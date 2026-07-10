-- 知识图谱构建平台 - 数据库初始化
-- PostgreSQL 16

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==================== 0. device_configs ====================
CREATE TABLE IF NOT EXISTS device_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    module_name VARCHAR(50) NOT NULL,
    device VARCHAR(20) DEFAULT 'CPU',
    gpu_id INT DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, module_name)
);

-- ==================== 1. projects 项目表 ====================
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== 2. users 用户表 ====================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'reviewer',  -- admin / reviewer
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== 3. llm_configs 大模型配置表 ====================
CREATE TABLE IF NOT EXISTS llm_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    pipeline_stage VARCHAR(30) NOT NULL,  -- PARSE_AUDIT / EXTRACTION / VERIFICATION
    api_provider VARCHAR(20) NOT NULL,    -- OPENAI / ANTHROPIC
    base_url VARCHAR(500),
    api_key_encrypted TEXT NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, pipeline_stage)
);

-- ==================== 4. schema_constraints 动态Schema表 ====================
CREATE TABLE IF NOT EXISTS schema_constraints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    subject_type VARCHAR(100) NOT NULL,
    predicate VARCHAR(100) NOT NULL,
    object_type VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== 5. documents 文档表 ====================
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    file_name VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000),
    md_content TEXT,
    parse_engine_used VARCHAR(50),
    llm_parse_score FLOAT,
    status VARCHAR(20) DEFAULT 'PENDING',  -- PENDING / PROCESSING / DONE / FAILED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==================== 6. triples_raw 原始三元组表 ====================
CREATE TABLE IF NOT EXISTS triples_raw (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    subject VARCHAR(500) NOT NULL,
    predicate VARCHAR(200) NOT NULL,
    object VARCHAR(500) NOT NULL,
    extraction_method VARCHAR(50) NOT NULL,   -- UIE / LLM_PROMPT / CasRel / GLiNER / RULE
    llm_confidence FLOAT,
    status VARCHAR(20) DEFAULT 'PENDING',     -- PENDING / PASSED / REJECTED / FUSED
    chunk_text TEXT,                           -- 溯源上下文
    assigned_to VARCHAR(100),                  -- 分配的审核人
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_triples_raw_project_status ON triples_raw(project_id, status);
CREATE INDEX idx_triples_raw_assigned ON triples_raw(assigned_to, status);

-- ==================== 7. audit_logs 审核日志表 ====================
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    triple_id UUID REFERENCES triples_raw(id) ON DELETE CASCADE,
    action VARCHAR(20) NOT NULL,              -- PASS / REJECT / MODIFY / AUTO_FUSE
    operator VARCHAR(100) NOT NULL,
    old_data JSONB,
    new_data JSONB,
    applied_schema_id UUID REFERENCES schema_constraints(id),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_logs_triple ON audit_logs(triple_id);

-- ==================== 8. entities_fused 融合实体表 ====================
CREATE TABLE IF NOT EXISTS entities_fused (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    standard_name VARCHAR(500) NOT NULL,
    aliases JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_entities_fused_project ON entities_fused(project_id);

-- ==================== 9. triples_fused 最终图谱资产表 ====================
CREATE TABLE IF NOT EXISTS triples_fused (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    subject_entity_id UUID REFERENCES entities_fused(id) ON DELETE CASCADE,
    predicate VARCHAR(200) NOT NULL,
    object_entity_id UUID REFERENCES entities_fused(id) ON DELETE CASCADE,
    source_triple_ids JSONB DEFAULT '[]'::jsonb,  -- 溯源原始三元组ID列表
    fused_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_triples_fused_project ON triples_fused(project_id);

-- ==================== 10. task_status 异步任务状态表 ====================
CREATE TABLE IF NOT EXISTS task_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    task_type VARCHAR(30) NOT NULL,    -- PARSE / EXTRACT / QUALITY_CHECK / FUSION
    status VARCHAR(20) DEFAULT 'PENDING',  -- PENDING / RUNNING / DONE / FAILED
    progress INT DEFAULT 0,            -- 0-100
    result JSONB,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- ==================== 初始管理员账号 ====================
-- 密码: admin123 (bcrypt hash, Python生成后替换)
INSERT INTO users (username, password_hash, role)
VALUES ('admin', '$2b$12$placeholder_will_be_replaced_by_python_script', 'admin')
ON CONFLICT (username) DO NOTHING;
