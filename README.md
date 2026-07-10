# 智能知识图谱构建与融合平台 (KG Platform)

[![Python](https://img.shields.io/badge/python-3.10+-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.4+-success.svg)](https://vuejs.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://www.docker.com/)

> **注意：本项目目前为内部私有项目，暂不开源，不提供许可证。**  
> 仅用于展示技术架构与功能说明。

---

## 核心特性

- 多源数据接入：支持 PDF/Word/图片等格式解析（部分实现）
- 动态 Schema 定义：灵活配置实体与关系约束
- 多方法抽取引擎：规则、深度学习、大模型 Prompt（框架已搭建）
- 大模型质检 + HITL 人工审核：自动化置信度评分与阈值分流，人工兜底复核
- 知识融合与资产管理：实体对齐、别名管理、血缘追溯（框架已搭建）
- 项目级数据隔离：多项目独立配置与运行

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Element Plus + Pinia + G6 |
| 后端 | FastAPI + SQLAlchemy + Alembic + JWT |
| AI 集成 | LangChain / OpenAI / Anthropic SDK |
| 数据库 | PostgreSQL 16 + Neo4j 5 |
| 容器 | Docker + Docker Compose |

---

## 快速开始（开发环境）

前置要求：Python 3.10+、Node.js 18+、Docker、Git。

1. 克隆项目  
   git clone https://github.com/your-username/kg-platform.git  
   cd kg-platform

2. 环境配置  
   复制 .env.example 为 .env，填写数据库连接、密钥及可选的 LLM API 密钥。

3. 启动基础设施（PostgreSQL 和 Neo4j）  
   docker-compose up -d postgres neo4j

4. 启动后端  
   cd backend  
   python -m venv venv  
   source venv/bin/activate （Windows 下用 venv\Scripts\activate）  
   pip install -r requirements.txt  
   alembic upgrade head  
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

5. 启动前端  
   cd frontend  
   npm install  
   npm run dev

6. 验证服务  
   - 后端 API 文档：http://localhost:8000/docs  
   - 前端应用：http://localhost:5173  
   - Neo4j 浏览器：http://localhost:7474  
   默认登录账号：admin / admin123

---

## API 概览（主要端点）

- 认证：POST /api/v1/auth/login  
- 项目：GET /api/v1/projects/ ， POST /api/v1/projects/  
- Schema：GET /api/v1/projects/{id}/schemas ， PUT /api/v1/schemas/{id}  
- HITL：GET /api/v1/hitl/pending/{project_id} ， POST /api/v1/hitl/decide/{triple_id}  
- 融合：GET /api/v1/fusion/suggestions/{project_id} ， POST /api/v1/fusion/merge  

详细请求/响应格式请参考 Swagger 文档。

---

## 项目结构（精简）

kg-platform/  
├── backend/  
│   ├── app/api/v1/endpoints/   # 各业务接口  
│   ├── app/core/               # 配置、安全、数据库  
│   ├── app/models/             # SQLAlchemy 模型  
│   ├── app/schemas/            # Pydantic 模式  
│   ├── app/services/           # 业务逻辑  
│   ├── alembic/                # 迁移脚本  
│   └── requirements.txt  
├── frontend/  
│   ├── src/views/              # 页面组件  
│   ├── src/components/         # 公共组件  
│   ├── src/stores/             # Pinia 状态  
│   ├── src/api/                # 接口封装  
│   └── package.json  
├── docker-compose.yml  
└── .env.example  

---

## 数据库核心表

- projects：项目信息  
- llm_configs：LLM 路由与密钥  
- schema_constraints：Schema 约束  
- documents：上传文档  
- triples_raw：待审核三元组  
- audit_logs：审核日志与血缘  
- entities_fused / triples_fused：融合后图谱资产  

---

## 开发进度

- 已完成：基础架构、认证、项目管理、Schema 编辑器、HITL UI、融合框架  
- 部分完成：文档解析、LLM 质检、融合算法、血缘追踪  
- 规划中：完整解析器、LLM 抽取、生产部署、图谱可视化  

---

## 常见问题

- PostgreSQL 连接失败：检查 Docker 服务状态及 DATABASE_URL 格式。  
- bcrypt 版本冲突：执行 pip install bcrypt==4.0.1。  
- 端口占用：修改 frontend/vite.config.js 中的 server.port。

---

## 贡献与联系

本项目为内部私有，暂不接受外部贡献。如有问题，请联系项目负责人。

最后更新：2026-07-10
