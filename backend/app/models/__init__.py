"""SQLAlchemy ORM 模型"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean, DateTime, ForeignKey, JSON, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


class Project(Base):
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    llm_configs = relationship("LLMConfig", back_populates="project", cascade="all, delete-orphan")
    schemas = relationship("SchemaConstraint", back_populates="project", cascade="all, delete-orphan")
    schema_entities = relationship("SchemaEntity", back_populates="project", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    device_configs = relationship("DeviceConfig", back_populates="project", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="reviewer")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class LLMConfig(Base):
    __tablename__ = "llm_configs"
    __table_args__ = (
        Index("ix_llm_configs_project_stage", "project_id", "pipeline_stage"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    pipeline_stage = Column(String(30), nullable=False)
    api_provider = Column(String(20), nullable=False)
    base_url = Column(String(500))
    api_key_encrypted = Column(Text, nullable=False)
    model_name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="llm_configs")


class SchemaConstraint(Base):
    __tablename__ = "schema_constraints"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    subject_type = Column(String(100), nullable=False)
    predicate = Column(String(100), nullable=False)
    object_type = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="schemas")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_project", "project_id"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    file_name = Column(String(500), nullable=False)
    file_path = Column(String(1000))
    md_content = Column(Text)
    parse_engine_used = Column(String(50))
    llm_parse_score = Column(Float)
    status = Column(String(20), default="PENDING")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="documents")
    triples = relationship("TripleRaw", back_populates="document", cascade="all, delete-orphan")


class TripleRaw(Base):
    __tablename__ = "triples_raw"
    __table_args__ = (
        Index("ix_triples_raw_project_status", "project_id", "status"),
        Index("ix_triples_raw_doc", "doc_id"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    task_id = Column(UUID(as_uuid=True), index=True)  # 关联抽取任务，删除任务时按此精确删除三元组
    subject = Column(String(500), nullable=False)
    predicate = Column(String(200), nullable=False)
    object = Column(String(500), nullable=False)
    extraction_method = Column(String(50), nullable=False)
    llm_confidence = Column(Float)
    status = Column(String(20), default="PENDING")
    chunk_text = Column(Text)
    assigned_to = Column(String(100))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="triples")
    audit_logs = relationship("AuditLog", back_populates="triple", cascade="all, delete-orphan")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    triple_id = Column(UUID(as_uuid=True), ForeignKey("triples_raw.id", ondelete="CASCADE"))
    action = Column(String(20), nullable=False)
    operator = Column(String(100), nullable=False)
    old_data = Column(JSONB)
    new_data = Column(JSONB)
    applied_schema_id = Column(UUID(as_uuid=True), ForeignKey("schema_constraints.id"))
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    triple = relationship("TripleRaw", back_populates="audit_logs")


class EntityFused(Base):
    __tablename__ = "entities_fused"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    standard_name = Column(String(500), nullable=False)
    aliases = Column(JSONB, default=[])
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TripleFused(Base):
    __tablename__ = "triples_fused"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    subject_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities_fused.id", ondelete="CASCADE"))
    predicate = Column(String(200), nullable=False)
    object_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities_fused.id", ondelete="CASCADE"))
    source_triple_ids = Column(JSONB, default=[])
    fused_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TaskStatus(Base):
    __tablename__ = "task_status"
    __table_args__ = (
        Index("ix_task_status_project_type_status", "project_id", "task_type", "status"),
        Index("ix_task_status_project_status", "project_id", "status"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    task_type = Column(String(30), nullable=False)
    status = Column(String(20), default="PENDING")
    progress = Column(Integer, default=0)
    result = Column(JSONB)
    error_message = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime)
    doc_id = Column(UUID(as_uuid=True), index=True)  # 关联文档，解决并发任务查询歧义
    timeout_at = Column(DateTime)  # 任务超时时间戳
    started_at = Column(DateTime)  # 实际开始执行时间


class SchemaEntity(Base):
    """Schema 实体类型表（DSL 导入后的新模型）"""
    __tablename__ = "schema_entities"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)  # 英文名如 EquipmentComponent
    label = Column(String(200))  # 中文标签如 设备部件
    namespace = Column(String(100))  # 命名空间
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="schema_entities")
    properties = relationship("SchemaProperty", back_populates="entity", cascade="all, delete-orphan")


class SchemaProperty(Base):
    """Schema 属性/关系表（DSL 导入后的新模型）"""
    __tablename__ = "schema_properties"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("schema_entities.id", ondelete="CASCADE"))
    name = Column(String(100), nullable=False)  # 英文名
    label = Column(String(200))  # 中文标签
    prop_type = Column(String(50), nullable=False)  # Text/Int/Float/Date/Bool/DateTime
    is_relation = Column(Boolean, default=False)  # True=关系, False=属性
    target_type = Column(String(100))  # 仅关系有值，指向目标实体类型名

    entity = relationship("SchemaEntity", back_populates="properties")


class DeviceConfig(Base):
    """设备配置表 - 各模块的 CPU/GPU 配置"""
    __tablename__ = "device_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "module_name", name="uq_device_config_project_module"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    module_name = Column(String(50), nullable=False)  # MINERU / UIE / EMBEDDING / DEEPKE
    device = Column(String(20), nullable=False, default="CPU")  # CPU / GPU
    gpu_id = Column(Integer, default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project", back_populates="device_configs")


class AssistantSession(Base):
    """智能助手会话"""
    __tablename__ = "assistant_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False, default="新会话")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    messages = relationship("AssistantMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="AssistantMessage.created_at")


class AssistantMessage(Base):
    """智能助手消息"""
    __tablename__ = "assistant_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("assistant_sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # user / assistant
    content = Column(Text, nullable=False)
    reasoning_path = Column(JSONB)  # 推理路径 {entities, nodes, edges}
    subgraph_stats = Column(JSONB)  # {node_count, edge_count}
    sources = Column(JSONB)  # [{project_id, project_name}]
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session = relationship("AssistantSession", back_populates="messages")
