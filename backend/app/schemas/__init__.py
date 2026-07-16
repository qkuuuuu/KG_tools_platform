"""Pydantic 请求/响应 Schema"""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, Any, Literal


# ==================== 认证 ====================
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class CreateUserRequest(BaseModel):
    username: str
    password: str = Field(..., min_length=6, description="密码至少6位")
    role: Literal["admin", "reviewer", "viewer"] = "reviewer"


# ==================== 项目 ====================
class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== LLM 配置 ====================
class LLMConfigUpdate(BaseModel):
    pipeline_stage: str  # PARSE_AUDIT / EXTRACTION / VERIFICATION / FUSION / DISAMBIGUATION / EMBEDDING
    api_provider: str    # OPENAI / ANTHROPIC / DEEPSEEK / QWEN
    base_url: Optional[str] = None
    api_key: Optional[str] = None  # 允许不传 key（不更新已有 key）
    model_name: str
    prompt: Optional[str] = None  # 自定义 Prompt（需求1）：为空则回退默认
    enabled: bool = True  # 向量模型(EMBEDDING)开关：是否启用向量语义匹配


class LLMConfigResponse(BaseModel):
    id: UUID
    pipeline_stage: str
    api_provider: str
    base_url: Optional[str] = None
    model_name: str
    prompt: Optional[str] = None  # 自定义 Prompt（需求1）
    enabled: bool = True  # 向量模型(EMBEDDING)开关

    class Config:
        from_attributes = True


# ==================== Schema ====================
class SchemaItem(BaseModel):
    subject_type: str
    predicate: str
    object_type: str


class SchemaResponse(BaseModel):
    id: UUID
    subject_type: str
    predicate: str
    object_type: str
    subject_label: Optional[str] = None
    predicate_label: Optional[str] = None
    object_label: Optional[str] = None

    class Config:
        from_attributes = True


# ==================== Schema DSL ====================
class SchemaPropertyItem(BaseModel):
    name: str
    label: str
    type: str


class SchemaEntityItem(BaseModel):
    name: str
    label: str
    namespace: str
    properties: list[SchemaPropertyItem]


class SchemaRelationItem(BaseModel):
    subject_type: str
    predicate: str
    predicate_label: str
    object_type: str


class ImportDSLRequest(BaseModel):
    dsl: str


class ImportDSLResponse(BaseModel):
    entities: list[SchemaEntityItem]
    relations: list[SchemaRelationItem]


# ==================== 设备配置 ====================
VALID_MODULES = ["MINERU", "UIE", "DEEPKE", "EMBEDDING"]
VALID_DEVICES = ["CPU", "GPU"]


class DeviceConfigItem(BaseModel):
    module_name: Literal["MINERU", "UIE", "DEEPKE", "EMBEDDING"]
    device: Literal["CPU", "GPU"] = "CPU"
    gpu_id: int = 0


class DeviceConfigResponse(BaseModel):
    id: UUID
    module_name: str
    device: str
    gpu_id: int
    updated_at: datetime

    class Config:
        from_attributes = True


class DeviceConfigBatchUpdate(BaseModel):
    configs: list[DeviceConfigItem]


# ==================== 文档 ====================
class DocumentResponse(BaseModel):
    id: UUID
    project_id: UUID
    file_name: str
    md_content: Optional[str]
    parse_engine_used: Optional[str]
    llm_parse_score: Optional[float]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== 三元组 ====================
class TripleResponse(BaseModel):
    id: UUID
    doc_id: UUID
    subject: str
    predicate: str
    object: str
    extraction_method: str
    llm_confidence: Optional[float]
    status: str
    chunk_text: Optional[str]
    assigned_to: Optional[str]
    needs_disambiguation: Optional[bool] = None
    disambiguation_note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewAction(BaseModel):
    triple_id: UUID
    action: str  # PASS / REJECT / MODIFY
    modified_subject: Optional[str] = None
    modified_predicate: Optional[str] = None
    modified_object: Optional[str] = None


class ReviewRequest(BaseModel):
    operator: str
    reviews: list[ReviewAction]


# ==================== 融合 ====================
class FusionSuggestion(BaseModel):
    entity_1_id: UUID
    entity_1_name: str
    entity_2_id: UUID
    entity_2_name: str
    similarity: float
    suggestion: str  # AUTO_MERGE / MANUAL_CONFIRM


class FusionMergeRequest(BaseModel):
    entity_1_id: UUID
    entity_2_id: UUID
    standard_name: str
    merge_aliases: bool = True


# ==================== 任务 ====================
class TaskResponse(BaseModel):
    id: UUID
    task_type: str
    status: str
    progress: int
    result: Optional[Any]
    error_message: Optional[str]

    class Config:
        from_attributes = True


# ==================== 抽取请求 ====================
class ExtractRequest(BaseModel):
    doc_id: UUID
    extraction_method: str  # LLM_PROMPT / UIE / RULE / GLiNER
    schema_ids: list[UUID] = []


class QualityCheckRequest(BaseModel):
    doc_id: UUID
    threshold: Optional[float] = None


# ==================== 三元组消歧（需求4/5） ====================
class DisambiguateRequest(BaseModel):
    # 待消歧的三元组 ID 列表（来自审核台中 needs_disambiguation 标记的三元组）
    triple_ids: list[UUID]
    # 自定义消歧 Prompt（可选，覆盖默认 DISAMBIGUATION Prompt）
    custom_prompt: Optional[str] = None
