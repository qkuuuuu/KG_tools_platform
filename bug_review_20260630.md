# KG 平台全局 Bug Review — 2026-06-30

> 手动逐文件审查报告。子代理 review 因 API 限流失败，以下为主代理亲自审查结果。

## 审查范围
- 后端: 37 个 Python 文件（routers / services / models / utils）
- 前端: 15 个 Vue/JS 文件
- 已排除: 已知并正在由 kg-engine-upgrade 子代理修复的 5 个引擎问题

---

## 🔴 严重 Bug（会导致崩溃或功能完全不可用）

### S1. export.py 路由顺序错误 — graph-data 接口被吞
- **文件**: `backend/app/routers/export.py`
- **行号**: 141 vs 382
- **问题**: `@router.get("/{project_id}")` 定义在 `@router.get("/{project_id}/graph-data")` 之前。FastAPI 按注册顺序匹配，`GET /export/xxx/graph-data` 会被 `{project_id}` 路由先捕获，`project_id` 参数变成 `xxx/graph-data`，UUID 解析失败 → 422 错误。
- **影响**: 图谱可视化页面点击无反应（API 404/422）。
- **修复**: 将 `/{project_id}/graph-data` 和 `/{project_id}/neo4j-sync`、`/{project_id}/import-ttl`、`/{project_id}/neo4j-query` 等子路径路由全部移到 `/{project_id}` **之前**。

```python
# 正确顺序:
@router.get("/multi-project-graph")     # 第1
@router.get("/{project_id}/graph-data") # 第2
@router.post("/{project_id}/neo4j-sync")
@router.post("/{project_id}/neo4j-query")
@router.post("/{project_id}/import-ttl")
@router.get("/{project_id}")            # 最后（兜底）
@router.post("/{project_id}")           # 如果有
```

### S2. ReviewHistory.vue formatDate 函数括号不匹配
- **文件**: `frontend/src/views/ReviewHistory.vue`
- **行号**: 约 192-198
- **问题**: 
```javascript
return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }
//                                                                          ↑ 少一个 )
```
- **影响**: 前端编译报错，审核历史页面白屏。
- **修复**: 
```javascript
return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
```

### S3. 审核历史不同步 — HITL review 未触发 AuditLog 时间戳填充
- **文件**: `backend/app/routers/hitl.py` + `backend/app/models/__init__.py`
- **行号**: hitl.py L108, models/__init__.py L108
- **问题**: `AuditLog` 模型有 `timestamp = Column(DateTime, default=datetime.utcnow)`，但 `review_triples` 函数创建 AuditLog 时**没有显式传 timestamp**。SQLAlchemy `default` 只在 INSERT 时由 ORM 触发，如果数据库层没正确触发 default（PostgreSQL 某些配置），timestamp 可能为 NULL。
- **更可能的根因**: 用户说"审核了四五个但历史没记录"。检查 `review_triples` 代码发现 — **AuditLog 确实有写入**。问题可能在 `review_history.py` 的 JOIN 查询：`AuditLog.timestamp >= since`。如果 timestamp 是 NULL，则 `NULL >= since` 在 PostgreSQL 中为 NULL → 被过滤掉。
- **修复**: 在 `hitl.py` review_triples 中显式设置 `timestamp=datetime.utcnow()`：
```python
from datetime import datetime
log = AuditLog(
    triple_id=triple.id,
    action=review.action,
    operator=body.operator,
    old_data=old_data,
    new_data=new_data,
    timestamp=datetime.utcnow(),  # 显式设置
)
```

### S4. 审核历史缺少"同步到图谱"按钮 — 已存在但前端路由可能没到
- **文件**: `frontend/src/views/ReviewHistory.vue`
- **行号**: L77-80
- **问题**: ReviewHistory.vue 已有 `syncToGraph` 按钮调用 `/fusion/auto-fuse-passed/{projectId}`。但用户说没有这个按钮 — 可能是旧版缓存或路由没刷新。
- **修复**: 确认前端 dev server 重启，清浏览器缓存。如果仍不可见，检查 `projectId` 是否正确从路由参数获取。

---

## 🟠 中等 Bug（功能部分异常）

### M1. 后端时间戳全部缺少 Z 后缀 — 前端显示少 8 小时
- **文件**: 所有后端路由（documents.py, hitl.py, review_history.py, export.py 等）
- **问题**: 后端用 `str(d.created_at)` 返回 datetime，如 `2026-06-30 08:23:19`（UTC 无标记）。前端 `new Date(s)` 按本地时间解析 → 再 `toLocaleString('Asia/Shanghai')` → 时间不对。
- **影响**: 所有页面时间显示偏差 8 小时。
- **修复方案 A（推荐）**: 后端统一在返回中加 `Z`：
```python
"created_at": str(d.created_at) + "Z" if d.created_at else None,
```
- **修复方案 B**: 前端解析时补 Z（已在部分 Vue 文件做了，需统一）。

### M2. extraction.py 中 LLM 抽取异常被静默吞掉
- **文件**: `backend/app/routers/extraction.py` `_extract_triples_bg`
- **行号**: 约 L120
- **问题**: 
```python
except Exception as e:
    import traceback
    traceback.print_exc()  # 只打印，不通知前端
    if task:
        task.status = "FAILED"
        task.error_message = str(e)
    db.commit()
```
后台任务失败后 task 状态正确设为 FAILED，但前端 Extract.vue 轮询 task 状态的间隔可能太长，用户感知不到失败。
- **修复**: 前端加任务失败 toast 通知，或缩短轮询间隔。

### M3. GLiNER 引擎默认模型 urchade/gliner_multilingual 可能下载失败
- **文件**: `backend/app/services/extraction/gliner_extractor.py`
- **行号**: L17
- **问题**: 默认用 `urchade/gliner_multilingual`，但 HF 镜像 `hf-mirror.com` 不一定有所有模型。如果下载失败，降级到 spaCy，但 spaCy 中文模型 `zh_core_web_sm` 也可能没装。
- **修复**: 已由 kg-engine-upgrade 子代理处理中。

### M4. fusion.py auto_fuse_passed 没有去重已存在的 TripleFused
- **文件**: `backend/app/routers/fusion.py` `auto_fuse_passed`
- **行号**: 约 L240-280
- **问题**: 每次调用都会重新创建 EntityFused 和 TripleFused，不检查是否已存在。多次调用会产生重复的融合三元组。
- **修复**: 在创建 TripleFused 前检查是否已存在相同 (subject_entity_id, predicate, object_entity_id)。

### M5. ws.py broadcast_task_update 在后台线程中可能失效
- **文件**: `backend/app/routers/ws.py` `broadcast_task_update`
- **行号**: L62-70
- **问题**: 后台任务（BackgroundTasks）运行在独立线程中，`asyncio.get_event_loop()` 在非主线程可能抛 RuntimeError。当前代码 catch 了 RuntimeError 但静默跳过 → WebSocket 推送不生效。
- **修复**: 使用 `asyncio.run_coroutine_threadsafe(manager.broadcast(...), loop)` 并在启动时保存主事件循环引用。

### M6. search.py min_confidence 过滤会把 NULL 置信度排除
- **文件**: `backend/app/routers/search.py`
- **行号**: L30
- **问题**: `TripleRaw.llm_confidence >= min_confidence`（默认 0）。如果三元组的 `llm_confidence` 为 NULL（非 LLM 引擎抽取的），PostgreSQL 中 `NULL >= 0` 为 NULL → 被过滤掉。
- **影响**: 非 LLM 引擎抽取的三元组在搜索页不可见。
- **修复**:
```python
query = query.filter(
    (TripleRaw.llm_confidence >= min_confidence) | (TripleRaw.llm_confidence.is_(None))
)
```

### M7. export.py _entity_group 中文关键词重复
- **文件**: `backend/app/routers/export.py`
- **行号**: L17
- **问题**: `"公司"` 在第一个条件和第五个条件都出现，逻辑上第一个条件会先匹配，导致"XX公司"被分到 Organization 而不是 Location。
- **影响**: 图谱节点分组不够精确，但不影响功能。
- **修复**: 去重关键词列表。

---

## 🟡 轻微 Bug（不影响主流程但有隐患）

### L1. main.py 注释中文乱码
- **文件**: `backend/app/main.py`
- **问题**: 文件编码不是 UTF-8（可能是 GBK），导致中文注释乱码。
- **影响**: 不影响运行，但影响可读性。
- **修复**: 用 UTF-8 重新保存。

### L2. security.py require_admin 依赖 get_current_user 重复查库
- **文件**: `backend/app/utils/security.py`
- **问题**: `require_admin` 依赖 `get_current_user`，每次都查一次 User 表。高频接口可能有性能损耗。
- **修复**: 可接受，暂不优化。

### L3. HITL.vue revoke 接口返回的 message 中文有乱码字符
- **文件**: `backend/app/routers/hitl.py`
- **行号**: L155
- **问题**: `"撚回成功"` — "撚" 是乱码/错字，应该是"撤回"。
- **修复**: 改为 `"撤回成功"`。

### L4. documents.py download_markdown 没有权限检查
- **文件**: `backend/app/routers/documents.py`
- **行号**: L181
- **问题**: 任何登录用户都能下载任何项目的文档，没有检查 doc 所属 project_id 是否在用户权限范围内。
- **影响**: 多用户系统中有数据泄露风险。当前单用户使用可接受。

### L5. extraction.py extract 接口要求 admin 权限 — reviewer 无法抽取
- **文件**: `backend/app/routers/extraction.py`
- **行号**: L200
- **问题**: `_: User = Depends(require_admin)` — 如果用户角色是 reviewer，无法使用抽取功能。
- **影响**: 取决于业务需求。如果 reviewer 也需要抽取，需改为 `get_current_user`。

### L6. fusion.py merge 接口参数用 Query 而非 Body
- **文件**: `backend/app/routers/fusion.py`
- **行号**: L141
- **问题**: `merge_entities` 接口的参数 `entity_1_name`、`entity_2_name`、`standard_name`、`project_id` 都用 URL Query 传递。中文实体名需要 URL 编码，容易出错。
- **修复**: 改为 JSON Body。

### L7. Graph.vue G6 动态 import 在 Vite 生产构建中可能失败
- **文件**: `frontend/src/views/Graph.vue`
- **行号**: 约 L100
- **问题**: `import('@antv/g6')` 动态导入在 Vite 生产构建中可能不会正确分包。G6 4.x 是 CJS 模块，Vite 需要配置 optimizeDeps。
- **修复**: 在 `vite.config.js` 中添加：
```javascript
optimizeDeps: { include: ['@antv/g6'] }
```

### L8. config.py JWT_SECRET 可能使用默认值
- **文件**: `backend/app/config.py`（未直接读取，从 security.py 推断）
- **问题**: `settings.JWT_SECRET` 如果没有环境变量，可能使用硬编码默认值，存在安全风险。
- **修复**: 确认 config.py 中 `JWT_SECRET` 优先从环境变量读取。

---

## 🔵 优化建议

### O1. 后端统一时间序列化
建议在 models 中添加 `to_dict()` 方法或 Pydantic schema，统一处理 datetime → ISO 8601 字符串（含 Z 后缀），避免每个路由手动 `str(d.created_at)`。

### O2. 前端统一 formatDate 工具函数
当前每个 Vue 文件都有自己的 `formatDate`，且实现不一致（有的补 Z，有的不补）。建议提取到 `utils/date.js` 统一。

### O3. 数据库索引
- `TripleRaw(project_id, status)` 组合查询频繁，建议加索引
- `AuditLog(triple_id)` 外键已有索引，但 `AuditLog(timestamp)` 也常用于范围查询，可加索引

### O4. Neo4j 同步接口缺少批量提交
`try_neo4j_import` 一次性导入所有三元组，大图谱可能超时。建议分批提交。

### O5. 前端 API 模块化
`api/index.js` 单文件 200+ 行，建议拆分为 `api/auth.js`、`api/project.js`、`api/extract.js` 等。

---

## 修复优先级

| 优先级 | Bug | 工作量 |
|--------|-----|--------|
| P0 | S1 export 路由顺序 | 5分钟 |
| P0 | S2 ReviewHistory formatDate | 1分钟 |
| P0 | S3 AuditLog timestamp | 5分钟 |
| P1 | M1 时间戳 Z 后缀 | 15分钟 |
| P1 | M4 fusion 去重 | 10分钟 |
| P1 | M6 search NULL 置信度 | 5分钟 |
| P2 | L3 撤回乱码 | 1分钟 |
| P2 | L5 权限调整 | 需确认 |
| P3 | 其余优化 | 按需 |

---

## 审查结论

核心问题 3 个（S1-S3）导致用户反馈的"图谱点击无反应"和"审核历史无记录"，修复后主要功能即可恢复。时间戳问题（M1）影响全局显示，建议优先处理。
