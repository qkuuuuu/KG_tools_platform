# KG 平台代码审查报告 (2026-06-30)

## 一、Bug（必须修）

### 🔴 B1: extraction.py `_extract_triples_bg` 任务查询错位
**文件**: `backend/app/routers/extraction.py:58-62`
**问题**: 后台任务通过 `TaskStatus.task_type == "EXTRACT"` + `order_by(created_at.desc()).first()` 查询任务，但没有限定 `doc_id`。如果同一项目几乎同时发起两个抽取任务，后启动的任务会抢走先启动任务的 task 记录，导致先启动的任务永远卡在 PENDING。
**修复**: 创建 TaskStatus 时把 `doc_id` 也存进去（需在 TaskStatus 模型加字段），或查询时加 `doc_id` 过滤。

### 🔴 B2: 同上问题存在于 `_quality_check_bg`
**文件**: `extraction.py:145-149`
同样按 `task_type=="QUALITY_CHECK"` + `order_by` 取最新，无 `doc_id` 隔离。

### 🔴 B3: `_parse_document_bg` 同样按 `task_type=="PARSE"` 查最新
**文件**: `documents.py:30-35`
三个后台任务全部有同一类 bug。

### 🔴 B4: HITL 审核 markAction 逻辑缺陷
**文件**: `frontend/src/views/HITL.vue` `markAction` 函数
```js
if (action === 'MODIFY' && editingId.value === row.id) {
    // 只有在"完成编辑"时才 push MODIFY
} else {
    reviews.value.push({ triple_id: row.id, action })
}
```
问题：点击"修改"按钮进入编辑模式时，`toggleEdit` → `markAction(row, 'MODIFY')`，此时 `editingId === row.id` 为 true，会直接 push 一条 MODIFY（但用户还没编辑完）。应该改成：进入编辑时不 push，只有退出编辑时才 push。

### 🔴 B5: Export.vue `llmDisambiguate` 用了 `api.post` 但拿不到 data
**文件**: `frontend/src/views/Export.vue`
```js
const res = await api.post(`/fusion/llm-disambiguate/${projectId}`)
if (res.decisions?.length) // ← res 是整个响应，应该 res.data
```
axios 响应拦截器返回 `res.data`，但这里用的是 `api.post`（不是封装的 `fusionApi`），拦截器确实已经返回 data 了。但 `res.decisions` 这里 `res` 已经是 data 了... 需要确认。实际上拦截器 `res => res.data` 已经生效，所以 `res.decisions` 是对的。**降级为非 bug，但代码风格不一致**（其他地方用 `fusionApi`，这里直接用 `api`）。

### 🔴 B6: `rule_extractor.py` 函数名不一致
**文件**: `backend/app/services/extraction/rule_extractor.py`
`register_rule_rule` 应该是 `register_rule_template`，明显的命名错误（虽然目前没被调用，但是公共 API）。

### 🔴 B7: `documents.py` 上传接口 `background` 参数未使用
**文件**: `documents.py:62`
```python
background: bool = Form(True),
```
声明了但从未使用，无论传什么都是后台解析。应该要么用上（同步/异步切换），要么删掉。

### 🔴 B8: `neo4j_exporter.py` Cypher 脚本生成有 SQL 注入风险
**文件**: `backend/app/services/fusion/neo4j_exporter.py:65-78`
实体名直接拼接到 Cypher 语句中，只做了简单的 `replace("'", "\\'")`。如果实体名含特殊字符（反引号、$、{}），可能破坏 Cypher 语法或注入。
**修复**: 用参数化查询 `MERGE (a:Entity {name: $name})`，或至少做更严格的转义。

### 🔴 B9: `fusion.py` merge_entities 路由参数问题
**文件**: `backend/app/routers/fusion.py:133-140`
```python
async def merge_entities(
    entity_1_name: str,
    entity_2_name: str,
    standard_name: str,
    project_id: UUID,
    merge_aliases: bool = True,
    ...
```
这些参数作为 query parameters 传递，但 `project_id: UUID` 类型在 query param 中可能无法自动转换。实际前端调用 `api.post('/fusion/merge', null, { params: {...} })` 传的是字符串，FastAPI 能自动转 UUID，但如果传空会 422。

### 🔴 B10: `extraction.py` trigger_extraction 里的 existing_task 检查无意义
**文件**: `extraction.py:208-214`
```python
existing_task = db.query(TaskStatus).filter(
    ...status == "DONE"
).first()
```
查到了但没有用，既没阻止重复抽取也没做任何处理。死代码。

## 二、问题（应该修）

### 🟡 P1: CORS 全开
**文件**: `backend/app/main.py:14-20`
`allow_origins=["*"]` + `allow_credentials=True` 在生产环境是安全隐患。浏览器规范实际上禁止 `*` + `credentials=True` 同时使用，但 CORS 中间件可能不报错。

### 🟡 P2: JWT Secret 硬编码
**文件**: `backend/app/config.py:21`
`JWT_SECRET = "kg_jwt_secret_change_in_production_2026"` 硬编码在代码中。应该从环境变量读取，无环境变量时拒绝启动或生成随机值。

### 🟡 P3: 加密密钥硬编码
**文件**: `backend/app/config.py:24`
`ENCRYPTION_KEY = "kg_encryption_key_32bytes!changeme!"` 同上，API Key 加密用的密钥硬编码。

### 🟡 P4: 前端路由无登录守卫
**文件**: `frontend/src/router/index.js:24-29`
`router.beforeEach` 直接 `next()`，没有检查登录状态。虽然注释说"App.vue 会显示 Login"，但如果用户直接访问 URL 会闪现页面内容。

### 🟡 P5: LLM 配置更新接口 — 空 api_key 会覆盖已加密的 key
**文件**: `backend/app/routers/llm_config.py:35`
```python
existing.api_key_encrypted = encrypt_value(cfg.api_key)
```
如果前端编辑时没填 api_key（空字符串），会用空字符串覆盖已有的 key。应该 `if cfg.api_key:` 才更新。

### 🟡 P6: `extraction.py` 抽取结果 `get_project_triples` 无分页
**文件**: `extraction.py:240-255`
返回全部三元组，项目数据量大时会爆内存/超时。应该加分页。

### 🟡 P7: 后台任务无超时/取消机制
所有 `_xxx_bg` 后台任务（解析/抽取/质检）没有超时机制。如果 LLM API 卡住，任务永远停在 RUNNING。

### 🟡 P8: `fusion.py` auto_fuse_passed — 每条三元组 commit 一次
**文件**: `fusion.py:194-218`
在循环里每创建一个 EntityFused 就 `db.commit()` 一次，大量三元组时性能极差。应该批量 commit。

### 🟡 P9: 前端 Extract.vue 轮询间隔固定 2 秒
**文件**: `frontend/src/views/Extract.vue` `pollTask`
LLM 抽取可能需要 30 秒以上，2 秒轮询太频繁，应该用指数退避或 WebSocket。

### 🟡 P10: UIE extractor 顶层 import paddle
**文件**: `backend/app/services/extraction/uie_extractor.py:62-63`
```python
import paddle
from paddlenlp.transformers import UIE, AutoTokenizer
```
模块顶层 import，如果 paddle 未安装，`_check_engine_import` 会捕获异常标记为 unavailable，但 import 错误信息会被吞掉。应该放到函数内部 import。

### 🟡 P11: `gliner_extractor.py` 模块顶层 import gliner
同上问题。应该在函数内延迟导入。

### 🟡 P12: 数据库 datetime 用 `datetime.utcnow`
**文件**: `backend/app/models/__init__.py` 全文
`datetime.utcnow()` 在 Python 3.12+ 已废弃，应该用 `datetime.now(timezone.utc)`。

### 🟡 P13: 前端 store 里 `auth` 取值不一致
**文件**: `frontend/src/views/Extract.vue` downloadMarkdown
```js
const token = JSON.parse(localStorage.getItem('auth') || '{}').token || ''
```
但 store 里存的是 `kg_token`，不是 `auth`。这个 token 永远是空字符串。应该用 `useAuthStore().token`。

### 🟡 P14: `export.py` graph-data 节点 group 用首字母
**文件**: `backend/app/routers/export.py:278`
```python
"group": s_ent.standard_name[0].upper()
```
用实体名首字母做 group，导致颜色分配几乎每节点都不同色。应该用实体类型（但当前模型没有 type 字段）。

## 三、改进建议

### 💡 I1: TaskStatus 加 `doc_id` 字段
彻底解决 B1/B2/B3，后台任务查询精确到文档级。

### 💡 I2: 统一 LLM 调用代码
`llm_engine.py`、`llm_extractor.py`、`quality/__init__.py`、`llm_fusion.py` 各有一份 `_call_llm` 副本。应该抽成公共模块。

### 💡 I3: 引入 Celery / asyncio.Task 做后台任务
FastAPI BackgroundTasks 在请求生命周期外运行，无状态追踪、无重试、无并发控制。生产应换 Celery 或 `asyncio.create_task`。

### 💡 I4: 前端 API 拦截器加 error message 提取
现在 `ElMessage.error('失败')` 丢掉了后端的 detail 信息。应该统一提取 `err.response?.data?.detail`。

### 💡 I5: Schema 编辑器加去重
`Config.vue` addSchema 不检查重复，saveSchemas 也不去重，可能写入重复约束。

### 💡 I6: 数据库加索引
`triples_raw.project_id + status` 是高频查询组合，应该建联合索引。
`task_status.project_id + task_type + status` 同理。

### 💡 I7: 前端轮询改成 SSE 或 WebSocket
后端用 FastAPI 的 `StreamingResponse` 或 `sse-starlette` 推送任务进度，前端 EventSource 接收。省去轮询。

## 四、建议新增功能

### 🚀 F1: 项目级文档管理（多文档批量抽取）
当前一次只能传一个文档。支持多文档批量上传 + 批量抽取 + 批量质检，效率提升 10x。

### 🚀 F2: 抽取结果去重
同一文档多次抽取或跨文档抽取时，三元组会重复。应该有去重逻辑（subject|predicate|object 哈希）。

### 🚀 F3: Schema 模板库
预置行业 Schema 模板（医疗/金融/制造/法律），新建项目时一键导入，不用从零配。

### 🚀 F4: 审核结果导出与统计
HITL 审核日志已经记录了，但前端没有展示。加一个"审核历史"页面，展示谁审核了什么、修改了什么、通过率趋势。

### 🚀 F5: 三元组搜索与过滤
HITL 工作台没有搜索框。审核员想找特定实体的三元组只能翻页。加按 subject/object/predicate 搜索。

### 🚀 F6: 文档版本管理
同一文档重新上传解析后，旧的三元组应该保留历史记录，而不是直接覆盖。

### 🚀 F7: LLM 抽取结果缓存
同一文档 + 同一 Schema + 同一模型，二次抽取应该走缓存，省 API 调用费。

### 🚀 F8: 图谱差异对比
两次融合结果对比，可视化展示新增/删除/修改的三元组。适合迭代验证场景。

### 🚀 F9: 批量审核操作
HITL 表格支持"全选当前页 → 批量通过/拒绝"，当前只能逐条点。

### 🚀 F10: API 限流
当前无任何限流。LLM 抽取接口可以被恶意调用。加 `slowapi` 或 nginx 层限流。
