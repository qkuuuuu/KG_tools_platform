"""DSL 导入/预览 Schema 路由"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID, uuid4
from app.database import get_db
from app.models import SchemaConstraint, Project, User
from app.utils.security import get_current_user
from app.services.schema_dsl import parse_dsl

logger = logging.getLogger(__name__)
router = APIRouter()


class DSLPreviewRequest(BaseModel):
    dsl: str


class DSLImportRequest(BaseModel):
    dsl: str


from pydantic import BaseModel as PydanticBase


class DSLPreviewResponse(PydanticBase):
    namespace: str
    entities: List[dict]
    relations: List[dict]
    error: str = None


class DSLImportResponse(PydanticBase):
    namespace: str
    entities_created: int
    relations_created: int


@router.post("/{project_id}/schemas/preview-dsl", response_model=DSLPreviewResponse)
async def preview_dsl(
    project_id: UUID,
    body: DSLPreviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """预览 DSL 解析结果（不入库）"""
    result = parse_dsl(body.dsl)
    return result


@router.post("/{project_id}/schemas/import-dsl", response_model=DSLImportResponse)
async def import_dsl(
    project_id: UUID,
    body: DSLImportRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """解析 DSL 并入库到 schema_constraints 表（兼容旧逻辑）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    result = parse_dsl(body.dsl)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    # 先删除该项目旧关系约束
    db.query(SchemaConstraint).filter(SchemaConstraint.project_id == project_id).delete()

    # 为每个关系创建 SchemaConstraint（同时持久化中文标签，避免抽取结果中英混排）
    count = 0
    for rel in result["relations"]:
        db.add(SchemaConstraint(
            id=uuid4(),
            project_id=project_id,
            subject_type=rel["subject_type"],
            predicate=rel["predicate"],
            object_type=rel["object_type"],
            subject_label=rel.get("subject_label"),
            predicate_label=rel.get("predicate_label"),
            object_label=rel.get("object_label"),
        ))
        count += 1

    db.commit()

    return {
        "namespace": result["namespace"],
        "entities_created": len(result["entities"]),
        "relations_created": count,
    }
