-- KG Platform 数据库初始化脚本
-- 由 Docker Compose 的 postgres-db 容器自动执行
-- 对应 SQLAlchemy 模型定义 (app/models.py)

-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'reviewer',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 项目表
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- LLM 配置表
CREATE TABLE IF NOT EXISTS llm_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    pipeline_stage VARCHAR(30) NOT NULL,
    api_provider VARCHAR(20) NOT NULL,
    base_url VARCHAR(500),
    api_key_encrypted TEXT NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Schema 约束表
CREATE TABLE IF NOT EXISTS schema_constraints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    subject_type VARCHAR(100) NOT NULL,
    predicate VARCHAR(100) NOT NULL,
    object_type VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Schema 实体表
CREATE TABLE IF NOT EXISTS schema_entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    label VARCHAR(200),
    namespace VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Schema 属性表
CREATE TABLE IF NOT EXISTS schema_properties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID REFERENCES schema_entities(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    label VARCHAR(200),
    prop_type VARCHAR(50) NOT NULL,
    is_relation BOOLEAN DEFAULT FALSE,
    target_type VARCHAR(100)
);

-- 文档表
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    file_name VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000),
    md_content TEXT,
    parse_engine_used VARCHAR(50),
    llm_parse_score FLOAT,
    status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 原始三元组表
CREATE TABLE IF NOT EXISTS triples_raw (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    subject VARCHAR(500) NOT NULL,
    predicate VARCHAR(200) NOT NULL,
    object VARCHAR(500) NOT NULL,
    task_id UUID,  -- 关联抽取任务，删除任务时按此精确删除三元组
    extraction_method VARCHAR(50) NOT NULL,
    llm_confidence FLOAT,
    status VARCHAR(20) DEFAULT 'PENDING',
    chunk_text TEXT,
    assigned_to VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 审核日志表
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    triple_id UUID REFERENCES triples_raw(id) ON DELETE CASCADE,
    action VARCHAR(20) NOT NULL,
    operator VARCHAR(100) NOT NULL,
    old_data JSONB,
    new_data JSONB,
    applied_schema_id UUID REFERENCES schema_constraints(id),
    timestamp TIMESTAMP DEFAULT NOW()
);

-- 融合实体表
CREATE TABLE IF NOT EXISTS entities_fused (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    standard_name VARCHAR(500) NOT NULL,
    aliases JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 融合三元组表
CREATE TABLE IF NOT EXISTS triples_fused (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    subject_entity_id UUID REFERENCES entities_fused(id) ON DELETE CASCADE,
    predicate VARCHAR(200) NOT NULL,
    object_entity_id UUID REFERENCES entities_fused(id) ON DELETE CASCADE,
    source_triple_ids JSONB DEFAULT '[]',
    fused_at TIMESTAMP DEFAULT NOW()
);

-- 任务状态表
CREATE TABLE IF NOT EXISTS task_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    task_type VARCHAR(30) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING',
    progress INTEGER DEFAULT 0,
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    doc_id UUID,  -- 关联文档
    timeout_at TIMESTAMP,  -- 任务超时时间戳
    started_at TIMESTAMP  -- 实际开始执行时间
);

-- 设备配置表
CREATE TABLE IF NOT EXISTS device_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    module_name VARCHAR(50) NOT NULL,
    device VARCHAR(20) NOT NULL DEFAULT 'CPU',
    gpu_id INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(project_id, module_name)
);

-- Schema 实体类型表 (DSL 导入)
CREATE TABLE IF NOT EXISTS schema_entities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    label VARCHAR(200),
    namespace VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Schema 属性/关系表 (DSL 导入)
CREATE TABLE IF NOT EXISTS schema_properties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id UUID REFERENCES schema_entities(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    label VARCHAR(200),
    prop_type VARCHAR(50) NOT NULL,
    is_relation BOOLEAN DEFAULT FALSE,
    target_type VARCHAR(100)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_triples_project ON triples_raw(project_id);
CREATE INDEX IF NOT EXISTS idx_triples_status ON triples_raw(status);
CREATE INDEX IF NOT EXISTS idx_triples_doc ON triples_raw(doc_id);
CREATE INDEX IF NOT EXISTS idx_triples_task ON triples_raw(task_id);
CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_llm_configs_stage ON llm_configs(project_id, pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON task_status(project_id);

-- 智能助手会话表
CREATE TABLE IF NOT EXISTS assistant_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    title VARCHAR(200) NOT NULL DEFAULT '新会话',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 智能助手消息表
CREATE TABLE IF NOT EXISTS assistant_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES assistant_sessions(id) ON DELETE CASCADE NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    reasoning_path JSONB,
    subgraph_stats JSONB,
    sources JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 默认 admin 用户 (密码: admin123)
-- 用 Python 的 bcrypt 生成: $2b$12$LJ3m4ys3GQWtHGPGxXoJZu1T.KQxfF8RRrZmGmFYMmxaMj7vUBmW6
INSERT INTO users (username, password_hash, role)
VALUES ('admin', '$2b$12$LJ3m4ys3GQWtHGPGxXoJZu1T.KQxfF8RRrZmGmFYMmxaMj7vUBmW6', 'admin')
ON CONFLICT (username) DO NOTHING;
