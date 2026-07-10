"""已通过三元组路由 - 统计 / 列表 / Neo4j 同步"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date
from uuid import UUID
from app.database import get_db
from app.models import TripleRaw, Project, User
from app.utils.security import get_current_user

router = APIRouter()


@router.get("/{project_id}/stats")
async def get_passed_triples_stats(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """已通过三元组统计"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    base_q = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PASSED",
    )

    total = base_q.count()

    # 按引擎统计
    by_engine_rows = db.query(
        TripleRaw.extraction_method,
        func.count(TripleRaw.id),
    ).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PASSED",
    ).group_by(TripleRaw.extraction_method).all()
    by_engine = {row[0]: row[1] for row in by_engine_rows}

    # 按关系统计
    by_relation_rows = db.query(
        TripleRaw.predicate,
        func.count(TripleRaw.id),
    ).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PASSED",
    ).group_by(TripleRaw.predicate).all()
    by_relation = {row[0]: row[1] for row in by_relation_rows}

    # 按日期统计
    by_time_rows = db.query(
        cast(TripleRaw.created_at, Date).label("d"),
        func.count(TripleRaw.id),
    ).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PASSED",
    ).group_by("d").order_by("d").all()
    by_time = [{"date": str(row[0]), "count": row[1]} for row in by_time_rows]

    # 近 7 天
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_7_days = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PASSED",
        TripleRaw.created_at >= seven_days_ago,
    ).count()

    return {
        "total": total,
        "by_engine": by_engine,
        "by_relation": by_relation,
        "by_time": by_time,
        "recent_7_days": recent_7_days,
    }


@router.get("/{project_id}")
async def list_passed_triples(
    project_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query("", description="关键词搜索 subject/object"),
    relation: str = Query("", description="关系类型过滤"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """已通过三元组分页列表"""
    q = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PASSED",
    )
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(
            (TripleRaw.subject.ilike(kw)) | (TripleRaw.object.ilike(kw))
        )
    if relation:
        q = q.filter(TripleRaw.predicate == relation)

    total = q.count()
    offset = (page - 1) * page_size
    triples = q.order_by(TripleRaw.created_at.desc()).offset(offset).limit(page_size).all()

    return {
        "items": [
            {
                "id": str(t.id),
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "extraction_method": t.extraction_method,
                "llm_confidence": t.llm_confidence,
                "created_at": str(t.created_at),
            }
            for t in triples
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/{project_id}/sync-neo4j")
async def sync_passed_triples_to_neo4j(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """同步所有 PASSED 状态的三元组到 Neo4j"""
    from app.config import settings as s
    from app.services.fusion.neo4j_exporter import try_neo4j_import

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    triples = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PASSED",
    ).all()

    if not triples:
        return {"status": "ok", "synced": 0, "failed": 0}

    triples_data = [
        {
            "subject": t.subject,
            "predicate": t.predicate,
            "object": t.object,
            "confidence": t.llm_confidence or 80,
        }
        for t in triples
    ]

    result = try_neo4j_import(
        triples_data,
        project_id=str(project_id),
        project_name=project.name,
        neo4j_url=s.NEO4J_URL,
        neo4j_user=s.NEO4J_USER,
        neo4j_password=s.NEO4J_PASSWORD,
    )

    if result.get("status") == "success":
        synced = result.get("relations_created", len(triples_data))
        return {"status": "ok", "synced": synced, "failed": 0}
    else:
        return {"status": "ok", "synced": 0, "failed": len(triples_data), "error": result.get("error", "")}
