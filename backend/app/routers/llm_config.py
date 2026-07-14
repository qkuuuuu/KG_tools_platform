"""LLM 配置路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict
from uuid import UUID
from app.database import get_db
from app.models import LLMConfig, User
from app.schemas import LLMConfigUpdate, LLMConfigResponse
from app.utils.security import get_current_user, require_admin
from app.config import encrypt_value, decrypt_value
from app.services.default_prompts import STAGE_DEFAULT_PROMPTS

router = APIRouter()


@router.get("/{project_id}/llm-configs", response_model=List[LLMConfigResponse])
async def get_llm_configs(project_id: UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    configs = db.query(LLMConfig).filter(LLMConfig.project_id == project_id).all()
    return configs


@router.get("/{project_id}/llm-config-default-prompts")
async def get_default_prompts(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """返回各阶段默认 Prompt 模板，供前端「自定义 Prompt」输入框预填充（需求1）"""
    return {"stages": STAGE_DEFAULT_PROMPTS}


@router.put("/{project_id}/llm-configs", response_model=List[LLMConfigResponse])
async def update_llm_configs(
    project_id: UUID,
    configs: List[LLMConfigUpdate],
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),  # H1 修复: 更新 LLM 配置需 admin 权限
):
    for cfg in configs:
        existing = db.query(LLMConfig).filter(
            LLMConfig.project_id == project_id,
            LLMConfig.pipeline_stage == cfg.pipeline_stage,
        ).first()
        if existing:
            existing.api_provider = cfg.api_provider
            existing.base_url = cfg.base_url
            if cfg.api_key:  # 只有传了非空 key 才更新
                existing.api_key_encrypted = encrypt_value(cfg.api_key)
            existing.model_name = cfg.model_name
            existing.prompt = cfg.prompt  # 自定义 Prompt（可为空 -> 回退默认）
            existing.enabled = cfg.enabled  # 向量模型开关（仅 EMBEDDING 阶段生效）
        else:
            # 新建配置时必须有 api_key
            if not cfg.api_key:
                raise HTTPException(
                    status_code=400,
                    detail=f"阶段 {cfg.pipeline_stage} 的新配置必须提供 api_key"
                )
            db.add(LLMConfig(
                project_id=project_id,
                pipeline_stage=cfg.pipeline_stage,
                api_provider=cfg.api_provider,
                base_url=cfg.base_url,
                api_key_encrypted=encrypt_value(cfg.api_key),
                model_name=cfg.model_name,
                prompt=cfg.prompt,
                enabled=cfg.enabled,
            ))
    db.commit()
    return db.query(LLMConfig).filter(LLMConfig.project_id == project_id).all()
