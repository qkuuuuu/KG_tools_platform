# KG 平台修改汇总报告 — 删除功能 + 已通过三元组页面 + 批量操作

> 日期: 2026-06-30
> 修改范围: 后端 (FastAPI) + 前端 (Vue3 + Element Plus)

---

## 一、新增的接口列表

### 删除接口 (app/routers/extraction.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| `DELETE` | `/api/v1/data/documents/{doc_id}` | 删除文档解析任务，级联删除关联 TaskStatus + TripleRaw |
| `DELETE` | `/api/v1/data/extract-tasks/{task_id}` | 删除抽取任务，仅删除 TaskStatus，保留三元组 |
| `DELETE` | `/api/v1/data/quality-tasks/{task_id}` | 删除质检任务，仅删除 TaskStatus |
| `DELETE` | `/api/v1/data/triples/{triple_id}` | 删除单条三元组 (TripleRaw) |

### 已通过三元组接口 (app/routers/passed_triples.py — 新建文件)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/data/passed-triples/{project_id}/stats` | 统计: 总数 / 按引擎 / 按关系 / 按时间 / 近7天 |
| `GET` | `/api/v1/data/passed-triples/{project_id}` | 分页列表，支持 keyword 搜索 + relation 过滤 |
| `POST` | `/api/v1/data/passed-triples/{project_id}/sync-neo4j` | 同步所有 PASSED 三元组到 Neo4j |

所有接口均需 `get_current_user` 登录依赖，不强制 admin。

---

## 二、新增的前端页面

### PassedTriples.vue (frontend/src/views/PassedTriples.vue)

- **统计卡片**: 总数 / 近7天新增 / 引擎数 / 关系类型数
- **关系类型分布**: CSS 条形图，按数量排序，显示 Top 20
- **引擎分布**: CSS conic-gradient 圆环图 + 图例
- **三元组列表**: 分页表格，支持关键词搜索 + 关系类型下拉筛选
- **删除按钮**: 每行红色「删除」按钮，确认后调用 `extractApi.deleteTriple`
- **同步到 Neo4j**: 顶部按钮，确认后调用同步接口
- **刷新按钮**: 重新加载统计数据和列表

---

## 三、修改的文件清单

### 后端

| 文件 | 修改内容 |
|------|----------|
| `backend/app/routers/extraction.py` | 新增 4 个 DELETE 接口 (文档/抽取任务/质检任务/三元组) |
| `backend/app/routers/passed_triples.py` | **新建** — 已通过三元组统计/列表/同步路由 |
| `backend/app/main.py` | 注册 passed_triples 路由 |

### 前端

| 文件 | 修改内容 |
|------|----------|
| `frontend/src/api/index.js` | docApi 增加 `delete`; extractApi 增加 `deleteTask`/`deleteQualityTask`/`deleteTriple`; 新增 `passedTriplesApi` |
| `frontend/src/views/Extract.vue` | 三个任务表加「删除」按钮 + 批量选择/批量删除; 上传组件改为多文件自动上传; 新增 `loadExtractTasks`/`loadQualityTasks` 使用真实 tasks API |
| `frontend/src/views/PassedTriples.vue` | **新建** — 已通过三元组管理页面 |
| `frontend/src/router/index.js` | 新增 `/project/:id/passed-triples` 路由 |
| `frontend/src/App.vue` | 侧边栏新增「✅ 已通过三元组」菜单项 |

---

## 四、功能验证

- ✅ 后端 `from app.main import app` 正常导入
- ✅ 前端 `vite build` 编译成功 (12.18s)，`PassedTriples.vue` 正确打包
- ✅ 所有删除接口使用 `get_current_user` 依赖
- ✅ 所有删除操作前端有 `ElMessageBox.confirm` 确认对话框
- ✅ 删除成功/失败有 `ElMessage` 提示
- ✅ 批量删除显示进度结果 (成功/失败计数)
- ✅ 新页面使用现有 `kg-card` / `kg-page-header` CSS 类，风格统一

---

## 五、需要用户手动操作

1. **重启后端服务** — 新增了 `passed_triples.py` 路由文件和 `main.py` 注册，需重启 FastAPI 后端生效
2. **重启前端开发服务器** — 如使用 `vite dev`，需重启以加载新路由和页面 (如已 build 部署则无需额外操作)
3. **Neo4j 同步** — 如需使用「同步到 Neo4j」功能，确保 Neo4j 在线且 `.env` 中 `NEO4J_URL`/`NEO4J_USER`/`NEO4J_PASSWORD` 配置正确

---

## 六、遗留问题

1. **ECharts 未集成** — 项目 package.json 中未包含 echarts，已使用 CSS (conic-gradient + 条形图) 替代实现，视觉效果一致但无交互。如需更丰富的图表交互，可后续 `npm install echarts` 升级。
2. **上传组件改造** — `auto-upload` 改为 `true` 后，每个文件会独立上传。如需批量合并上传或进度显示，可进一步优化。
3. **TaskStatus 关联** — 删除文档时同时删除该文档关联的所有 TaskStatus (doc_id 匹配)，已覆盖 PARSE/EXTRACT/QUALITY_CHECK 三类任务。
4. **批量删除进度** — 当前批量删除为串行调用，大量数据时可能较慢。如需提升性能，可后续改为后端批量删除接口。
