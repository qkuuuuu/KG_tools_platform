# 智能知识图谱构建与融合平台 (KG Platform)

[![Python](https://img.shields.io/badge/python-3.11+-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.4+-success.svg)](https://vuejs.org/)
[![Docker](https://img.shields.io/badge/Docker--Compose-blue.svg)](https://www.docker.com/)

> **说明：本项目为内部私有项目，暂不开源，不提供许可证。** 仅用于展示技术架构与功能说明。

---

## 项目简介

KG Platform 是一个**多方法知识图谱构建与融合平台**，覆盖从文档解析、多方法三元组抽取、大模型质检、人工审核（HITL）、知识融合与资产导出，到 **KAG 知识增强问答（Knowledge Augmented Generation）** 的完整链路。平台支持 LLM Prompt / 规则 / 深度学习（GLiNER、UIE、DeepKE）等多种抽取引擎，并通过动态 Schema 与项目级数据隔离支撑多业务场景。

---

## 核心特性

- **多源数据接入**：PDF / Word / 图片 / Excel 等格式解析（pdfplumber、PyMuPDF、PaddleOCR、MinerU、python-docx）。
- **动态 Schema 定义**：灵活配置实体类型、关系与约束。
- **多方法抽取引擎**：
  - LLM Prompt（OpenAI / Anthropic / 兼容 OpenAI 协议的自建大模型）
  - 规则抽取
  - 深度学习模型：GLiNER、UIE、DeepKE（随 Docker 镜像构建期一并安装，见 `backend/requirements.txt`；如仅需部分引擎可注释对应依赖行以精简镜像）
- **大模型质检 + HITL 人工审核**：自动置信度评分与阈值分流，低置信度样本进入人工复核。
- **知识融合与资产管理**：实体对齐、别名归一、血缘追溯，融合结果可导出多种格式。
- **KAG 知识增强问答**：内置 KAG 式智能助手，将知识图谱作为结构化知识源，结合多跳子图检索与 LLM 推理，回答可解释、可追溯（详见下章）。
- **项目级数据隔离**：多项目独立配置与运行。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Element Plus + Pinia + AntV G6 |
| 后端 | FastAPI + SQLAlchemy + JWT + bcrypt |
| AI 集成 | LangChain / OpenAI / Anthropic SDK / KAG 知识增强生成 |
| 数据库 | PostgreSQL 16 + Neo4j 5（可选） |
| 容器 | Docker + Docker Compose |

---

## 系统架构

```
┌─────────────┐      /api , /ws       ┌──────────────────┐
│  浏览器     │ ───────────────────▶  │  Frontend (Nginx) │
│ (Vue3+G6)   │ ◀─────────────────── │  80: 静态 + 反代  │
└─────────────┘                       └────────┬─────────┘
                                              │ proxy_pass
                                              ▼
                                    ┌──────────────────┐
                                    │  Backend API     │
                                    │  (FastAPI 8000)  │
                                    └──┬───────────┬──┘
                                       │           │
                          ┌────────────▼┐         ▼
                          │ PostgreSQL │    ┌─────────┐
                          │   (图谱/   │    │  Neo4j  │ (可选 --profile full)
                          │   业务数据)│    │ 图数据库│
                          └────────────┘    └─────────┘
```

> 前端容器内 Nginx 已把 `/api/` 和 `/ws/` 反代到后端 `backend-api:8000`，**部署到服务器时无需修改任何前端 API 地址**。

---

## KAG 智能助手（知识增强生成 / Knowledge Augmented Generation）

平台内置一个 **KAG 式智能助手**，将已构建的知识图谱作为结构化知识源，让大模型基于图谱进行**可解释的推理问答**（参考 OpenSPG/KAG 的核心思想）。它把「图谱检索」与「LLM 推理」结合，回答可追溯、可解释。

### 工作链路（KAG 四步推理）

1. **问题解析**：从用户问题中识别实体、关系意图。
2. **知识检索**：在三元组库（优先融合后的图谱 `TripleFused`，补充已通过审核 `PASSED` 的原始三元组）中检索相关子图，BFS 多跳（默认 2 跳）扩展。
3. **推理合成**：将子图作为上下文注入 LLM 提示词，由大模型推理出答案。
4. **推理路径**：返回用到的实体、节点与关系边，支持答案溯源与可视化。

### 核心能力

- **多跳图谱问答**：支持跨多实体的链式推理，自动抽取相关子图（最多 50 条关系 / 100 节点）。
- **可解释推理路径**：每次回答附带 `reasoning_path`（实体、节点、边）与子图统计，前端可可视化推理链路。
- **多项目融合查询**：请求可传入 `project_ids` 多个项目，跨项目联合推理。
- **持续会话**：会话持久化（增删改查 + 消息历史），支持多轮对话上下文（最近 12 条消息）。
- **推荐问题**：根据图谱实际实体 / 关系自动生成引导性问题，降低提问门槛。
- **优雅降级**：未配置 LLM 时，仍返回纯图谱检索结果（实体 + 关系）并提示去「模型配置」设置；LLM 配置优先取 `ASSISTANT` 阶段，回退 `EXTRACTION / FUSION / QUALITY`。
- **项目级隔离**：会话与消息按项目、按用户隔离。

### 关键接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/assistant/{project_id}/chat` | POST | 基于图谱的推理问答（支持 `session_id` / `project_ids`） |
| `/api/assistant/{project_id}/sessions` | GET / POST | 列出 / 新建会话 |
| `/api/assistant/{project_id}/sessions/{session_id}` | PUT / DELETE | 重命名 / 删除会话 |
| `/api/assistant/{project_id}/sessions/{session_id}/messages` | GET | 获取会话消息历史 |
| `/api/assistant/{project_id}/suggested-questions` | GET | 获取图谱引导式推荐问题 |

> **使用前提**：项目需已完成抽取、融合，且至少配置一个可用的 LLM（见「模型配置」）。子图检索基于已通过审核（`PASSED` / `FUSED`）的三元组。
>
> **相关代码**：引擎 `backend/app/services/assistant_engine.py`，路由 `backend/app/routers/assistant.py`。

---

## 快速开始（Docker 一键部署）

> 前置要求：服务器已安装 **Docker 20.10+** 与 **Docker Compose v2**。

```bash
# 1. 克隆代码
git clone https://github.com/qkuuuuu/KG_tools_platform.git
cd kg-platform

# 2. 准备环境变量（复制模板后按需修改）
cp .env.example .env
vi .env                      # ⚠️ 务必修改默认密码与密钥，见下方「部署前必须修改」

# 3. 构建并启动（首次构建约 3~10 分钟，需下载基础镜像）
docker compose up -d --build

# 4. 查看状态
docker compose ps
docker compose logs -f backend-api
```

启动后访问：

- 前端页面：<http://服务器IP/>
- 后端 API 文档（Swagger）：<http://服务器IP:8000/docs>
- 默认管理员账号：**admin / admin123**（请尽快修改）

### 可选：启动 Neo4j 图数据库

Neo4j 默认不启动，需要图可视化 / 图查询时：

```bash
docker compose --profile full up -d --build
```

---

## 目录结构

```
kg-platform/
├── backend/                  # FastAPI 后端
│   ├── Dockerfile
│   ├── entrypoint.sh         # 启动脚本：等待DB → 建表 → 启动
│   ├── init_db.py            # 由 SQLAlchemy 模型自动建表(create_all) + 默认管理员
│   ├── requirements.txt
│   └── app/
│       ├── api/v1/endpoints/ # 业务接口
│       ├── core/             # 配置、安全、数据库
│       ├── models/           # SQLAlchemy 模型
│       ├── schemas/          # Pydantic 模式
│       ├── services/         # 业务逻辑（解析/抽取/融合/助手-KAG）
│       └── utils/            # 安全、加解密工具
├── frontend/                 # Vue3 前端
│   ├── Dockerfile
│   ├── nginx.conf            # 生产 Nginx + API 反代
│   └── src/
│       ├── views/            # 页面
│       ├── components/       # 组件
│       ├── stores/           # Pinia 状态
│       └── api/              # 接口封装
├── docker-compose.yml        # 生产编排
├── .env.example              # 环境变量模板
└── DEPLOY.md                 # 详细服务器部署与运维指南
```

> **表结构唯一来源**：所有表由 `backend/app/models/__init__.py` 定义，后端启动时通过 `create_all` 自动建表（`backend/init.sql` 仅做 UUID 扩展引导）。
> 改动模型后需重置数据库使变更生效：`docker compose down -v && docker compose up -d --build`。

---

## 环境变量说明

所有敏感配置通过 `.env` 注入（`.env` 已被 `.gitignore` 忽略，**不会提交到 Git**）。

| 变量 | 说明 | 示例 |
|------|------|------|
| `POSTGRES_USER` | 数据库用户名 | `postgres` |
| `POSTGRES_PASSWORD` | 数据库密码 | 强密码 |
| `POSTGRES_DB` | 数据库名 | `kg_platform` |
| `NEO4J_PASSWORD` | Neo4j 密码 | 强密码 |
| `JWT_SECRET` | 登录 Token 签发密钥 | 强随机串（见下） |
| `ENCRYPTION_KEY` | LLM API Key 落库加密密钥 | 强随机串（见下） |
| `CORS_ORIGINS` | 允许跨域的源 | `*` 或 `https://你的域名` |

生成强随机密钥：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

> ⚠️ `JWT_SECRET` 与 `ENCRYPTION_KEY` 一旦设定并在系统中存储了 LLM API Key，**之后不要随意更改**——`ENCRYPTION_KEY` 改变会导致已加密的 API Key 无法解密。

---

## 部署前必须修改的内容（重点）

把代码推上服务器后，正式上线前请逐项确认：

### A. 必须改（安全）

1. **`.env` 中的密码**：`POSTGRES_PASSWORD`、`NEO4J_PASSWORD` 不要使用默认的 `admin123`，改为强密码。
2. **`.env` 中的 `JWT_SECRET`**：默认 `admin123`，必须换成强随机串，否则登录 Token 可被伪造。
3. **`.env` 中的 `ENCRYPTION_KEY`**：默认 `admin123`，必须换成强随机串，用于加密 LLM API Key。
4. **`.env` 中的 `CORS_ORIGINS`**：生产环境改为你的域名（如 `https://kg.example.com`），不要保留 `*`。
5. **部署后修改管理员密码**：用 `admin/admin123` 登录后，立即在系统中修改管理员密码。

### B. 建议改（网络暴露 / HTTPS）

6. **数据库端口不要暴露公网**：`docker-compose.yml` 中 `postgres-db` 默认映射 `5432:5432`，建议改为仅本机或删除 host 映射（容器之间仍可互访）：
   ```yaml
   ports:
     - "127.0.0.1:5432:5432"     # 仅本机可访问；或整段删除，仅容器内部访问
   ```
7. **后端端口按需暴露**：若不需要公网访问 Swagger，把 `backend-api` 的 `8000:8000` 改为 `127.0.0.1:8000:8000`，再经 SSH 隧道访问 `/docs`。
8. **域名 + HTTPS**：在 `frontend/nginx.conf` 中将 `server_name localhost` 改为你的域名，并在前端容器前加 Caddy / Nginx / Traefik 反向代理配置 SSL 证书。

### C. 不需要改

- 前端 API 地址：容器内已完成反代，无需改动。
- `download/` 模型文件：PaddleOCR / UIE / GLiNER / DeepKE(RaNER) / spaCy / MinerU 的大模型已在**镜像构建期**由 `backend/predownload_models.py` 下载并打包进镜像（缓存统一位于 `/opt/models`，由 Dockerfile 的 `HOME`/`HF_HOME`/`MODELSCOPE_CACHE`/`PADDLENLP_HOME` 指定），运行时直接命中，**无需用户首次使用时联网下载**。构建期已配置 `HF_ENDPOINT=https://hf-mirror.com`、`MINERU_MODEL_SOURCE=modelscope` 走国内镜像。若某模型构建期下载失败，对应引擎会在首次使用时自动回退下载（或降级方案）。

---

## 日常运维

```bash
# 查看日志
docker compose logs -f backend-api
docker compose logs -f frontend-app

# 重启 / 停止
docker compose restart backend-api
docker compose down

# 更新代码后重新部署
git pull
docker compose up -d --build

# 备份数据库
docker compose exec postgres-db pg_dump -U postgres kg_platform > backup_$(date +%Y%m%d).sql
```

更完整的服务器部署、备份恢复、模型引擎安装说明见 **[DEPLOY.md](./DEPLOY.md)**。

---

## 常见问题

- **PostgreSQL 连接失败**：检查 Docker 服务状态与 `.env` 中 `DATABASE_URL` 是否正确（compose 中已自动拼装）。
- **模型下载慢 / 失败**：已配置国内镜像；若仍失败，检查服务器能否访问 `hf-mirror.com` 与 `modelscope.cn`。
- **端口被占用**：修改 `docker-compose.yml` 中的端口映射，例如 `80:80` 改为 `8080:80`。
- **内存不足**：默认不启动 Neo4j；可在 `docker-compose.yml` 的 `backend-api` 下加 `deploy.resources.limits.memory: 2G` 限制。

---

## 许可证

本项目为内部私有项目，暂不开放源代码与许可证授权。

最后更新：2026-07-13（新增 KAG 智能助手章节）
