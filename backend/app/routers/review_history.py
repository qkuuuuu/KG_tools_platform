"""审核历史路由 - HITL 审核日志查询与统计"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.models import AuditLog, TripleRaw, User
from app.utils.security import get_current_user

router = APIRouter()


@router.get("/{project_id}/history")
async def get_review_history(
    project_id: UUID,
    operator: Optional[str] = Query(None, description="按审核人过滤"),
    action: Optional[str] = Query(None, description="按操作类型过滤: PASS/REJECT/MODIFY"),
    days: int = Query(30, ge=1, le=365, description="最近 N 天"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """获取审核历史记录"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = db.query(AuditLog).join(
        TripleRaw, AuditLog.triple_id == TripleRaw.id
    ).filter(
        TripleRaw.project_id == project_id,
        AuditLog.timestamp >= since,
    )
    if operator:
        query = query.filter(AuditLog.operator == operator)
    if action:
        query = query.filter(AuditLog.action == action)

    total = query.count()
    offset = (page - 1) * page_size
    logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": [
            {
                "id": str(log.id),
                "triple_id": str(log.triple_id),
                "action": log.action,
                "operator": log.operator,
                "old_data": log.old_data,
                "new_data": log.new_data,
                "timestamp": log.timestamp.isoformat() + "Z" if log.timestamp else "",
            }
            for log in logs
        ],
    }


@router.get("/{project_id}/stats")
async def get_review_stats(
    project_id: UUID,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """审核统计：通过率趋势、审核人贡献、操作分布"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = db.query(AuditLog).join(
        TripleRaw, AuditLog.triple_id == TripleRaw.id
    ).filter(
        TripleRaw.project_id == project_id,
        AuditLog.timestamp >= since,
    )
    all_logs = query.all()

    # 操作分布
    action_counts = {"PASS": 0, "REJECT": 0, "MODIFY": 0}
    operator_counts = {}
    daily_counts = {}

    for log in all_logs:
        action_counts[log.action] = action_counts.get(log.action, 0) + 1
        operator_counts[log.operator] = operator_counts.get(log.operator, 0) + 1
        day = log.timestamp.strftime("%Y-%m-%d") if log.timestamp else "unknown"
        if day not in daily_counts:
            daily_counts[day] = {"PASS": 0, "REJECT": 0, "MODIFY": 0}
        daily_counts[day][log.action] = daily_counts[day].get(log.action, 0) + 1

    total = len(all_logs)
    pass_rate = (action_counts.get("PASS", 0) + action_counts.get("MODIFY", 0)) / total * 100 if total else 0

    # 日趋势排序
    daily_trend = [{"date": k, **v} for k, v in sorted(daily_counts.items())]

    return {
        "total_reviews": total,
        "pass_rate": round(pass_rate, 1),
        "action_distribution": action_counts,
        "operator_distribution": sorted(
            [{"operator": k, "count": v} for k, v in operator_counts.items()],
            key=lambda x: x["count"], reverse=True,
        ),
        "daily_trend": daily_trend,
    }
