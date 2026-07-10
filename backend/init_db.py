"""初始化数据库和管理员"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:kg_dev_password_2026@localhost:5432/kg_platform')
os.environ.setdefault('JWT_SECRET', 'kg-super-secret-key-2024-change-in-production')
os.environ.setdefault('ENCRYPT_KEY', '0123456789abcdef0123456789abcdef')
os.environ.setdefault('UPLOAD_DIR', 'C:/Users/11491/Desktop/KG/kg-platform/backend/uploads')
os.environ.setdefault('NEO4J_URL', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'kg123456')

from sqlalchemy import create_engine, text
from app.config import settings
from app.database import engine, Base
from app.models import User
from passlib.context import CryptContext

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 1. 建表
Base.metadata.create_all(engine)
print("[1/2] 表创建完成")

# 2. 创建管理员
with engine.connect() as conn:
    existing = conn.execute(text("SELECT username FROM users WHERE username = 'admin'")).fetchone()
    pw_hash = pwd_ctx.hash("admin123")
    if existing:
        conn.execute(text("UPDATE users SET password_hash = :h WHERE username = 'admin'"), {"h": pw_hash})
        print("[2/2] 管理员密码已重置")
    else:
        conn.execute(text("INSERT INTO users (id, username, password_hash, role) VALUES (gen_random_uuid(), 'admin', :h, 'admin')"), {"h": pw_hash})
        print("[2/2] 管理员创建完成")

    conn.commit()

print("\n登录凭据: admin / admin123")
