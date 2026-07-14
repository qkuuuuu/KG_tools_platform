"""文档上传与解析路由 - 接入真实解析引擎"""
import os
import uuid as uuid_lib
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
from app.database import get_db
from app.models import Document, TaskStatus, User
from app.utils.security import get_current_user, require_admin
from app.utils.http import attachment_filename
from app.config import settings
from app.services.parsers import parse_document

router = APIRouter()
logger = logging.getLogger(__name__)

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


def _parse_document_bg(doc_id: UUID, file_path: str, engine: str, project_id: UUID, task_id: UUID):
    """后台任务：真实解析文档"""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return
        task = db.query(TaskStatus).filter(TaskStatus.id == task_id).first()
        if task:
            task.status = "RUNNING"
            task.progress = 20
            db.commit()
            # S5: 通过 WebSocket 推送进度
            _broadcast(project_id, task_id, "PARSE", task.status, task.progress)

        try:
            md_content, score = parse_document(file_path, engine)
            doc.md_content = md_content
            doc.status = "DONE"
            doc.llm_parse_score = score
            if task:
                task.status = "DONE"
                task.progress = 100
                task.result = {"doc_id": str(doc_id), "score": score, "content_length": len(md_content)}
            db.commit()
            _broadcast(project_id, task_id, "PARSE",
                       task.status if task else "DONE",
                       task.progress if task else 100,
                       task.result if task else None)
        except Exception as e:
            logger.exception(f"文档解析失败 doc_id={doc_id} engine={engine}")
            if doc:
                doc.status = "FAILED"
            if task:
                task.status = "FAILED"
                task.error_message = str(e)
            db.commit()
            _broadcast(project_id, task_id, "PARSE", "FAILED", 0)
            # L13: 解析失败后清理磁盘上的上传文件
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
    finally:
        db.close()


def _broadcast(project_id, task_id, task_type, status, progress, result=None):
    """S5: 通过 WebSocket 广播任务进度更新"""
    try:
        from app.routers.ws import broadcast_task_update
        broadcast_task_update(str(project_id), str(task_id), task_type, status, progress, result)
    except Exception:
        pass


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    project_id: UUID = Form(...),
    parse_engine: str = Form("auto"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"文件大小不能超过 {settings.MAX_FILE_SIZE_MB}MB")

    ext = os.path.splitext(file.filename)[1]
    stored_name = f"{uuid_lib.uuid4()}{ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, stored_name)
    with open(file_path, "wb") as f:
        f.write(content)

    # 根据文件扩展名自动选择解析引擎
    auto_engine = "pdfplumber"  # 默认
    ext_lower = ext.lower()
    if ext_lower == ".csv":
        auto_engine = "csv"
    elif ext_lower in (".xlsx", ".xls"):
        auto_engine = "excel"
    elif ext_lower == ".docx":
        auto_engine = "python-docx"
    elif ext_lower in (".txt", ".md", ".html"):
        auto_engine = "txt"
    
    # M1 修复: "auto" 表示自动检测，其他值表示用户显式指定引擎
    actual_engine = auto_engine if parse_engine == "auto" else parse_engine

    doc = Document(
        project_id=project_id,
        file_name=file.filename,
        file_path=file_path,
        parse_engine_used=actual_engine,  # M2 修复: 记录实际使用的引擎而非原始值
        status="PROCESSING",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    task = TaskStatus(project_id=project_id, task_type="PARSE", status="PENDING", doc_id=doc.id)
    db.add(task)
    db.commit()

    background_tasks.add_task(_parse_document_bg, doc.id, file_path, actual_engine, project_id, task.id)

    return {
        "doc_id": str(doc.id),
        "task_id": str(task.id),
        "file_name": file.filename,
        "status": "PROCESSING",
    }


@router.get("/tasks")
async def list_tasks(
    project_id: Optional[UUID] = None,
    task_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """查询任务列表（支持按项目/类型/状态过滤）"""
    q = db.query(TaskStatus)
    if project_id:
        q = q.filter(TaskStatus.project_id == project_id)
    if task_type:
        q = q.filter(TaskStatus.task_type == task_type)
    if status:
        q = q.filter(TaskStatus.status == status)
    tasks = q.order_by(TaskStatus.created_at.desc()).limit(100).all()
    result = []
    for t in tasks:
        doc_name = None
        if hasattr(t, 'doc_id') and t.doc_id:
            doc = db.query(Document).filter(Document.id == t.doc_id).first()
            if doc:
                doc_name = doc.file_name
        result.append({
            "id": str(t.id),
            "project_id": str(t.project_id),
            "task_type": t.task_type,
            "status": t.status,
            "progress": t.progress,
            "result": t.result,
            "error_message": t.error_message,
            "doc_id": str(t.doc_id) if hasattr(t, 'doc_id') and t.doc_id else None,
            "doc_name": doc_name,
            "extraction_method": (t.result or {}).get("method") if t.task_type == "EXTRACT" else None,
            "created_at": str(t.created_at),
            "completed_at": str(t.completed_at) if t.completed_at else None,
        })
    return result


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    task = db.query(TaskStatus).filter(TaskStatus.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "id": str(task.id),
        "task_type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "result": task.result,
        "error_message": task.error_message,
    }


@router.get("/documents/{doc_id}")
async def get_document(doc_id: UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {
        "id": str(doc.id),
        "project_id": str(doc.project_id),
        "file_name": doc.file_name,
        "md_content": doc.md_content,
        "parse_engine_used": doc.parse_engine_used,
        "llm_parse_score": doc.llm_parse_score,
        "status": doc.status,
        "created_at": str(doc.created_at),
    }


@router.get("/documents/{doc_id}/content")
async def get_document_content(doc_id: UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"md_content": doc.md_content}


@router.get("/documents/{doc_id}/download")
async def download_markdown(
    doc_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """下载解析后的 Markdown 文件"""
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not doc.md_content:
        raise HTTPException(status_code=404, detail="文档尚未解析完成")

    base_name = os.path.splitext(doc.file_name)[0]
    download_name = f"{base_name}_parsed.md"

    return Response(
        content=doc.md_content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": attachment_filename(download_name),
        },
    )


@router.get("/documents")
async def list_documents(
    project_id: Optional[UUID] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Document)
    if project_id:
        q = q.filter(Document.project_id == project_id)
    if status:
        q = q.filter(Document.status == status)
    total = q.count()
    offset = (page - 1) * page_size
    docs = q.order_by(Document.created_at.desc()).offset(offset).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": str(d.id),
                "project_id": str(d.project_id),
                "file_name": d.file_name,
                "parse_engine_used": d.parse_engine_used,
                "status": d.status,
                "llm_parse_score": d.llm_parse_score,
                "created_at": str(d.created_at),
            }
            for d in docs
        ],
    }
