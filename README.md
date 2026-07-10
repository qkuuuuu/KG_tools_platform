# 🧠 智能知识图谱构建与融合平台
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.4+-success.svg)](https://vuejs.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://www.docker.com/)
> 一个支持多源异构数据接入、多方法智能抽取、大模型自动化质检与人工协同复核 (HITL) 的全链路工业级知识图谱构建数据工厂。
---
## 📖 目录
- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [API 文档](#api-文档)
- [数据库设计](#数据库设计)
- [开发进度](#开发进度)
- [贡献指南](#贡献指南)
---
## 🎯 项目简介
传统的知识图谱构建往往高度依赖人工标注或单一的算法模型，难以应对复杂的文档排版和多变的业务需求。本平台旨在打造一个 **“低门槛、高配置”的知识流水线**，通过集成前沿的解析工具、多种抽取算法，并辅以大模型质检与人工协同兜底，彻底打通从非结构化文本到高质量图谱资产的最后一公里。
**目标用户**：
- 知识工程人员 / 业务专家
- NLP 算法工程师
- 数据清洗管理员
---
## ✨ 核心特性
### 🔄 全链路闭环流程
flowchart LR
    A[多源数据接入] --> B[智能解析网关]
    B --> C[动态Schema定义]
    C --> D[多方法抽取引擎]
    D --> E[大模型质检审批]
    E --> F{置信度判断}
    F -- >= 阈值 --> G[知识融合]
    F -- < 阈值 --> H[HITL人工审核]
    H --> G
    G --> I[图谱资产输出]
🎛️ 功能模块清单
模块	核心功能	状态	
项目管理	多项目创建、切换、独立配置、数据隔离	✅ 已实现	
LLM 网关	多阶段模型路由、API 密钥管理、成本控制	✅ 已实现	
数据接入	PDF/Word/图片等格式解析	🔶 部分实现	
Schema 编辑器	动态定义 [主语-关系-宾语] 约束	✅ 已实现	
抽取引擎池	规则/深度学习/大模型 Prompt 等多种方法	🔶 框架已搭建	
LLM 审批	自动化质检、置信度评分、阈值分流	🔶 框架已搭建	
HITL 工作台	人工审核、修改、驳回、上下文对照	✅ UI 已实现	
知识融合	实体对齐、别名管理、血缘追溯	🔶 框架已搭建	
资产导出	CSV/JSON/Neo4j Cypher 等格式	🔶 部分实现	
🏗️ 技术架构
技术栈选型
前端技术栈
框架：Vue 3 (Composition API)
UI 组件库：Element Plus
状态管理：Pinia
HTTP 客户端：Axios
图谱可视化：G6
构建工具：Vite
后端技术栈
框架：FastAPI (Python 3.10+)
数据验证：Pydantic
ORM：SQLAlchemy
认证：JWT (PyJWT) + Passlib (bcrypt)
数据库迁移：Alembic
AI 与数据工具
LLM 对接：LangChain / OpenAI SDK / Anthropic SDK
PDF 解析：pdfplumber, PyMuPDF, MinerU
OCR：PaddleOCR
通用解析：Unstructured, Docling
基础设施
容器化：Docker, Docker Compose
反向代理：Nginx
数据库：PostgreSQL 16, Neo4j 5
系统架构图
flowchart LR
    subgraph Frontend [前端应用]
        A[Vue 3 App]
    end
    subgraph Backend [后端服务]
        B[FastAPI Application]
        C[LLM Gateway]
        D[Extraction Engine]
    end
    subgraph DataStore [数据存储]
        E[PostgreSQL]
        F[Neo4j]
    end
    subgraph AI [AI 服务]
        G[OpenAI/Anthropic]
        H[本地模型]
    end
    A -->|REST API| B
    B --> C
    C --> G
    C --> H
    B --> D
    B --> E
    B --> F
🚀 快速开始
前置要求
Python 3.10+
Node.js 18+
Docker Desktop (推荐)
Git
安装步骤
1. 克隆项目
git clone https://github.com/your-username/kg-platform.git
cd kg-platform
2. 环境配置
创建 .env 文件：
# Backend
DATABASE_URL=postgresql+psycopg2://kg_platform:kg_dev_password_2026@localhost:5432/kg_platform
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
# Frontend
VITE_API_BASE_URL=http://localhost:8000
# LLM Gateway (Optional)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=...
# Neo4j (Optional)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=kg_neo4j_2026
3. 启动基础设施
使用 Docker Compose 启动核心服务：
# 启动 PostgreSQL 和 Neo4j
docker-compose up -d postgres neo4j
# 查看服务状态
docker-compose ps
4. 启动后端服务
# 进入后端目录
cd backend
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
# 安装依赖
pip install -r requirements.txt
# 运行数据库迁移
alembic upgrade head
# 启动 FastAPI 服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
后端服务将运行在 http://localhost:8000，API 文档地址：http://localhost:8000/docs
5. 启动前端服务
# 进入前端目录
cd frontend
# 安装依赖
npm install
# 启动开发服务器
npm run dev
前端应用将运行在 http://localhost:5173
验证安装
访问以下地址验证服务状态：
服务	地址	预期状态	
后端健康检查	http://localhost:8000/health	{"status": "ok"}	
API 文档	http://localhost:8000/docs	Swagger UI	
前端应用	http://localhost:5173	登录页面	
Neo4j 控制台	http://localhost:7474	Neo4j Browser	
默认登录凭据：
用户名：admin
密码：admin123
角色：admin
📁 项目结构
kg-platform/
├── backend/                    # FastAPI 后端应用
│   ├── app/
│   │   ├── api/               # API 路由模块
│   │   │   └── v1/           # v1 版本接口
│   │   │       ├── endpoints/ # 各业务模块端点
│   │   │       │   ├── auth.py      # 认证接口
│   │   │       │   ├── projects.py  # 项目管理
│   │   │       │   ├── documents.py # 文档管理
│   │   │       │   ├── schemas.py   # Schema 管理
│   │   │       │   ├── hitl.py     # 人工审核
│   │   │       │   └── fusion.py   # 知识融合
│   │   │       └── api.py          # 路由聚合
│   │   ├── core/              # 核心配置
│   │   │   ├── config.py      # 应用配置
│   │   │   ├── security.py    # 安全相关
│   │   │   └── database.py    # 数据库连接
│   │   ├── models/            # SQLAlchemy 模型
│   │   ├── schemas/           # Pydantic 模式
│   │   ├── services/          # 业务逻辑层
│   │   └── main.py            # FastAPI 应用入口
│   ├── alembic/               # 数据库迁移文件
│   ├── requirements.txt       # Python 依赖
│   └── Dockerfile             # 后端容器配置
├── frontend/                  # Vue 3 前端应用
│   ├── src/
│   │   ├── views/             # 页面组件
│   │   │   ├── Dashboard.vue  # 仪表盘
│   │   │   ├── ProjectList.vue # 项目列表
│   │   │   ├── SchemaEditor.vue # Schema 编辑器
│   │   │   ├── HITLWorkbench.vue # 人工审核工作台
│   │   │   └── FusionDashboard.vue # 融合仪表盘
│   │   ├── components/        # 通用组件
│   │   ├── stores/            # Pinia 状态管理
│   │   ├── api/               # API 请求封装
│   │   └── router/            # Vue Router 路由
│   ├── package.json           # 前端依赖配置
│   ├── vite.config.js         # Vite 配置
│   └── Dockerfile             # 前端容器配置
├── docker-compose.yml         # Docker Compose 配置
├── .env.example               # 环境变量示例
└── README.md                  # 项目说明文档
📖 API 文档
核心 API 接口列表
<details>
<summary>🔐 认证接口</summary>
POST /api/v1/auth/login - JWT 登录
POST /api/v1/auth/register - 用户注册
GET /api/v1/auth/me - 获取当前用户信息
</details>
<details>
<summary>📁 项目管理接口</summary>
POST /api/v1/projects/ - 创建项目
GET /api/v1/projects/ - 项目列表
GET /api/v1/projects/{id} - 项目详情
PUT /api/v1/projects/{id} - 更新项目
DELETE /api/v1/projects/{id} - 删除项目
</details>
<details>
<summary>🎯 Schema 管理接口</summary>
POST /api/v1/projects/{id}/schemas - 创建 Schema 约束
GET /api/v1/projects/{id}/schemas - Schema 列表
PUT /api/v1/schemas/{id} - 更新 Schema
DELETE /api/v1/schemas/{id} - 删除 Schema
</details>
<details>
<summary>🛠️ HITL 审核接口</summary>
GET /api/v1/hitl/stats/{project_id} - HITL 统计
GET /api/v1/hitl/pending/{project_id} - 待审核队列
POST /api/v1/hitl/decide/{triple_id} - 审核决定（通过/拒绝/修改）
</details>
<details>
<summary>🔀 知识融合接口</summary>
GET /api/v1/fusion/suggestions/{project_id} - 融合建议
POST /api/v1/fusion/merge - 实体融合
GET /api/v1/fusion/entities/{project_id} - 融合实体列表
</details>
API 请求示例
# 登录获取 Token
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'
# 创建项目
curl -X POST "http://localhost:8000/api/v1/projects/" \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "医疗知识图谱项目"}'
🗄️ 数据库设计
系统基于 PostgreSQL 设计，共包含 8 张核心表：
表名	描述	
projects	项目表，存储项目基本信息	
llm_configs	大模型多阶段配置表，存储 API 凭据和路由策略	
schema_constraints	动态 Schema 规则表，定义实体关系约束	
documents	上传文档表，存储原文和解析后的 Markdown	
triples_raw	原始待审核三元组表，记录抽取结果和置信度	
audit_logs	数据血缘与人工审核日志表	
entities_fused	最终融合实体库，存储标准实体和别名	
triples_fused	最终图谱资产表，存储融合后的三元组	
🗺️ 开发进度
✅ 已完成功能 (2026-06-29)
[x] 项目基础架构搭建
[x] 用户认证与授权
[x] 项目管理模块
[x] 文档上传与管理
[x] Schema 动态编辑器
[x] 基础抽取框架
[x] HITL 审核工作台 UI
[x] 知识融合基础框架
🔶 部分实现功能
[ ] 多格式文档解析（支持 PDF/Word/图片等）
[ ] LLM 质检与审批流程
[ ] 实体融合与对齐算法
[ ] 数据血缘完整追踪
🔜 计划中功能
[ ] 接入 MinerU/pdfplumber 实际解析逻辑
[ ] 接入 LLM 抽取算法（UIE/LLM Prompt）
[ ] 完善 HITL 工作台 UI
[ ] 前端生产构建 + Nginx 部署
[ ] Docker Compose 一键启动后端
[ ] 图谱可视化与查询界面
🛠️ 常见问题与修复记录
<details>
<summary>🔧 环境配置问题排查</summary>
PostgreSQL 连接问题
确保 docker-compose.yml 中 postgres 服务已启动
检查 .env 中的 DATABASE_URL 格式是否正确
注意：使用 postgresql+psycopg2:// 协议头
bcrypt 版本冲突
如果遇到 passlib 兼容性问题，请降级 bcrypt：
pip install bcrypt==4.0.1
端口占用问题
前端默认端口 5173，如果被占用，请修改 vite.config.js：
server: {
  port: 5173  // 可改为其他端口
}
Neo4j 连接
首次启动 Neo4j 可能需要较长时间，请耐心等待
访问 http://localhost:7474 设置初始密码
</details>
🤝 贡献指南
我们欢迎所有形式的贡献，包括但不限于：
🐛 Bug 报告和修复
✨ 新功能建议和实现
📖 文档改进
🎨 UI/UX 优化
贡献流程
Fork 本仓库
创建特性分支 (git checkout -b feature/AmazingFeature)
提交更改 (git commit -m 'Add some AmazingFeature')
推送到分支 (git push origin feature/AmazingFeature)
提交 Pull Request
📄 许可证
本项目采用 MIT 许可证 - 查看 LICENSE 文件了解详情。
📞 联系方式
项目主页：[GitHub Repository]
问题反馈：[GitHub Issues]
最后更新时间：2026-06-29
