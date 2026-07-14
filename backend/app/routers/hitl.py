"""HITL 人工审核路由"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from app.database import get_db
from datetime import datetime, timezone
from app.models import TripleRaw, AuditLog, User
from app.schemas import TripleResponse, ReviewRequest
from app.utils.security import get_current_user, require_admin

router = APIRouter()


@router.get("/pending/{project_id}", response_model=List[TripleResponse])
async def get_pending_triples(
    project_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ambiguous_only: bool = Query(False, description="仅返回待消歧(needs_disambiguation)的三元组"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """获取待审核三元组列表（分配式：未分配或分配给当前人的）

    ambiguous_only=true 时，仅返回入库前被标记为"语义相似需消歧"的三元组（需求4）。
    """
    offset = (page - 1) * page_size
    q = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PENDING",
    )
    if ambiguous_only:
        q = q.filter(TripleRaw.needs_disambiguation == True)  # noqa: E712
    triples = q.order_by(TripleRaw.created_at.desc()).offset(offset).limit(page_size).all()
    return triples


@router.get("/assigned/{username}")
async def get_assigned_triples(
    username: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """获取分配给某人的三元组"""
    triples = db.query(TripleRaw).filter(
        TripleRaw.assigned_to == username,
        TripleRaw.status == "PENDING",
    ).all()
    return [
        {
            "id": str(t.id),
            "subject": t.subject,
            "predicate": t.predicate,
            "object": t.object,
            "llm_confidence": t.llm_confidence,
            "chunk_text": t.chunk_text,
            "doc_id": str(t.doc_id),
            "status": t.status,
        }
        for t in triples
    ]


@router.post("/assign")
async def assign_triple(
    triple_id: UUID,
    username: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """分配三元组给审核人"""
    triple = db.query(TripleRaw).filter(TripleRaw.id == triple_id).first()
    if not triple:
        raise HTTPException(status_code=404, detail="三元组不存在")
    triple.assigned_to = username
    db.commit()
    return {"message": "分配成功"}


@router.post("/review")
async def review_triples(body: ReviewRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """提交审核结果"""
    processed = 0
    for review in body.reviews:
        triple = db.query(TripleRaw).filter(TripleRaw.id == review.triple_id).first()
        if not triple:
            continue

        old_data = {
            "subject": triple.subject,
            "predicate": triple.predicate,
            "object": triple.object,
        }

        if review.action == "PASS":
            triple.status = "PASSED"
        elif review.action == "REJECT":
            triple.status = "REJECTED"
        elif review.action == "MODIFY":
            triple.status = "PASSED"
            if review.modified_subject:
                triple.subject = review.modified_subject
            if review.modified_predicate:
                triple.predicate = review.modified_predicate
            if review.modified_object:
                triple.object = review.modified_object

        new_data = {
            "subject": triple.subject,
            "predicate": triple.predicate,
            "object": triple.object,
        }

        # 记录血缘
        log = AuditLog(
            triple_id=triple.id,
            action=review.action,
            operator=body.operator,
            old_data=old_data,
            new_data=new_data,
            timestamp=datetime.now(timezone.utc),
        )
        db.add(log)
        processed += 1

    db.commit()
    return {"status": "success", "processed_count": processed}


@router.get("/reviewed/{project_id}")
async def get_reviewed_triples(
    project_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="PASSED / REJECTED"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """获取已审核三元组列表"""
    query = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status.in_(["PASSED", "REJECTED"]),
    )
    if status:
        query = query.filter(TripleRaw.status == status)
    total = query.count()
    offset = (page - 1) * page_size
    records = query.order_by(TripleRaw.created_at.desc()).offset(offset).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": records,
    }


@router.post("/revoke/{triple_id}")
async def revoke_review(
    triple_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤回审核：将 PASSED/REJECTED 改回 PENDING"""
    triple = db.query(TripleRaw).filter(TripleRaw.id == triple_id).first()
    if not triple:
        raise HTTPException(status_code=404, detail="三元组不存在")
    if triple.status not in ("PASSED", "REJECTED"):
        raise HTTPException(status_code=400, detail="只能撤回已审核的三元组")
    old_status = triple.status
    triple.status = "PENDING"
    # 记录撤回日志
    log = AuditLog(
        triple_id=triple.id,
        action="REVOKE",
        operator=current_user.username,
        old_data={"status": old_status},
        new_data={"status": "PENDING"},
    )
    db.add(log)
    db.commit()
    return {"message": "撤回成功", "triple_id": str(triple.id)}


@router.delete("/triples/{triple_id}")
async def delete_triple(
    triple_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """彻底删除三元组"""
    triple = db.query(TripleRaw).filter(TripleRaw.id == triple_id).first()
    if not triple:
        raise HTTPException(status_code=404, detail="三元组不存在")
    db.delete(triple)
    db.commit()
    return {"message": "已删除", "triple_id": str(triple_id)}


@router.get("/stats/{project_id}")
async def get_hitl_stats(project_id: UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """获取审核统计"""
    total = db.query(TripleRaw).filter(TripleRaw.project_id == project_id).count()
    pending = db.query(TripleRaw).filter(TripleRaw.project_id == project_id, TripleRaw.status == "PENDING").count()
    passed = db.query(TripleRaw).filter(TripleRaw.project_id == project_id, TripleRaw.status == "PASSED").count()
    rejected = db.query(TripleRaw).filter(TripleRaw.project_id == project_id, TripleRaw.status == "REJECTED").count()
    return {"total": total, "pending": pending, "passed": passed, "rejected": rejected}
