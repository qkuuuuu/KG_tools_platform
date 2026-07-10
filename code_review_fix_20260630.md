# 代码审查 Bug 修复汇总报告

**日期**: 2026-06-30  
**项目**: KG 知识图谱构建平台  
**审查轮次**: 代码审查 #1  

---

## 修复概览

| Bug # | 严重级别 | 文件 | 状态 |
|-------|---------|------|------|
| Bug 1 | P0 严重 | `backend/app/main.py` | ✅ 已修复 |
| Bug 2 | P1 | `frontend/src/views/Extract.vue` | ✅ 已修复 |
| Bug 3 | P1 | `frontend/src/views/Extract.vue` | ✅ 已修复 |
| Bug 4 | P2 | `frontend/src/views/PassedTriples.vue` | ⏭️ 跳过（无需修复） |
| Bug 5 | P1 | `backend/app/routers/extraction.py` | ✅ 已修复 |
| Bug 6 | P2 | `frontend/src/views/Extract.vue` | ✅ 已修复 |

---

## Bug 1: passed_triples.py 路由路径冲突 (P0 严重)

**问题**: `main.py` 中 `passed_triples` 路由注册在 `extraction` 之后。由于 `extraction.py` 中有 `GET /data/triples/{project_id}` 路由（prefix 为 `/api/v1/data`），而 `passed_triples` 的 prefix 为 `/api/v1/data/passed-triples`，虽然路径前缀不同不会直接冲突，但 FastAPI 路由匹配是按注册顺序的，如果未来有路径交叉可能导致匹配错误。

**修复**: 在 `main.py` 中将 `passed_triples` 的 `include_router` 移到 `extraction` 之前注册，确保更具体的路由优先匹配。

**修改文件**: `backend/app/main.py`

```python
# 修改前：extraction 在 passed_triples 之前
app.include_router(extraction.router, prefix="/api/v1/data", ...)
app.include_router(passed_triples.router, prefix="/api/v1/data/passed-triples", ...)

# 修改后：passed_triples 在 extraction 之前
app.include_router(passed_triples.router, prefix="/api/v1/data/passed-triples", ...)
app.include_router(extraction.router, prefix="/api/v1/data", ...)
```

---

## Bug 2: Extract.vue 上传对话框 auto-upload 与手动上传矛盾 (P1)

**问题**: `el-upload` 组件设置了 `:auto-upload="true"`，文件选择后会立即自动上传，但底部仍有「上传并解析」按钮调用 `doUpload()`。auto-upload=true 时与选择解析引擎矛盾，且 `on-success` 回调与手动 `doUpload` 逻辑冲突。

**修复**: 将 `:auto-upload` 改回 `false`，删除 `:on-success` 回调，保留 `multiple` 和 `:limit="10"`。用户选好文件后点「上传并解析」按钮统一上传，与解析引擎选择不冲突。

**修改文件**: `frontend/src/views/Extract.vue`

```html
<!-- 修改前 -->
<el-upload :auto-upload="true" :on-success="onUploadSuccess" ...>

<!-- 修改后 -->
<el-upload :auto-upload="false" ...>
```

---

## Bug 3: Extract.vue doUpload 只处理单文件 (P1)

**问题**: `doUpload()` 函数只使用 `selectedFile.value`（单个文件），与多文件上传组件配置矛盾。`handleFileChange` 也只保存单个文件。

**修复**:
1. `handleFileChange` 改为接收 `fileList` 参数，保存完整文件列表
2. `doUpload` 改为遍历 `fileList.value` 批量上传，统计成功/失败数量

**修改文件**: `frontend/src/views/Extract.vue`

```javascript
// handleFileChange 修改前
function handleFileChange(file) {
  selectedFile.value = file.raw
  fileList.value = [file]
}

// handleFileChange 修改后
function handleFileChange(file, fileList) {
  fileList.value = fileList
}

// doUpload 修改后 - 批量上传
async function doUpload() {
  if (!fileList.value.length) {
    ElMessage.warning('请先选择文件')
    return
  }
  uploading.value = true
  let ok = 0, fail = 0
  for (const file of fileList.value) {
    try {
      const formData = new FormData()
      formData.append('file', file.raw)
      formData.append('project_id', projectId)
      formData.append('parse_engine', form.parseEngine)
      await docApi.upload(formData)
      ok++
    } catch (e) {
      fail++
    }
  }
  ElMessage.success(`上传完成: 成功 ${ok} 个${fail ? ', 失败 ' + fail + ' 个' : ''}`)
  showUploadDialog.value = false
  fileList.value = []
  await loadDocs()
  uploading.value = false
}
```

---

## Bug 4: PassedTriples.vue llm_confidence 为 0 时的处理 (P2)

**问题**: 模板中 `v-if="row.llm_confidence != null"` 判断，当值为 `0` 时 `0 != null` 为 true 会显示标签。`toFixed(0)` 在 null 时不会执行（被 v-if 拦截）。

**结论**: 经分析，当前代码逻辑正确——`null` 和 `undefined` 都不会通过 `v-if`，`0` 是有效置信度值应显示。**无需修复，跳过。**

---

## Bug 5: extraction.py 删除文档时未删除 AuditLog (P1)

**问题**: `delete_document` 接口删除了 `TaskStatus` 和 `TripleRaw`，但未删除通过 `triple_id` 关联的 `AuditLog` 记录。`TripleRaw` 被删除后，`AuditLog` 变成孤儿记录（虽然数据库外键有 `ondelete="CASCADE"`，但 SQLAlchemy 的 `delete()` 批量操作可能不触发数据库级联）。

**修复**: 在删除 `TripleRaw` 之前，先查询所有关联的 `triple_id`，然后删除对应的 `AuditLog` 记录。

**修改文件**: `backend/app/routers/extraction.py`

```python
# 修改前
db.query(TaskStatus).filter(TaskStatus.doc_id == doc_id).delete(synchronize_session=False)
db.query(TripleRaw).filter(TripleRaw.doc_id == doc_id).delete(synchronize_session=False)

# 修改后
db.query(TaskStatus).filter(TaskStatus.doc_id == doc_id).delete(synchronize_session=False)
# 删除关联的 AuditLog（通过 triple_id 关联 TripleRaw）
triple_ids = [t.id for t in db.query(TripleRaw).filter(TripleRaw.doc_id == doc_id).all()]
if triple_ids:
    db.query(AuditLog).filter(AuditLog.triple_id.in_(triple_ids)).delete(synchronize_session=False)
db.query(TripleRaw).filter(TripleRaw.doc_id == doc_id).delete(synchronize_session=False)
```

---

## Bug 6: Extract.vue loadCurrentModel/saveQuickModel 字段名错误 (P2)

**问题**: `loadCurrentModel()` 和 `saveQuickModel()` 中使用 `c.stage === 'EXTRACTION'` 匹配配置，但后端 `LLMConfig` 模型的字段名是 `pipeline_stage` 不是 `stage`。导致永远找不到 EXTRACTION 阶段的配置，模型切换功能失效。

**修复**: 将所有 `c.stage` 改为 `c.pipeline_stage`，新建配置时的 `stage:` 也改为 `pipeline_stage:`。

**修改文件**: `frontend/src/views/Extract.vue`

```javascript
// loadCurrentModel 修改前
const extractionCfg = configs.find(c => c.stage === 'EXTRACTION')
// 修改后
const extractionCfg = configs.find(c => c.pipeline_stage === 'EXTRACTION')

// saveQuickModel 修改前
const extractionCfg = configList.find(c => c.stage === 'EXTRACTION')
// 修改后
const extractionCfg = configList.find(c => c.pipeline_stage === 'EXTRACTION')

// 新建配置修改前
configList.push({ stage: 'EXTRACTION', ... })
// 修改后
configList.push({ pipeline_stage: 'EXTRACTION', ... })
```

---

## 影响分析

| 修改 | 影响范围 | 风险评估 |
|------|---------|---------|
| Bug 1: 路由注册顺序 | 后端路由匹配 | 低风险，仅调整注册顺序，不影响现有功能 |
| Bug 2: auto-upload 改回 false | 前端上传交互 | 低风险，恢复为手动上传模式，用户体验更可控 |
| Bug 3: 批量上传 | 前端上传逻辑 | 低风险，新增多文件循环上传，错误处理完善 |
| Bug 5: 删除 AuditLog | 后端删除接口 | 低风险，新增清理操作，避免孤儿记录 |
| Bug 6: 字段名修正 | 前端模型配置 | 低风险，修正字段名使功能恢复正常 |

---

## 测试建议

1. **Bug 1**: 验证 `GET /api/v1/data/passed-triples/{project_id}/stats` 和 `GET /api/v1/data/triples/{project_id}` 均能正确路由
2. **Bug 2 & 3**: 在上传对话框选择多个文件，点击「上传并解析」验证批量上传功能
3. **Bug 5**: 删除一个包含三元组（且有三元组审核日志）的文档，检查 audit_logs 表是否还有孤儿记录
4. **Bug 6**: 在 LLM 配置页面设置 EXTRACTION 阶段模型，回到抽取页面点击「当前模型」按钮验证是否正确加载配置
