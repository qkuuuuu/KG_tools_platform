"""初始化数据库和管理员"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 注意：变量名必须与 app/config.py 中读取的一致（KG_ 前缀）
os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:kg_dev_password_2026@localhost:5432/kg_platform')
os.environ.setdefault('KG_JWT_SECRET', 'kg_jwt_secret_change_in_production_2026')
os.environ.setdefault('KG_ENCRYPTION_KEY', 'kg_encryption_key_32bytes!changeme!')
os.environ.setdefault('NEO4J_URL', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'kg123456')
# 管理员初始密码（仅用于本地开发首次创建；生产请通过环境变量 KG_ADMIN_PASSWORD 设置）
os.environ.setdefault('KG_ADMIN_PASSWORD', 'admin123')

from sqlalchemy import create_engine, text
from app.config import settings
from app.database import engine, Base
from app.models import User
from passlib.context import CryptContext

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 1. 建表
Base.metadata.create_all(engine)

# 1.5 新增列迁移（幂等，兼容旧库；create_all 不会给已存在的表加列）
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS prompt TEXT;"))
    conn.execute(text("ALTER TABLE llm_configs ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;"))
    conn.execute(text("ALTER TABLE triples_raw ADD COLUMN IF NOT EXISTS needs_disambiguation BOOLEAN NOT NULL DEFAULT FALSE;"))
    conn.execute(text("ALTER TABLE triples_raw ADD COLUMN IF NOT EXISTS disambiguation_note TEXT;"))
    conn.commit()
print("[1/2] 表结构就绪")

# 2. 创建管理员（仅在不存在时创建，绝不重置已有管理员密码）
with engine.connect() as conn:
    existing = conn.execute(text("SELECT username FROM users WHERE username = 'admin'")).fetchone()
    if not existing:
        pw_hash = pwd_ctx.hash(os.environ.get("KG_ADMIN_PASSWORD", "admin123"))
        conn.execute(text("INSERT INTO users (id, username, password_hash, role) VALUES (gen_random_uuid(), 'admin', :h, 'admin')"), {"h": pw_hash})
        print("[2/2] 管理员已创建 (admin / 环境变量 KG_ADMIN_PASSWORD)")
    else:
        print("[2/2] 管理员已存在，跳过创建（不重置密码）")
    conn.commit()

print("\n管理员账号: admin （若首次创建，密码为环境变量 KG_ADMIN_PASSWORD，默认 admin123）")
