"""应用配置 - 从环境变量读取，本地开发也可用 .env"""
import os
import base64
import hashlib
import logging
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from cryptography.fernet import Fernet

# 在 Settings 类定义之前加载 .env 文件，确保 _get_env_or_fail 能读到
load_dotenv()

logger = logging.getLogger(__name__)


def _make_fernet_key(raw: str) -> bytes:
    """使用 PBKDF2 从任意密钥字符串派生 32 字节 Fernet 密钥

    相比简单重复字符串，PBKDF2 提供更强的密钥派生安全性。
    """
    salt = b"kg_platform_salt_v1"
    key = hashlib.pbkdf2_hmac('sha256', raw.encode(), salt, 100000, dklen=32)
    return base64.urlsafe_b64encode(key)


def _get_env_or_fail(key: str, default: str, prod_required: bool = False) -> str:
    """读取环境变量，生产环境强制要求关键凭据存在"""
    val = os.environ.get(key, default)
    if prod_required and val == default:
        env = os.environ.get("KG_ENV", "development").lower()
        if env in ("production", "prod"):
            raise RuntimeError(
                f"生产环境必须设置环境变量 {key}，请勿使用默认值。"
                f"请在 .env 或环境变量中配置。"
            )
    return val


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = _get_env_or_fail(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:kg_dev_password_2026@localhost:5432/kg_platform",
        prod_required=True,
    )

    # Neo4j
    NEO4J_URL: str = os.environ.get("NEO4J_URL", "bolt://localhost:7687")
    NEO4J_USER: str = os.environ.get("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.environ.get("NEO4J_PASSWORD", "kg_neo4j_2026")

    # JWT — 优先环境变量，生产环境强制要求
    JWT_SECRET: str = _get_env_or_fail(
        "KG_JWT_SECRET",
        "kg_jwt_secret_change_in_production_2026",
        prod_required=True,
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # 加密密钥 — 优先环境变量，生产环境强制要求
    ENCRYPTION_KEY: str = _get_env_or_fail(
        "KG_ENCRYPTION_KEY",
        "kg_encryption_key_32bytes!changeme!",
        prod_required=True,
    )

    # 文件上传 — 使用相对路径，可移植部署
    UPLOAD_DIR: str = os.environ.get("KG_UPLOAD_DIR", os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "uploads",
    ))
    MAX_FILE_SIZE_MB: int = 50

    # LLM 质检阈值（可配置）
    CONFIDENCE_THRESHOLD: float = 90.0

    # 融合阈值
    FUSION_AUTO_THRESHOLD: float = 95.0
    FUSION_MANUAL_THRESHOLD: float = 80.0

    class Config:
        env_file = ".env"


settings = Settings()

# 确保上传目录存在
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

# Fernet 加密器
fernet = Fernet(_make_fernet_key(settings.ENCRYPTION_KEY))


def encrypt_value(plaintext: str) -> str:
    """加密敏感字段"""
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """解密敏感字段"""
    if not ciphertext:
        return ""
    return fernet.decrypt(ciphertext.encode()).decode()
