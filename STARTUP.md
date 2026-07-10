# KG Platform 启动状态总结

**时间**: 2026-06-29 11:25 GMT+8
**状态**: ✅ 全链路启动成功

## 服务清单

| 服务 | 端口 | 状态 | 访问方式 |
|------|------|------|----------|
| PostgreSQL 16 | 5432 | ✅ Running (Docker) | `localhost:5432` kg_platform/postgres/kg_dev_password_2026 |
| Neo4j 5 | 7474, 7687 | ✅ Running (Docker) | http://localhost:7474 (neo4j/kg_neo4j_2026) |
| FastAPI 后端 | 8000 | ✅ Running (本地) | http://localhost:8000/docs (Swagger) |
| Vue 3 前端 | 5173 | ✅ Running (Vite dev) | http://localhost:5173 |

## 默认账号

- **用户名**: admin
- **密码**: admin123
- **角色**: admin

## 验证通过的接口

1. ✅ POST `/api/v1/auth/login` - JWT 登录
2. ✅ POST `/api/v1/projects/` - 创建项目
3. ✅ GET `/api/v1/projects/` - 项目列表
4. ✅ PUT `/api/v1/projects/{id}/schemas` - Schema 管理
5. ✅ GET `/api/v1/hitl/stats/{project_id}` - HITL 统计
6. ✅ GET `/api/v1/hitl/pending/{project_id}` - 待审核队列
7. ✅ GET `/api/v1/fusion/suggestions/{project_id}` - 融合建议
8. ✅ GET `/api/v1/data/documents` - 文档列表（新增）
9. ✅ GET `/health` - 健康检查

## 修复记录

1. **docker-compose.yml**: 使用默认 postgres 用户，去掉 init.sql 挂载
2. **config.py**: DATABASE_URL 改为 `postgresql+psycopg2://`，修复 Fernet key 生成
3. **bcrypt**: 降级到 4.0.1（5.0.0 与 passlib 1.7.4 不兼容）
4. **PyJWT**: 安装缺失依赖
5. **vite.config.js**: 端口改为 5173（3000 被占用）
6. **documents.py**: 新增 `GET /data/documents` list 接口
7. **Dashboard.vue**: 补充文档列表 API 调用

## 后续待办

- [ ] 接入 MinerU/pdfplumber 实际解析逻辑
- [ ] 接入 LLM 抽取算法（UIE/LLM Prompt）
- [ ] 完善 HITL 工作台 UI
- [ ] 前端生产构建 + Nginx 部署
- [ ] Docker Compose 一键启动后端（目前是本地 python）
