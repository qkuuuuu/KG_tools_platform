"""搜索路由 - 三元组全文搜索与过滤"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
from app.database import get_db
from app.models import TripleRaw, User
from app.utils.security import get_current_user

router = APIRouter()


@router.get("/{project_id}/triples-search")
async def search_triples(
    project_id: UUID,
    q: str = Query(..., min_length=1, description="搜索关键词"),
    field: str = Query("all", description="搜索字段: all/subject/predicate/object"),
    status: Optional[str] = Query(None, description="状态过滤: PENDING/PASSED/REJECTED/FUSED"),
    method: Optional[str] = Query(None, description="抽取方法过滤"),
    min_confidence: float = Query(0, ge=0, le=100),
    max_confidence: float = Query(100, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """三元组搜索与过滤"""
    query = db.query(TripleRaw).filter(TripleRaw.project_id == project_id)

    if status:
        query = query.filter(TripleRaw.status == status)
    if method:
        query = query.filter(TripleRaw.extraction_method == method)
    query = query.filter(
        ((TripleRaw.llm_confidence >= min_confidence) | (TripleRaw.llm_confidence.is_(None))),
        ((TripleRaw.llm_confidence <= max_confidence) | (TripleRaw.llm_confidence.is_(None))),
    )

    # 全文搜索
    keyword = f"%{q}%"
    if field == "subject":
        query = query.filter(TripleRaw.subject.ilike(keyword))
    elif field == "predicate":
        query = query.filter(TripleRaw.predicate.ilike(keyword))
    elif field == "object":
        query = query.filter(TripleRaw.object.ilike(keyword))
    else:  # all
        query = query.filter(
            (TripleRaw.subject.ilike(keyword)) |
            (TripleRaw.predicate.ilike(keyword)) |
            (TripleRaw.object.ilike(keyword))
        )

    total = query.count()
    offset = (page - 1) * page_size
    triples = query.order_by(TripleRaw.llm_confidence.desc()).offset(offset).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": [
            {
                "id": str(t.id),
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "confidence": t.llm_confidence,
                "method": t.extraction_method,
                "status": t.status,
                "chunk_text": t.chunk_text,
                "doc_id": str(t.doc_id) if t.doc_id else "",
            }
            for t in triples
        ],
    }
