"""设备配置路由 - 按模块配置 CPU/GPU
统一使用 ORM DeviceConfig 模型，与 models/__init__.py 保持一致
"""
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, DeviceConfig
from app.schemas import DeviceConfigItem
from app.utils.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


# 向后兼容：extraction.py 等模块可能引用此名称
# 提供一个基于 ORM 的查询函数替代原来的 Core Table
def get_device_configs(db: Session, project_id):
    """查询项目的设备配置列表"""
    return db.query(DeviceConfig).filter(
        DeviceConfig.project_id == project_id
    ).all()


# ==================== 路由 ====================
@router.get("/{project_id}/device-configs")
async def list_device_configs(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """列出设备配置，缺失模块补默认"""
    result = db.query(DeviceConfig).filter(
        DeviceConfig.project_id == project_id
    ).all()
    rows = [
        {
            "id": str(r.id),
            "module_name": r.module_name,
            "device": r.device,
            "gpu_id": r.gpu_id,
        }
        for r in result
    ]
    defaults = {
        "MINERU": {"device": "GPU", "gpu_id": 0},
        "UIE": {"device": "CPU", "gpu_id": 0},
        "DEEPKE": {"device": "CPU", "gpu_id": 0},
        "EMBEDDING": {"device": "CPU", "gpu_id": 0},
    }
    existing = {r["module_name"] for r in rows}
    for name, cfg in defaults.items():
        if name not in existing:
            rows.append({"id": "", "module_name": name, **cfg})
    return rows


@router.put("/{project_id}/device-configs")
async def update_device_configs(
    project_id: uuid.UUID,
    configs: list[DeviceConfigItem],
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """全量替换设备配置"""
    # 先删除旧配置
    db.query(DeviceConfig).filter(
        DeviceConfig.project_id == project_id
    ).delete(synchronize_session=False)
    # 再插入新配置
    for cfg in configs:
        db.add(DeviceConfig(
            id=uuid.uuid4(),
            project_id=project_id,
            module_name=cfg.module_name,
            device=cfg.device,
            gpu_id=cfg.gpu_id,
        ))
    db.commit()
    return {"status": "ok", "count": len(configs)}
