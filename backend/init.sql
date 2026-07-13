-- ============================================================
-- KG Platform 数据库初始化脚本
-- ============================================================
-- 说明：表结构现在统一由 SQLAlchemy 模型在后端启动时通过
--       Base.metadata.create_all() 自动创建（见 backend/init_db.py）。
--       本文件只做数据库级别的引导，不再重复建表，避免“双源建表”漂移。
--
-- 修改表结构后：编辑 backend/app/models/__init__.py，
-- 然后重置数据库使变更生效：
--   docker compose down -v && docker compose up -d --build
-- ============================================================

-- 启用 UUID 扩展（部分查询/函数依赖）
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
