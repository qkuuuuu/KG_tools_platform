# KG 平台三项增强完成 (2026-06-30)

## 问题1: Schema 编辑器表头命名 ✅
- **目标**: "主语/谓语/宾语" → "主体/关系/客体"
- **修改文件** (4个):
  - `Config.vue`: 表格列名 + placeholder 全改
  - `Dashboard.vue`: `subject`→主体, `object`→客体
  - `Extract.vue`: `subject`→主体, `predicate`→关系, `object`→客体
  - `HITL.vue`: `subject`→主体, `object`→客体

## 问题2: TTL (Turtle) 导入导出 ✅
- **新建**: `backend/app/services/ttl_io.py` (依赖 rdflib 7.6.0)
- **新增 API**:
  - `GET /export/{id}?format=ttl` — TTL 导出 (Protégé 兼容)
  - `POST /export/{id}/import-ttl` — TTL 导入解析
- **前端**: Export.vue 新增 TTL 导出按钮 + 导入文本框
- **验证**: 往返测试通过 (3条三元组导出→导入→解析为3条)

## 问题3: Neo4j 图谱可视化 ✅
- **新建**: `frontend/src/views/Graph.vue` — 基于 @antv/g6 5.x 力导向图
- **新增 API**: `GET /export/{id}/graph-data` — 返回 nodes+edges
- **功能**: 拖拽节点、缩放画布、标签开关、点击查看关联关系弹窗
- **路由**: `/project/:id/graph` → 侧边栏 "🗺️ 图谱可视化"
- **Export.vue**: 新增 "查看知识图谱" 跳转按钮

## 待完成
- UIE 动态解 码逻辑重写 (spaCy 降级已可工作)
