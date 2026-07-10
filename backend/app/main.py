"""FastAPI 主应用"""
import os
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, projects, llm_config, schemas, documents, extraction, hitl, fusion, export, users, device_config, review_history, search, ws, passed_triples, assistant

app = FastAPI(
    title="知识图谱构建平台 API",
    version="1.0.0",
    description="多方法知识图谱构建与融合平台 - 前后端分离后端服务",
)


@app.on_event("startup")
async def _on_startup():
    """保存主事件循环引用，供后台线程中的 WebSocket 广播使用"""
    ws.set_main_loop(asyncio.get_running_loop())

# CORS（生产环境通过环境变量 KG_CORS_ORIGINS 配置，逗号分隔）
_cors_origins = os.environ.get("KG_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False if "*" in _cors_origins else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(users.router, prefix="/api/v1/users", tags=["用户管理"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["项目"])
app.include_router(llm_config.router, prefix="/api/v1/projects", tags=["LLM配置"])
app.include_router(schemas.router, prefix="/api/v1/projects", tags=["Schema"])
app.include_router(documents.router, prefix="/api/v1/data", tags=["文档与解析"])
app.include_router(passed_triples.router, prefix="/api/v1/data/passed-triples", tags=["已通过三元组"])
app.include_router(extraction.router, prefix="/api/v1/data", tags=["抽取"])
app.include_router(hitl.router, prefix="/api/v1/hitl", tags=["人工审核"])
app.include_router(fusion.router, prefix="/api/v1/fusion", tags=["融合"])
app.include_router(export.router, prefix="/api/v1/export", tags=["导出"])
app.include_router(device_config.router, prefix="/api/v1/projects", tags=["设备配置"])
app.include_router(review_history.router, prefix="/api/v1/review", tags=["审核历史"])
app.include_router(search.router, prefix="/api/v1/search", tags=["搜索"])
app.include_router(assistant.router, prefix="/api/v1/assistant", tags=["智能助手"])
# app.include_router(passed_triples.router, prefix="/api/v1/data/passed-triples", tags=["已通过三元组"])  # moved above extraction to avoid route conflict
app.include_router(ws.router, tags=["WebSocket"])


@app.get("/")
async def root():
    return {"message": "知识图谱构建平台 API", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}
