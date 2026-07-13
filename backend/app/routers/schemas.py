"""Schema 路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
import uuid
from app.database import get_db
from app.models import SchemaConstraint, Project, User
from app.schemas import SchemaItem, SchemaResponse
from app.utils.security import get_current_user, require_admin
from app.services import schema_dsl as _dsl_service

router = APIRouter()


@router.get("/{project_id}/schemas", response_model=List[SchemaResponse])
async def get_schemas(project_id: UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(SchemaConstraint).filter(SchemaConstraint.project_id == project_id).all()


@router.put("/{project_id}/schemas", response_model=List[SchemaResponse])
async def update_schemas(
    project_id: UUID,
    schemas: List[SchemaItem],
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),  # H1 修复: 修改 Schema 需 admin 权限
):
    # 保留已有中文标签（表格编辑只填英文标识符，避免覆盖 DSL 导入的中文）
    existing = {
        (s.subject_type, s.predicate, s.object_type): s
        for s in db.query(SchemaConstraint).filter(SchemaConstraint.project_id == project_id).all()
    }
    db.query(SchemaConstraint).filter(SchemaConstraint.project_id == project_id).delete()
    for s in schemas:
        prev = existing.get((s.subject_type, s.predicate, s.object_type))
        db.add(SchemaConstraint(
            project_id=project_id,
            subject_type=s.subject_type,
            predicate=s.predicate,
            object_type=s.object_type,
            subject_label=prev.subject_label if prev else None,
            predicate_label=prev.predicate_label if prev else None,
            object_label=prev.object_label if prev else None,
        ))
    db.commit()
    return db.query(SchemaConstraint).filter(SchemaConstraint.project_id == project_id).all()


@router.delete("/{project_id}/schemas")
async def delete_all_schemas(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),  # H1 修复: 删除 Schema 需 admin 权限
):
    """一键删除项目的所有 Schema 约束"""
    count = db.query(SchemaConstraint).filter(SchemaConstraint.project_id == project_id).delete()
    db.commit()
    return {"status": "ok", "deleted": count}


@router.post("/{project_id}/schemas/preview-dsl")
async def preview_dsl(project_id: UUID, body: dict, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """预览 DSL 解析结果（不入库）"""
    dsl = body.get("dsl", "")
    result = _dsl_service.parse_dsl(dsl)
    return result


@router.post("/{project_id}/schemas/import-dsl")
async def import_dsl(project_id: UUID, body: dict, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """解析 DSL 并入库到 schema_constraints 表"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    result = _dsl_service.parse_dsl(body.get("dsl", ""))
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    _dsl_service.save_schema_constraints(db, project_id, result["relations"])
    return {"namespace": result["namespace"], "entities_count": len(result["entities"]), "relations_count": len(result["relations"])}
