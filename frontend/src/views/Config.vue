<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push(`/project/${$route.params.id}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>模型与配置管理</h2>
    </div>

    <!-- LLM 配置 -->
    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">大模型路由配置</h3>
      <el-table :data="llmConfigs" stripe style="width: 100%">
        <el-table-column label="阶段" width="150">
          <template #default="{ row }">
            {{ stageLabel(row.pipeline_stage) }}
          </template>
        </el-table-column>
        <el-table-column prop="api_provider" label="服务商" width="120" />
        <el-table-column prop="base_url" label="Base URL" min-width="200" />
        <el-table-column prop="model_name" label="模型" width="200" />
        <el-table-column label="操作" width="150">
          <template #default="{ row, $index }">
            <el-button size="small" @click="editConfig($index)">编辑</el-button>
            <el-button size="small" type="danger" @click="deleteConfig($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-button style="margin-top: 12px;" @click="addConfig">+ 新增阶段配置</el-button>
    </div>

    <!-- 设备配置 -->
    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">设备配置 (CPU/GPU)</h3>
      <el-table :data="deviceConfigs" stripe style="width: 100%">
        <el-table-column label="模块" width="200">
          <template #default="{ row }">
            {{ moduleLabel(row.module_name) }}
          </template>
        </el-table-column>
        <el-table-column label="设备" width="200">
          <template #default="{ row }">
            <el-radio-group v-model="row.device">
              <el-radio-button value="CPU">CPU</el-radio-button>
              <el-radio-button value="GPU">GPU</el-radio-button>
            </el-radio-group>
          </template>
        </el-table-column>
        <el-table-column label="GPU ID" width="120">
          <template #default="{ row }">
            <el-input-number v-model="row.gpu_id" :min="0" :max="7" :disabled="row.device !== 'GPU'" size="small" style="width: 100px;" />
          </template>
        </el-table-column>
      </el-table>
      <el-button type="primary" style="margin-top: 12px;" @click="saveDevices">保存设备配置</el-button>
    </div>

    <!-- Schema 编辑器（表单模式） -->
    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">动态 Schema 约束</h3>
      <el-tabs v-model="schemaTab">
        <el-tab-pane label="表格编辑" name="table">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <span style="color: #909399; font-size: 13px;">共 {{ schemas.length }} 条约束</span>
            <el-button size="small" type="danger" plain @click="deleteAllSchemas" :disabled="!schemas.length">一键全部删除</el-button>
          </div>
          <el-table :data="schemas" stripe style="width: 100%; margin-bottom: 16px;">
            <el-table-column label="头实体类型">
              <template #default="{ row }">{{ row.subject_label || row.subject_type }}</template>
            </el-table-column>
            <el-table-column label="关系">
              <template #default="{ row }">{{ row.predicate_label || row.predicate }}</template>
            </el-table-column>
            <el-table-column label="尾实体类型">
              <template #default="{ row }">{{ row.object_label || row.object_type }}</template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ $index }">
                <el-button size="small" type="danger" @click="schemas.splice($index, 1)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="display: flex; gap: 12px; margin-bottom: 16px;">
            <el-input v-model="newSchema.subject_type" placeholder="头实体类型" />
            <el-input v-model="newSchema.predicate" placeholder="关系" />
            <el-input v-model="newSchema.object_type" placeholder="尾实体类型" />
            <el-button @click="addSchema">+ 添加</el-button>
          </div>
          <el-button type="primary" @click="saveSchemas">保存 Schema</el-button>
        </el-tab-pane>
        
        <el-tab-pane label="DSL 导入" name="dsl">
          <div style="display: flex; gap: 16px;">
            <div style="flex: 1;">
              <h4 style="margin: 0 0 8px;">DSL 代码</h4>
              <el-input
                v-model="dslInput"
                type="textarea"
                :rows="20"
                placeholder="粘贴 DSL 代码..."
                style="font-family: monospace; font-size: 13px;"
              />
              <div style="margin-top: 8px; display: flex; gap: 8px;">
                <el-button @click="previewDsl">解析预览</el-button>
                <el-button type="primary" @click="importDsl">确认导入</el-button>
              </div>
            </div>
            <div style="flex: 1;">
              <h4 style="margin: 0 0 8px;">解析预览</h4>
              <div v-if="dslPreview" style="background: #f5f7fa; padding: 16px; border-radius: 6px; max-height: 420px; overflow-y: auto;">
                <div v-if="dslPreview.entities?.length">
                  <h5 style="color: #409eff;">实体类型 ({{ dslPreview.entities.length }})</h5>
                  <div v-for="e in dslPreview.entities" :key="e.name" style="margin: 8px 0; padding: 8px; background: white; border-radius: 4px;">
                    <strong>{{ e.name }}</strong> ({{ e.label }})
                    <span v-if="e.namespace" style="color: #909399; font-size: 12px;"> [{{ e.namespace }}]</span>
                    <div v-if="e.properties?.length" style="margin-top: 4px; font-size: 12px; color: #606266;">
                      属性: <span v-for="p in e.properties" :key="p.name">{{ p.name }}({{ p.label }}):{{ p.type }} </span>
                    </div>
                    <div v-if="e.relations?.length" style="margin-top: 2px; font-size: 12px; color: #e6a23c;">
                      关系: <span v-for="r in e.relations" :key="r.name">{{ r.name }}({{ r.label }})→{{ r.target }} </span>
                    </div>
                  </div>
                </div>
                <div v-if="dslPreview.relations?.length" style="margin-top: 12px;">
                  <h5 style="color: #e6a23c;">关系约束 ({{ dslPreview.relations.length }})</h5>
                  <div v-for="(r, i) in dslPreview.relations" :key="i" style="font-size: 13px; margin: 4px 0;">
                    {{ r.subject_label || r.subject_type }} → <strong>{{ r.predicate_label || r.predicate }}</strong> → {{ r.object_label || r.object_type }}
                  </div>
                </div>
                <div v-if="dslPreview.error" style="color: #f56c6c;">{{ dslPreview.error }}</div>
              </div>
              <div v-else style="color: #909399; padding: 40px; text-align: center; background: #f5f7fa; border-radius: 6px;">
                点击"解析预览"查看结果
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="TTL 导入/导出" name="ttl">
          <div style="margin-bottom: 16px; display: flex; gap: 12px;">
            <el-button type="success" @click="exportTtl">导出 TTL (Protégé 兼容)</el-button>
            <el-button @click="showTtlImport = !showTtlImport">导入 TTL</el-button>
          </div>
          <div v-if="showTtlImport">
            <el-upload
              :auto-upload="false"
              :show-file-list="true"
              :limit="1"
              accept=".ttl,.txt"
              drag
              :on-change="onTtlFileChange"
              :on-remove="() => (ttlFile = null)"
            >
              <el-button type="primary" size="small">选择 TTL 文件</el-button>
              <template #tip>
                <div class="el-upload__tip">上传 Protégé 导出的 .ttl 本体文件，后台自动解析为「实体-关系-实体」约束</div>
              </template>
            </el-upload>
            <div style="margin-top: 8px; display: flex; gap: 8px; align-items: center;">
              <el-button type="primary" size="small" @click="importTtl" :loading="ttlImporting" :disabled="!ttlFile">确认导入</el-button>
              <span v-if="ttlResult" style="color: #27ae60;">{{ ttlResult }}</span>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 编辑 LLM 配置弹窗 -->
    <el-dialog v-model="editDialog" title="编辑 LLM 配置" width="520px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="阶段">
          <el-select v-model="editForm.pipeline_stage" style="width: 100%;">
            <el-option label="解析质检" value="PARSE_AUDIT" />
            <el-option label="核心抽取" value="EXTRACTION" />
            <el-option label="置信度审批" value="VERIFICATION" />
            <el-option label="融合阶段" value="FUSION" />
          </el-select>
        </el-form-item>
        <el-form-item label="服务商">
          <el-select v-model="editForm.api_provider" style="width: 100%;">
            <el-option label="OpenAI" value="OPENAI" />
            <el-option label="Anthropic" value="ANTHROPIC" />
            <el-option label="DeepSeek" value="DEEPSEEK" />
            <el-option label="Qwen" value="QWEN" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="editForm.base_url" placeholder="https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="editForm.api_key" type="password" show-password placeholder="sk-..." />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="editForm.model_name" placeholder="gpt-4o" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { llmConfigApi, schemaApi, deviceConfigApi, exportApi } from '../api'

const route = useRoute()
const projectId = route.params.id
const llmConfigs = ref([])
const schemas = ref([])
const deviceConfigs = ref([])
const schemaTab = ref('table')
const dslInput = ref('')
const dslPreview = ref(null)
const editDialog = ref(false)
const editForm = reactive({
  pipeline_stage: 'EXTRACTION', api_provider: 'OPENAI', base_url: '', api_key: '', model_name: ''
})
const newSchema = reactive({ subject_type: '', predicate: '', object_type: '' })
let editIndex = -1

// TTL
const showTtlImport = ref(false)
const ttlFile = ref(null)
const ttlImporting = ref(false)
const ttlResult = ref('')

onMounted(async () => {
  await Promise.all([loadConfigs(), loadSchemas(), loadDevices()])
})

async function loadConfigs() {
  try {
    llmConfigs.value = await llmConfigApi.list(projectId)
  } catch (e) {
    ElMessage.error('加载 LLM 配置失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadSchemas() {
  try {
    schemas.value = await schemaApi.list(projectId)
  } catch (e) {
    ElMessage.error('加载 Schema 失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadDevices() {
  try {
    const res = await deviceConfigApi.list(projectId)
    // 补全默认模块
    const defaults = [
      { module_name: 'MINERU', device: 'GPU', gpu_id: 0 },
      { module_name: 'UIE', device: 'CPU', gpu_id: 0 },
      { module_name: 'DEEPKE', device: 'CPU', gpu_id: 0 },
      { module_name: 'EMBEDDING', device: 'CPU', gpu_id: 0 },
    ]
    const existing = new Set(res.map(r => r.module_name))
    deviceConfigs.value = [...res, ...defaults.filter(d => !existing.has(d.module_name))]
  } catch (e) {
    // 接口未就绪时用默认值
    deviceConfigs.value = [
      { module_name: 'MINERU', device: 'GPU', gpu_id: 0 },
      { module_name: 'UIE', device: 'CPU', gpu_id: 0 },
      { module_name: 'DEEPKE', device: 'CPU', gpu_id: 0 },
      { module_name: 'EMBEDDING', device: 'CPU', gpu_id: 0 },
    ]
  }
}

async function saveDevices() {
  try {
    await deviceConfigApi.update(projectId, deviceConfigs.value)
    ElMessage.success('设备配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || ''))
  }
}

function stageLabel(s) {
  return { PARSE_AUDIT: '解析质检', EXTRACTION: '核心抽取', VERIFICATION: '置信度审批', FUSION: '融合阶段' }[s] || s
}

function moduleLabel(m) {
  return { MINERU: 'MinerU (文档解析)', UIE: 'UIE (信息抽取)', DEEPKE: 'DeepKE (NER抽取)', EMBEDDING: '向量嵌入' }[m] || m
}

function addConfig() {
  editIndex = -1
  Object.assign(editForm, { pipeline_stage: 'EXTRACTION', api_provider: 'OPENAI', base_url: '', api_key: '', model_name: '' })
  editDialog.value = true
}

function editConfig(index) {
  editIndex = index
  const c = llmConfigs.value[index]
  Object.assign(editForm, { pipeline_stage: c.pipeline_stage, api_provider: c.api_provider, base_url: c.base_url || '', api_key: '', model_name: c.model_name })
  editDialog.value = true
}

async function deleteConfig(index) {
  try {
    await ElMessageBox.confirm('确认删除该配置?', '提示', { type: 'warning' })
  } catch { return }
  llmConfigs.value.splice(index, 1)
  await saveAllConfigs()
}

async function saveConfig() {
  try {
    if (editIndex >= 0) {
      llmConfigs.value[editIndex] = { ...editForm }
    } else {
      llmConfigs.value.push({ ...editForm })
    }
    await saveAllConfigs()
    editDialog.value = false
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function saveAllConfigs() {
  await llmConfigApi.update(projectId, llmConfigs.value)
  ElMessage.success('保存成功')
  await loadConfigs()
}

function addSchema() {
  if (!newSchema.subject_type || !newSchema.predicate || !newSchema.object_type) {
    ElMessage.warning('请填写完整')
    return
  }
  schemas.value.push({ ...newSchema })
  newSchema.subject_type = ''
  newSchema.predicate = ''
  newSchema.object_type = ''
}

async function saveSchemas() {
  try {
    await schemaApi.update(projectId, schemas.value)
    ElMessage.success('保存成功')
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

async function deleteAllSchemas() {
  try {
    const res = await schemaApi.deleteAll(projectId)
    schemas.value = []
    ElMessage.success(`已删除 ${res.deleted || 0} 条约束`)
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.detail || ''))
  }
}

// DSL 预览（前端纯解析，不调后端）
function parseDslLocal(dsl) {
  if (!dsl || !dsl.trim()) return { error: '空输入' }
  const entities = []
  const relations = []
  const entityMap = new Map() // name -> entity
  let namespace = ''
  let current = null
  let mode = null // 'properties' | 'relations'

  const lines = dsl.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    const line = raw.replace(/\t/g, '    ')
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue

    // namespace
    const nsMatch = trimmed.match(/^namespace\s+(\S+)/)
    if (nsMatch) { namespace = nsMatch[1]; continue }

    // entity header: 支持中英文混杂
    // 格式1: Name(中文标签): EntityType
    // 格式2: 中文标签(Name): EntityType
    const entMatch = trimmed.match(/^([\w\u4e00-\u9fff]+)\s*\(([^)]+)\)\s*:\s*(?:EntityType|IndexType)/)
    if (entMatch) {
      let [, name, label] = entMatch
      // 判断哪个是英文标识符
      if (!/^[a-zA-Z]\w*$/.test(name)) {
        if (/^[a-zA-Z]\w*$/.test(label)) {
          [name, label] = [label, name]
        }
      }
      current = { name, label, namespace, properties: [], relations: [] }
      entities.push(current)
      entityMap.set(name, current)
      mode = null
      continue
    }

    // properties: / relations:
    if (trimmed === 'properties:') { mode = 'properties'; continue }
    if (trimmed === 'relations:') { mode = 'relations'; continue }

    // property/relation line: 支持中英文混杂
    const itemMatch = trimmed.match(/^([\w\u4e00-\u9fff]+)\s*\(([^)]+)\)\s*:\s*(\S+)/)
    if (itemMatch && current) {
      let [, itemName, itemLabel, itemType] = itemMatch
      // 判断哪个是英文标识符
      if (!/^[a-zA-Z]\w*$/.test(itemName)) {
        if (/^[a-zA-Z]\w*$/.test(itemLabel)) {
          [itemName, itemLabel] = [itemLabel, itemName]
        }
      }
      if (mode === 'properties') {
        current.properties.push({ name: itemName, label: itemLabel, type: itemType })
      } else if (mode === 'relations') {
        current.relations.push({ name: itemName, label: itemLabel, target: itemType })
        // 同时生成关系约束
        relations.push({
          subject_type: current.name,
          predicate: itemName,
          predicate_label: itemLabel,
          object_type: itemType,
        })
        // 如果目标类型未定义，创建占位实体
        if (!entityMap.has(itemType)) {
          const placeholder = { name: itemType, label: itemType, namespace, properties: [], relations: [] }
          entities.push(placeholder)
          entityMap.set(itemType, placeholder)
        }
      }
    }
  }
  return { entities, relations, namespace }
}

async function previewDsl() {
  const res = parseDslLocal(dslInput.value)
  dslPreview.value = res
}

async function importDsl() {
  const parsed = parseDslLocal(dslInput.value)
  if (parsed.error) {
    ElMessage.error(parsed.error)
    return
  }
  try {
    // 调后端导入（如果后端接口就绪）
    await schemaApi.importDsl(projectId, dslInput.value)
    ElMessage.success(`导入成功: ${parsed.entities.length} 实体, ${parsed.relations.length} 关系`)
    dslPreview.value = parsed
    await loadSchemas()
  } catch (e) {
    // 后端接口未就绪，仅本地预览
    ElMessage.warning('后端导入接口暂不可用，已本地解析。关系约束将同步到表格。')
    // 把解析出的关系写入 schemas 表格
    for (const r of parsed.relations) {
      schemas.value.push({ subject_type: r.subject_type, predicate: r.predicate, object_type: r.object_type, subject_label: r.subject_label, predicate_label: r.predicate_label, object_label: r.object_label })
    }
    dslPreview.value = parsed
  }
}

// ===== TTL 导入导出 =====
async function exportTtl() {
  try {
    const res = await exportApi.export(projectId, 'ttl')
    const blob = await res.blob?.() || new Blob([res], { type: 'text/turtle' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'schema_export.ttl'
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('TTL 导出成功')
  } catch (e) {
    // 后端可能没有 ttl format，用 graph-data 转本地导出
    try {
      const data = await exportApi.graphData(projectId)
      const triples = (data.edges || []).map(e => ({
        subject: e.source,
        predicate: e.label,
        object: e.target,
      }))
      const ttl = generateTtlLocal(triples)
      const blob = new Blob([ttl], { type: 'text/turtle' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'schema_export.ttl'
      a.click()
      URL.revokeObjectURL(url)
      ElMessage.success('TTL 导出成功 (本地生成)')
    } catch (e2) {
      ElMessage.error('TTL 导出失败: ' + (e2.message || ''))
    }
  }
}

function onTtlFileChange(file) {
  const raw = file.raw
  if (!raw) return
  if (!/\.(ttl|txt)$/i.test(raw.name)) {
    ElMessage.warning('请选择 .ttl 或 .txt 本体文件')
    return
  }
  ttlFile.value = raw
}

async function importTtl() {
  if (!ttlFile.value) {
    ElMessage.warning('请先选择 TTL 文件')
    return
  }
  ttlImporting.value = true
  try {
    const res = await exportApi.importTtl(projectId, ttlFile.value)
    ttlResult.value = res.message || `导入 ${res.relations_imported || 0} 条关系约束`
    ElMessage.success('TTL 导入成功')
    await loadSchemas()
  } catch (e) {
    ElMessage.error('TTL 导入失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    ttlImporting.value = false
  }
}

function generateTtlLocal(triples) {
  const prefixes = [
    '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .',
    '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .',
    '@prefix owl: <http://www.w3.org/2002/07/owl#> .',
    '@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .',
    '@prefix kg: <http://kg.example.org/entity/> .',
    '@prefix kgrel: <http://kg.example.org/relation/> .',
    '',
  ]
  const lines = [...prefixes]
  lines.push('kg:Entity a owl:Class ;')
  lines.push('    rdfs:label "Entity" .')
  lines.push('')
  const entities = new Set()
  const relations = new Set()
  for (const t of triples) {
    entities.add(t.subject)
    entities.add(t.object)
    relations.add(t.predicate)
  }
  for (const e of entities) {
    const safe = e.replace(/[^\w\-.]/g, '_')
    lines.push(`kg:${safe} a kg:Entity ;`)
    lines.push(`    rdfs:label "${e}" .`)
  }
  lines.push('')
  for (const r of relations) {
    const safe = r.replace(/[^\w\-.]/g, '_')
    lines.push(`kgrel:${safe} a owl:ObjectProperty ;`)
    lines.push(`    rdfs:label "${r}" .`)
  }
  lines.push('')
  for (const t of triples) {
    const s = t.subject.replace(/[^\w\-.]/g, '_')
    const p = t.predicate.replace(/[^\w\-.]/g, '_')
    const o = t.object.replace(/[^\w\-.]/g, '_')
    lines.push(`kg:${s} kgrel:${p} kg:${o} .`)
  }
  return lines.join('\n')
}
</script>
