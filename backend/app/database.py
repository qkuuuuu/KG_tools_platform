"""数据库连接与会话管理"""
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _run_additive_migrations():
    """无破坏性加列迁移（幂等）。

    仅 ADD COLUMN IF NOT EXISTS，不删除/不重建表，
    因此已有数据不会丢失，无需 docker compose down -v 重置。
    非 PostgreSQL（例如测试用 SQLite）静默跳过。
    """
    migrations = [
        'ALTER TABLE schema_constraints ADD COLUMN IF NOT EXISTS subject_label VARCHAR(200);',
        'ALTER TABLE schema_constraints ADD COLUMN IF NOT EXISTS predicate_label VARCHAR(200);',
        'ALTER TABLE schema_constraints ADD COLUMN IF NOT EXISTS object_label VARCHAR(200);',
    ]
    try:
        if engine.dialect.name != "postgresql":
            return
        with engine.connect() as conn:
            for sql in migrations:
                conn.execute(text(sql))
            conn.commit()
    except Exception as e:  # 迁移失败不应阻断启动
        logging.getLogger(__name__).warning(f"加列迁移跳过: {e}")


_run_additive_migrations()


def get_db():
    """FastAPI 依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
