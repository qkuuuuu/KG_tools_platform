"""项目路由"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.database import get_db
from app.models import Project, User, Document
from app.schemas import ProjectCreate, ProjectResponse
from app.utils.security import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=List[ProjectResponse])
async def list_projects(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.post("/", response_model=ProjectResponse)
async def create_project(body: ProjectCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    project = Project(name=body.name, description=body.description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: UUID, body: ProjectCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.name = body.name
    project.description = body.description
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: UUID, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    project_name = project.name
    pid_str = str(project_id)
    
    # 删除上传的原始文件（磁盘清理）
    files_deleted = 0
    try:
        docs = db.query(Document).filter(Document.project_id == project_id).all()
        for doc in docs:
            if doc.file_path and os.path.exists(doc.file_path):
                try:
                    os.remove(doc.file_path)
                    files_deleted += 1
                except Exception as e:
                    logger.warning(f"删除文件失败 {doc.file_path}: {e}")
    except Exception as e:
        logger.warning(f"清理上传文件时出错: {e}")

    # 级联删除 Neo4j 图谱子图（项目隔离）
    try:
        from app.services.fusion.neo4j_exporter import delete_project_graph
        from app.config import settings as s
        result = delete_project_graph(
            pid_str,
            neo4j_url=s.NEO4J_URL,
            neo4j_user=s.NEO4J_USER,
            neo4j_password=s.NEO4J_PASSWORD,
        )
        neo4j_msg = f"Neo4j: 删除 {result.get('deleted_nodes', 0)} 节点, {result.get('deleted_rels', 0)} 关系"
    except Exception as e:
        neo4j_msg = f"Neo4j 清理跳过: {str(e)}"

    # 删除 PostgreSQL 数据（级联 CASCADE 自动清理所有关联表）
    db.delete(project)
    db.commit()
    return {
        "message": f"项目 '{project_name}' 删除成功",
        "neo4j": neo4j_msg,
        "files_deleted": files_deleted,
    }
