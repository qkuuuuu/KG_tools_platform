"""抽取与质检路由 - 多引擎抽取池 + LLM 质检
标签: ⚠️ 后台任务耗时较长(LLM 抽取 ~15s/块)
"""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Form, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from app.database import get_db
from app.models import Document, TripleRaw, SchemaConstraint, TaskStatus, User, AuditLog
from app.utils.security import get_current_user, require_admin
from app.config import settings
from app.services.llm_engine import get_llm_config_for_project
from app.services.extraction import extract_triples, get_available_engines
from app.services.quality import llm_quality_review, rule_based_quality

router = APIRouter()
logger = logging.getLogger(__name__)


def _broadcast(project_id, task_id, task_type, status, progress, result=None):
    """S5: 通过 WebSocket 广播任务进度更新"""
    try:
        from app.routers.ws import broadcast_task_update
        broadcast_task_update(str(project_id), str(task_id), task_type, status, progress, result)
    except Exception:
        pass


@router.get("/engines")
async def list_engines():
    """获取可用的抽取引擎列表"""
    return {"engines": get_available_engines()}


@router.post("/upload-script")
async def upload_script(
    file: UploadFile = File(...),
    description: str = Form(""),
    _: User = Depends(require_admin),
):
    """上传 Python 自定义抽取脚本"""
    if not file.filename or not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="请上传 .py 文件")
    
    content = await file.read()
    if len(content) > 1 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="脚本文件超过 1MB 限制")
    
    from app.services.extraction.custom_script_extractor import save_uploaded_script
    try:
        meta = save_uploaded_script(file.filename, content, description)
        return {"status": "ok", "script_id": meta["script_id"], "filename": meta["filename"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存脚本失败: {e}")


@router.get("/scripts")
async def list_scripts(
    _: User = Depends(get_current_user),
):
    """列出已上传的自定义脚本"""
    from app.services.extraction.custom_script_extractor import list_scripts
    return {"scripts": list_scripts()}


@router.delete("/scripts/{script_id}")
async def delete_script(
    script_id: str,
    _: User = Depends(require_admin),
):
    """删除已上传的脚本"""
    from app.services.extraction.custom_script_extractor import delete_script as _delete
    ok = _delete(script_id)
    if not ok:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return {"status": "ok"}


def _extract_triples_bg(doc_id: UUID, extraction_method: str, schema_ids: List[UUID], project_id: UUID, task_id: UUID, script_id: str = ""):
    """后台任务：多引擎抽取"""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc or not doc.md_content:
            return

        task = db.query(TaskStatus).filter(TaskStatus.id == task_id).first()
        if task:
            task.status = "RUNNING"
            task.progress = 20
            db.commit()
            _broadcast(project_id, task_id, "EXTRACT", task.status, task.progress)

        schemas = []
        if schema_ids:
            schemas = db.query(SchemaConstraint).filter(SchemaConstraint.id.in_(schema_ids)).all()
        else:
            schemas = db.query(SchemaConstraint).filter(SchemaConstraint.project_id == project_id).all()

        schema_list = [
            {"subject_type": s.subject_type, "predicate": s.predicate, "object_type": s.object_type}
            for s in schemas
        ]

        try:
            # 获取 LLM 配置（LLM_PROMPT 需要）
            cfg = None
            if extraction_method in ("LLM_PROMPT", "LLM"):
                cfg = get_llm_config_for_project(db, project_id, "EXTRACTION")
                if not cfg:
                    raise Exception("未配置 EXTRACTION 阶段的 LLM，请先在配置页设置")

            # ===== 读取设备配置（使用 ORM 模型）=====
            from app.models import DeviceConfig
            dev_rows = db.query(DeviceConfig).filter(
                DeviceConfig.project_id == project_id
            ).all()
            device_config = {
                r.module_name: {"device": r.device, "gpu_id": r.gpu_id}
                for r in dev_rows
            }

            if task:
                task.progress = 40
                db.commit()
                _broadcast(project_id, task_id, "EXTRACT", "RUNNING", 40)

            # ===== 统一调用多引擎抽取池 =====
            extra_kwargs = {}
            if extraction_method == "CUSTOM_SCRIPT" and script_id:
                extra_kwargs["script_id"] = script_id

            triples_data = extract_triples(
                method=extraction_method,
                md_content=doc.md_content,
                schemas=schema_list,
                cfg=cfg,
                device_config=device_config,
                **extra_kwargs,
            )

            if task:
                task.progress = 80
                db.commit()
                _broadcast(project_id, task_id, "EXTRACT", "RUNNING", 80)

            # ===== 规则预校验 =====
            triples_data = rule_based_quality(triples_data)

            # ===== 去重 =====
            seen_keys = set()
            unique_triples = []
            for t in triples_data:
                key = (t.get("subject", "").strip().lower(),
                       t.get("predicate", "").strip().lower(),
                       t.get("object", "").strip().lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_triples.append(t)
            triples_data = unique_triples

            # 写入数据库
            for t in triples_data:
                triple = TripleRaw(
                    doc_id=doc_id,
                    project_id=project_id,
                    task_id=task_id,
                    subject=t.get("subject", ""),
                    predicate=t.get("predicate", ""),
                    object=t.get("object", ""),
                    extraction_method=t.get("extraction_method", extraction_method),
                    llm_confidence=t.get("confidence"),
                    chunk_text=(t.get("chunk") or t.get("source_chunk", ""))[:500],
                    status="PENDING",
                )
                db.add(triple)

            if task:
                task.status = "DONE"
                task.progress = 100
                task.result = {
                    "extracted_count": len(triples_data),
                    "method": extraction_method,
                    "schema_count": len(schema_list),
                }
            db.commit()
            _broadcast(project_id, task_id, "EXTRACT", "DONE", 100, task.result if task else None)
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.exception(f"抽取任务失败 task_id={task_id}")
            if task:
                task.status = "FAILED"
                task.error_message = str(e)
            db.commit()
            _broadcast(project_id, task_id, "EXTRACT", "FAILED", 0)
    finally:
        db.close()


def _quality_check_bg(doc_id: UUID, threshold: float, project_id: UUID, task_id: UUID, benchmark_content: str = ""):
    """后台任务：LLM 质检
    
    Args:
        benchmark_content: 质检基准文件内容（约束文档/规范），由用户上传，可选
    """
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return

        triples = db.query(TripleRaw).filter(
            TripleRaw.doc_id == doc_id,
            TripleRaw.status == "PENDING",
        ).all()

        if not triples:
            return

        task = db.query(TaskStatus).filter(TaskStatus.id == task_id).first()
        if task:
            task.status = "RUNNING"
            task.progress = 20
            db.commit()
            _broadcast(project_id, task_id, "QUALITY_CHECK", "RUNNING", 20)

        try:
            # 获取 VERIFICATION 阶段的 LLM 配置
            cfg = get_llm_config_for_project(db, project_id, "VERIFICATION")

            if not cfg:
                # 未配置 LLM → 直接失败
                if task:
                    task.status = "FAILED"
                    task.error_message = "未配置 VERIFICATION 阶段的 LLM，请先在配置页设置"
                db.commit()
                _broadcast(project_id, task_id, "QUALITY_CHECK", "FAILED", 0)
                return

            passed = 0
            if task:
                task.progress = 40
                db.commit()
                _broadcast(project_id, task_id, "QUALITY_CHECK", "RUNNING", 40)

            # 用 LLM 质检
            triples_data = [
                {"subject": t.subject, "predicate": t.predicate, "object": t.object, "confidence": t.llm_confidence}
                for t in triples
            ]

            checked = llm_quality_review(triples_data, doc.md_content or "", cfg, threshold, benchmark_content=benchmark_content)

            if task:
                task.progress = 80
                db.commit()
                _broadcast(project_id, task_id, "QUALITY_CHECK", "RUNNING", 80)

            for t, check in zip(triples, checked):
                score = check.get("quality_score", t.llm_confidence or 50.0)
                t.llm_confidence = score
                verdict = check.get("verdict", "")
                if verdict == "PASS" or score >= threshold:
                    t.status = "PASSED"
                    passed += 1
                elif verdict == "REJECT":
                    t.status = "REJECTED"
                # UNCERTAIN: 保持 PENDING，等待 HITL

            if task:
                task.status = "DONE"
                task.progress = 100
                task.result = {
                    "total": len(triples),
                    "passed": passed,
                    "rejected": len([t for t in triples if t.status == "REJECTED"]),
                    "pending": len([t for t in triples if t.status == "PENDING"]),
                }
            db.commit()
            _broadcast(project_id, task_id, "QUALITY_CHECK", "DONE", 100, task.result if task else None)
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.exception(f"质检任务失败 task_id={task_id}")
            if task:
                task.status = "FAILED"
                task.error_message = str(e)
            db.commit()
            _broadcast(project_id, task_id, "QUALITY_CHECK", "FAILED", 0)
    finally:
        db.close()


@router.post("/extract")
async def trigger_extraction(
    background_tasks: BackgroundTasks,
    doc_id: UUID = Form(...),
    extraction_method: str = Form("LLM_PROMPT"),
    schema_ids: str = Form(""),
    script_id: str = Form(""),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 自定义脚本引擎需要 script_id
    if extraction_method == "CUSTOM_SCRIPT" and not script_id:
        raise HTTPException(status_code=400, detail="自定义脚本抽取需要选择脚本 (script_id)")

    schema_uuid_list = [UUID(s.strip()) for s in schema_ids.split(",") if s.strip()] if schema_ids else []

    task = TaskStatus(project_id=doc.project_id, task_type="EXTRACT", status="PENDING", doc_id=doc_id)
    db.add(task)
    db.commit()

    background_tasks.add_task(_extract_triples_bg, doc_id, extraction_method, schema_uuid_list, doc.project_id, task.id, script_id)

    return {"task_id": str(task.id), "status": "PENDING"}


@router.post("/quality-check")
async def trigger_quality_check(
    background_tasks: BackgroundTasks,
    doc_id: UUID = Form(...),
    threshold: float = Form(None),
    benchmark_file: UploadFile = File(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 前置校验：必须已配置 VERIFICATION 阶段的 LLM
    cfg = get_llm_config_for_project(db, doc.project_id, "VERIFICATION")
    if not cfg:
        raise HTTPException(status_code=400, detail="未配置 VERIFICATION 阶段的 LLM，请先在配置页设置")

    threshold = threshold or settings.CONFIDENCE_THRESHOLD

    # 读取基准文件内容（可选）
    benchmark_content = ""
    if benchmark_file and benchmark_file.filename:
        allowed_exts = ('.txt', '.md', '.json', '.docx', '.doc')
        if not benchmark_file.filename.lower().endswith(allowed_exts):
            raise HTTPException(status_code=400, detail="基准文件仅支持 txt/md/json/docx/doc 格式")
        raw = await benchmark_file.read()
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="基准文件超过 5MB 限制")
        # docx 需要特殊处理
        if benchmark_file.filename.lower().endswith('.docx'):
            try:
                import io
                from docx import Document as DocxDocument
                docx_doc = DocxDocument(io.BytesIO(raw))
                benchmark_content = "\n".join(p.text for p in docx_doc.paragraphs if p.text.strip())
            except ImportError:
                raise HTTPException(status_code=500, detail="服务器未安装 python-docx，无法解析 .docx 文件")
        elif benchmark_file.filename.lower().endswith('.doc'):
            raise HTTPException(status_code=400, detail="暂不支持 .doc 格式，请转换为 .docx")
        else:
            # txt/md/json 直接解码
            benchmark_content = raw.decode('utf-8', errors='replace')

    task = TaskStatus(project_id=doc.project_id, task_type="QUALITY_CHECK", status="PENDING", doc_id=doc_id)
    db.add(task)
    db.commit()

    background_tasks.add_task(_quality_check_bg, doc_id, threshold, doc.project_id, task.id, benchmark_content)

    return {"task_id": str(task.id), "status": "PENDING", "threshold": threshold, "benchmark_uploaded": bool(benchmark_content)}


@router.get("/triples/{project_id}/stats")
async def get_triple_stats(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """获取项目三元组统计（高效，不加载全部数据）"""
    base = db.query(TripleRaw).filter(TripleRaw.project_id == project_id)
    total = base.filter(TripleRaw.status != "MERGED").count()
    pending = base.filter(TripleRaw.status == "PENDING").count()
    passed = base.filter(TripleRaw.status == "PASSED").count()
    rejected = base.filter(TripleRaw.status == "REJECTED").count()
    return {"total": total, "pending": pending, "passed": passed, "rejected": rejected}


@router.get("/triples/{project_id}")
async def get_project_triples(
    project_id: UUID,
    status: str = None,
    include_merged: bool = False,
    limit: int = None,
    task_id: str = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """获取项目的所有三元组（可按状态/任务过滤）
    
    默认排除 MERGED 状态的三元组（已合并的重复项）
    """
    query = db.query(TripleRaw).filter(TripleRaw.project_id == project_id)
    if task_id:
        query = query.filter(TripleRaw.task_id == task_id)
    if status:
        query = query.filter(TripleRaw.status == status)
    elif not include_merged:
        query = query.filter(TripleRaw.status != "MERGED")
    query = query.order_by(TripleRaw.llm_confidence.desc())
    if limit:
        query = query.limit(limit)
    triples = query.all()
    return [
        {
            "id": str(t.id),
            "subject": t.subject,
            "predicate": t.predicate,
            "object": t.object,
            "confidence": t.llm_confidence,
            "method": t.extraction_method,
            "status": t.status,
        }
        for t in triples
    ]


# ====== 删除接口 ======

@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """删除文档解析任务：删除 Document + 关联 TaskStatus + 关联 TripleRaw（级联）"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    # 删除关联的 TaskStatus
    db.query(TaskStatus).filter(TaskStatus.doc_id == doc_id).delete(synchronize_session=False)
    # 删除关联的 AuditLog（通过 triple_id 关联 TripleRaw）
    triple_ids = [t.id for t in db.query(TripleRaw).filter(TripleRaw.doc_id == doc_id).all()]
    if triple_ids:
        db.query(AuditLog).filter(AuditLog.triple_id.in_(triple_ids)).delete(synchronize_session=False)
    # 删除关联的 TripleRaw
    db.query(TripleRaw).filter(TripleRaw.doc_id == doc_id).delete(synchronize_session=False)
    # 删除 Document
    db.delete(doc)
    db.commit()
    return {"status": "ok", "deleted": True}


@router.delete("/extract-tasks/{task_id}")
async def delete_extract_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """删除抽取任务：同时删除该任务产出的三元组
    
    兼容老数据：task_id 为 NULL 时，通过 doc_id + extraction_method 回溯删除
    """
    task = db.query(TaskStatus).filter(TaskStatus.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 优先通过 task_id 精确删除
    triple_ids = [
        t.id for t in db.query(TripleRaw.id)
        .filter(TripleRaw.task_id == task_id)
        .all()
    ]

    # 兼容老数据：task_id 为空时，通过 doc_id + extraction_method 回溯
    if not triple_ids and task.doc_id:
        method = (task.result or {}).get("method", "") if task.result else ""
        if method:
            triple_ids = [
                t.id for t in db.query(TripleRaw.id)
                .filter(
                    TripleRaw.doc_id == task.doc_id,
                    TripleRaw.extraction_method == method,
                    TripleRaw.task_id.is_(None),
                )
                .all()
            ]
        else:
            # 没有 method 信息，删除该文档下所有 task_id 为空的三元组
            triple_ids = [
                t.id for t in db.query(TripleRaw.id)
                .filter(
                    TripleRaw.doc_id == task.doc_id,
                    TripleRaw.task_id.is_(None),
                )
                .all()
            ]

    if triple_ids:
        db.query(AuditLog).filter(AuditLog.triple_id.in_(triple_ids)).delete(synchronize_session=False)
        db.query(TripleRaw).filter(TripleRaw.id.in_(triple_ids)).delete(synchronize_session=False)

    db.delete(task)
    db.commit()
    return {"status": "ok", "deleted": True, "triples_removed": len(triple_ids)}


@router.delete("/quality-tasks/{task_id}")
async def delete_quality_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """删除质检任务：仅删除 TaskStatus 记录"""
    task = db.query(TaskStatus).filter(TaskStatus.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete(task)
    db.commit()
    return {"status": "ok", "deleted": True}


@router.delete("/triples/{triple_id}")
async def delete_triple(
    triple_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """删除单条三元组"""
    triple = db.query(TripleRaw).filter(TripleRaw.id == triple_id).first()
    if not triple:
        raise HTTPException(status_code=404, detail="三元组不存在")
    db.delete(triple)
    db.commit()
    return {"status": "ok", "deleted": True}
