<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="router.push(`/project/${projectId}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>文档解析与抽取工作流</h2>
      <el-popover trigger="click" width="420" @before-enter="loadCurrentModel">
        <template #reference>
          <el-button size="small" style="margin-left: auto;">
            当前模型: {{ currentModelName }}
          </el-button>
        </template>
        <div style="padding: 12px;">
          <h4 style="margin: 0 0 12px;">快速切换 {{ stageLabel }} 模型</h4>
          <el-form label-width="80px" size="small">
            <el-form-item label="服务商">
              <el-select v-model="quickForm.api_provider" style="width: 100%">
                <el-option label="OpenAI" value="OPENAI" />
                <el-option label="Anthropic" value="ANTHROPIC" />
                <el-option label="DeepSeek" value="DEEPSEEK" />
                <el-option label="Qwen" value="QWEN" />
              </el-select>
            </el-form-item>
            <el-form-item label="Base URL">
              <el-input v-model="quickForm.base_url" placeholder="https://api.openai.com/v1" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input v-model="quickForm.api_key" type="password" show-password />
            </el-form-item>
            <el-form-item label="模型名">
              <el-input v-model="quickForm.model_name" placeholder="gpt-4o" />
            </el-form-item>
          </el-form>
          <el-button type="primary" size="small" @click="saveQuickModel" style="width: 100%; margin-top: 8px;">保存</el-button>
        </div>
      </el-popover>
    </div>

    <!-- 文档解析任务表 -->
    <div class="kg-card" style="margin-bottom: 20px;">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
        <h3 style="margin: 0;">文档解析任务</h3>
        <el-button type="primary" size="small" @click="showUploadDialog = true">+ 上传新文档</el-button>
      </div>
      <div style="margin-bottom: 8px; display: flex; gap: 8px;" v-if="docSelection.length">
        <el-button type="danger" size="small" @click="batchDeleteDocs" :loading="batchDeleting">批量删除 ({{ docSelection.length }})</el-button>
      </div>
      <el-table :data="docTasks" stripe style="width: 100%" max-height="320" empty-text="暂无文档，点击右上角上传" @selection-change="onDocSelectionChange">
        <el-table-column type="selection" width="45" />
        <el-table-column prop="file_name" label="文件名" min-width="180" />
        <el-table-column prop="parse_engine_used" label="解析引擎" width="120">
          <template #default="{ row }">{{ row.parse_engine_used || row.parse_engine || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="taskTagType(row.status)" size="small">{{ taskStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="180">
          <template #default="{ row }">
            <el-progress
              :percentage="row.progress || (row.status === 'DONE' ? 100 : 0)"
              :status="row.status === 'DONE' ? 'success' : row.status === 'FAILED' ? 'exception' : ''"
              :stroke-width="14"
            />
          </template>
        </el-table-column>
        <el-table-column prop="llm_parse_score" label="解析评分" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.llm_parse_score" size="small" type="success">{{ row.llm_parse_score }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewDocDetail(row)">查看</el-button>
            <el-button size="small" type="success" @click="goExtract(row)" :disabled="row.status !== 'DONE'">抽取</el-button>
            <el-button size="small" @click="downloadMd(row)">MD</el-button>
            <el-button size="small" type="danger" text @click="deleteDoc(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 抽取任务表 -->
    <div class="kg-card" style="margin-bottom: 20px;">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
        <h3 style="margin: 0;">知识抽取任务</h3>
        <span style="font-size: 12px; color: #95a5a6;">从已解析文档中抽取三元组</span>
      </div>
      <div style="margin-bottom: 8px; display: flex; gap: 8px;" v-if="extractSelection.length">
        <el-button type="danger" size="small" @click="batchDeleteExtractTasks" :loading="batchDeleting">批量删除 ({{ extractSelection.length }})</el-button>
      </div>
      <el-table :data="extractTasks" stripe style="width: 100%" max-height="280" empty-text="暂无抽取任务" @selection-change="onExtractSelectionChange">
        <el-table-column type="selection" width="45" />
        <el-table-column prop="doc_name" label="源文档" min-width="160" />
        <el-table-column prop="extraction_method" label="引擎" width="120">
          <template #default="{ row }">
            <el-tag size="small" v-if="row.extraction_method">{{ row.extraction_method }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="taskTagType(row.status)" size="small">{{ taskStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            <el-progress
              :percentage="row.progress || (row.status === 'DONE' ? 100 : 0)"
              :status="row.status === 'DONE' ? 'success' : row.status === 'FAILED' ? 'exception' : ''"
              :stroke-width="14"
            />
          </template>
        </el-table-column>
        <el-table-column prop="triple_count" label="三元组数" width="90">
          <template #default="{ row }">
            {{ row.status === 'DONE' ? (row.triple_count != null ? row.triple_count : (row.result?.extracted_count ?? '-')) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewExtractResult(row)" :disabled="row.status !== 'DONE'">查看结果</el-button>
            <el-button size="small" type="warning" @click="goQualityCheck(row)" :disabled="row.status !== 'DONE'">质检</el-button>
            <el-button size="small" type="danger" text @click="deleteExtractTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 质检任务表 -->
    <div class="kg-card">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
        <h3 style="margin: 0;">质检任务</h3>
        <span style="font-size: 12px; color: #95a5a6;">LLM 置信度审核与分流</span>
      </div>
      <div style="margin-bottom: 8px; display: flex; gap: 8px;" v-if="qualitySelection.length">
        <el-button type="danger" size="small" @click="batchDeleteQualityTasks" :loading="batchDeleting">批量删除 ({{ qualitySelection.length }})</el-button>
      </div>
      <el-table :data="qualityTasks" stripe style="width: 100%" max-height="240" empty-text="暂无质检任务" @selection-change="onQualitySelectionChange">
        <el-table-column type="selection" width="45" />
        <el-table-column prop="doc_name" label="源文档" min-width="160" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="taskTagType(row.status)" size="small">{{ taskStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            <el-progress
              :percentage="row.progress || (row.status === 'DONE' ? 100 : 0)"
              :status="row.status === 'DONE' ? 'success' : row.status === 'FAILED' ? 'exception' : ''"
              :stroke-width="14"
            />
          </template>
        </el-table-column>
        <el-table-column label="通过/拒绝/待审" width="160">
          <template #default="{ row }">
            <span v-if="row.result">
              <span style="color: #27ae60;">{{ row.result.passed || 0 }}</span> /
              <span style="color: #e74c3c;">{{ row.result.rejected || 0 }}</span> /
              <span style="color: #f39c12;">{{ row.result.pending || 0 }}</span>
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="success" @click="goToHitl" :disabled="row.status !== 'DONE'">前往审核</el-button>
            <el-button size="small" type="danger" text @click="deleteQualityTask(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 上传对话框 -->
    <el-dialog v-model="showUploadDialog" title="上传文档" width="560px">
      <el-form label-width="100px">
        <el-form-item label="解析引擎">
          <el-select v-model="form.parseEngine" style="width: 100%;">
            <el-option label="自动选择 (按文件类型)" value="auto" />
            <el-option label="pdfplumber (原生PDF，快速)" value="pdfplumber" />
            <el-option label="PyMuPDF (高速PDF)" value="PyMuPDF" />
            <el-option label="MinerU (复杂文档/学术)" value="MinerU" />
            <el-option label="python-docx (Word)" value="python-docx" />
            <el-option label="PaddleOCR (扫描件/图片)" value="PaddleOCR" />
            <el-option label="CSV 解析" value="csv" />
            <el-option label="Excel 解析" value="excel" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="10"
            multiple
            :on-change="handleFileChange"
            :file-list="fileList"
            drag
            accept=".pdf,.docx,.txt,.html,.pptx,.csv,.xlsx,.xls"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽文件到此处或 <em>点击上传</em></div>
            <template #tip>
              <div class="el-upload__tip">支持 PDF / DOCX / TXT / HTML / PPTX / CSV / Excel，最大 50MB</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showUploadDialog = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="doUpload">上传并解析</el-button>
      </template>
    </el-dialog>

    <!-- 文档详情对话框 -->
    <el-dialog v-model="docDetailVisible" :title="`文档: ${currentDoc?.file_name || ''}`" width="80%" top="5vh">
      <div v-if="currentDoc" style="max-height: 70vh; overflow-y: auto;">
        <el-descriptions :column="3" border style="margin-bottom: 16px;">
          <el-descriptions-item label="文件名">{{ currentDoc.file_name }}</el-descriptions-item>
          <el-descriptions-item label="解析引擎">{{ currentDoc.parse_engine_used }}</el-descriptions-item>
          <el-descriptions-item label="解析评分">{{ currentDoc.llm_parse_score || '-' }}</el-descriptions-item>
          <el-descriptions-item label="内容长度">{{ (currentDoc.md_content || '').length }} 字符</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="taskTagType(currentDoc.status)" size="small">{{ taskStatusLabel(currentDoc.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="上传时间">{{ formatDate(currentDoc.created_at) }}</el-descriptions-item>
        </el-descriptions>
        <div style="display: flex; gap: 8px; margin-bottom: 12px;">
          <el-button @click="downloadMd(currentDoc)" size="small" :disabled="!currentDoc.md_content">下载 Markdown</el-button>
        </div>
        <div style="background: #f9f9f9; padding: 16px; border-radius: 4px; border: 1px solid #e0e0e0;">
          <pre style="white-space: pre-wrap; font-size: 13px; line-height: 1.6; margin: 0;">{{ currentDoc.md_content || '(无内容)' }}</pre>
        </div>
      </div>
    </el-dialog>

    <!-- 抽取对话框 -->
    <el-dialog v-model="extractDialogVisible" title="知识抽取" width="600px">
      <el-alert
        v-if="currentDoc"
        :title="`文档: ${currentDoc.file_name} | 内容: ${(currentDoc.md_content || '').length} 字符`"
        type="info" style="margin-bottom: 16px;"
      />
      <el-form label-width="100px">
        <el-form-item label="抽取引擎">
          <el-radio-group v-model="form.extractMethod">
            <el-radio-button
              v-for="engine in availableEngines"
              :key="engine.key"
              :value="engine.key"
              :disabled="engine.status !== 'ready'"
            >
              {{ engine.name }}
              <el-tag v-if="engine.status !== 'ready'" size="small" type="danger" style="margin-left: 4px;">需安装</el-tag>
            </el-radio-button>
          </el-radio-group>
          <div style="margin-top: 8px; font-size: 12px; color: #95a5a6;">
            {{ currentEngineDesc }}
          </div>
        </el-form-item>

        <!-- 自定义脚本选择 -->
        <el-form-item v-if="form.extractMethod === 'CUSTOM_SCRIPT'" label="选择脚本">
          <div style="display: flex; gap: 8px; width: 100%;">
            <el-select v-model="form.scriptId" placeholder="请选择已上传的脚本" style="flex: 1;">
              <el-option
                v-for="s in scriptList"
                :key="s.script_id"
                :label="s.filename + (s.description ? ' (' + s.description + ')' : '')"
                :value="s.script_id"
              />
            </el-select>
            <el-button type="primary" size="default" @click="showScriptUploadDialog = true">上传脚本</el-button>
            <el-button type="danger" size="default" @click="deleteScript(form.scriptId)" :disabled="!form.scriptId">删除脚本</el-button>
          </div>
          <div style="margin-top: 8px; font-size: 12px; color: #95a5a6;">
            上传 .py 文件，需实现 extract(md_content: str, schemas: list) -> list 接口
          </div>
        </el-form-item>

        <!-- Schema 多选 -->
        <el-form-item label="Schema">
          <el-select v-model="form.schemaIds" multiple placeholder="不选则使用项目全部 schema" style="width: 100%;">
            <el-option
              v-for="s in schemaList"
              :key="s.id || `${s.subject_type}-${s.predicate}-${s.object_type}`"
              :label="s.name || `${s.subject_type} -${s.predicate}-> ${s.object_type}`"
              :value="s.id"
            />
          </el-select>
          <div style="margin-top: 8px; font-size: 12px; color: #95a5a6;">
            选择约束抽取范围的 schema；不选则使用项目下全部 schema
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="extractDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="extracting" @click="doExtract" :disabled="form.extractMethod === 'CUSTOM_SCRIPT' && !form.scriptId">开始抽取</el-button>
      </template>
    </el-dialog>

    <!-- 脚本上传对话框 -->
    <el-dialog v-model="showScriptUploadDialog" title="上传 Python 脚本" width="500px">
      <el-form label-width="100px">
        <el-form-item label="脚本文件">
          <el-upload
            ref="scriptUploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="handleScriptFileChange"
            :file-list="scriptFileList"
            drag
            accept=".py"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽 .py 文件到此处或 <em>点击上传</em></div>
            <template #tip>
              <div class="el-upload__tip">仅支持 .py 文件，最大 1MB</div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item label="脚本说明">
          <el-input v-model="scriptDescription" placeholder="简要描述脚本功能" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showScriptUploadDialog = false">取消</el-button>
        <el-button type="primary" :loading="uploadingScript" @click="doUploadScript">上传</el-button>
      </template>
    </el-dialog>

    <!-- 质检对话框 -->
    <el-dialog v-model="qualityDialogVisible" title="LLM 质检" width="640px">
      <el-form label-width="100px">
        <el-form-item label="置信度阈值">
          <el-slider
            v-model="form.qualityThreshold"
            :min="50" :max="100"
            :marks="{ 50: '50%', 75: '75%', 90: '90%', 100: '100%' }"
            style="width: 100%;"
          />
          <span style="margin-left: 16px;">{{ form.qualityThreshold }}%</span>
        </el-form-item>
        <el-form-item label="质检基准">
          <el-upload
            ref="benchmarkUploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="onBenchmarkFileChange"
            :on-remove="onBenchmarkFileRemove"
            accept=".txt,.md,.json,.docx"
            style="width: 100%;"
          >
            <template #trigger>
              <el-button size="small">选择文件</el-button>
            </template>
            <template #tip>
              <div class="el-upload__tip">
                上传约束文档/质检规范（txt/md/json/docx），帮助 LLM 更准确地审核三元组是否符合领域规范
              </div>
            </template>
          </el-upload>
          <div v-if="benchmarkFile" style="margin-top: 6px; color: #67c23a; font-size: 12px;">
            ✅ 已选择: {{ benchmarkFile.name }}
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="qualityDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="checking" @click="doQualityCheck">开始质检</el-button>
      </template>
    </el-dialog>

    <!-- 抽取结果对话框 -->
    <el-dialog v-model="extractResultVisible" title="抽取结果" width="80%" top="5vh">
      <div v-if="extractedTriples.length" style="max-height: 70vh; overflow-y: auto;">
        <p style="margin-bottom: 12px; color: #606266;">共 {{ extractedTriples.length }} 条三元组</p>
        <el-table :data="extractedTriples" stripe style="width: 100%" max-height="500">
          <el-table-column prop="subject" label="主体" min-width="120" />
          <el-table-column prop="predicate" label="关系" width="120" />
          <el-table-column prop="object" label="客体" min-width="120" />
          <el-table-column prop="confidence" label="置信度" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.confidence != null" :type="row.confidence >= 90 ? 'success' : row.confidence >= 70 ? 'warning' : 'danger'" size="small">
                {{ row.confidence.toFixed(0) }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="extraction_method" label="方法" width="100">
            <template #default="{ row }">
              <el-tag size="small">{{ row.extraction_method }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="taskTagType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-empty v-else description="暂无抽取结果" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { docApi, extractApi, llmConfigApi, scriptApi, schemaApi } from '../api'
import api from '../api'
import { useAuthStore } from '../stores'

const route = useRoute()
const router = useRouter()
const projectId = route.params.id
const authStore = useAuthStore()

// ====== 数据 ======
const docTasks = ref([])
const extractTasks = ref([])
const qualityTasks = ref([])
const availableEngines = ref([])
const extractedTriples = ref([])
const scriptList = ref([])
const schemaList = ref([])

// 对话框
const showUploadDialog = ref(false)
const docDetailVisible = ref(false)
const extractDialogVisible = ref(false)
const qualityDialogVisible = ref(false)
const benchmarkFile = ref(null)
const benchmarkUploadRef = ref(null)
const extractResultVisible = ref(false)
const showScriptUploadDialog = ref(false)

const currentDoc = ref(null)

const form = reactive({
  parseEngine: 'auto',
  extractMethod: 'LLM_PROMPT',
  qualityThreshold: 90,
  scriptId: '',
  schemaIds: [],
})

const uploading = ref(false)
const extracting = ref(false)
const checking = ref(false)
const uploadRef = ref()
const selectedFile = ref(null)
const fileList = ref([])

// 脚本上传相关
const scriptUploadRef = ref()
const selectedScriptFile = ref(null)
const scriptFileList = ref([])
const scriptDescription = ref('')
const uploadingScript = ref(false)

// 批量操作相关
const docSelection = ref([])
const extractSelection = ref([])
const qualitySelection = ref([])
const batchDeleting = ref(false)

const quickForm = reactive({ api_provider: 'OPENAI', base_url: '', api_key: '', model_name: '' })
const currentModelName = ref('未配置')
const modelLoaded = ref(false)

async function loadCurrentModelName() {
  if (modelLoaded.value) return
  try {
    const res = await llmConfigApi.list(projectId)
    const extractionCfg = (res || []).find(c => c.pipeline_stage === 'EXTRACTION')
    if (extractionCfg && extractionCfg.model_name) {
      currentModelName.value = extractionCfg.model_name
    }
    modelLoaded.value = true
  } catch (e) {
    modelLoaded.value = true
  }
}

onMounted(() => {
  loadCurrentModelName()
})
const stageLabel = computed(() => '当前阶段')
const currentEngineDesc = computed(() => {
  const engine = availableEngines.value.find(e => e.key === form.extractMethod)
  return engine ? engine.description : ''
})

function taskTagType(s) {
  if (s === 'DONE') return 'success'
  if (s === 'FAILED') return 'danger'
  if (s === 'RUNNING' || s === 'PROCESSING') return 'warning'
  return 'info'
}
function taskStatusLabel(s) {
  const map = { DONE: '已完成', FAILED: '失败', RUNNING: '进行中', PROCESSING: '解析中', PENDING: '等待中' }
  return map[s] || s
}
function formatDate(s) {
  if (!s) return ''
  let str = String(s)
  if (!str.endsWith('Z') && !str.includes('+') && !str.match(/\d{2}:\d{2}:\d{2}\.\d/)) {
    str = str + 'Z'
  }
  const d = new Date(str)
  if (isNaN(d)) return s
  return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

// ====== 脚本管理 ======
async function loadScripts() {
  try {
    const res = await scriptApi.list()
    scriptList.value = res.scripts || []
  } catch (e) {
    ElMessage.error('加载脚本列表失败: ' + (e.response?.data?.detail || e.message))
  }
}

// ====== Schema 管理 ======
async function loadSchemas() {
  try {
    const res = await schemaApi.list(projectId)
    schemaList.value = res || []
  } catch (e) {
    ElMessage.error('加载 Schema 列表失败: ' + (e.response?.data?.detail || e.message))
  }
}

function handleScriptFileChange(file) {
  selectedScriptFile.value = file.raw
  scriptFileList.value = [file]
}

async function doUploadScript() {
  if (!selectedScriptFile.value) {
    ElMessage.warning('请先选择 .py 脚本文件')
    return
  }
  uploadingScript.value = true
  try {
    const res = await scriptApi.upload(selectedScriptFile.value, scriptDescription.value)
    ElMessage.success(`脚本上传成功: ${res.filename}`)
    showScriptUploadDialog.value = false
    selectedScriptFile.value = null
    scriptFileList.value = []
    scriptDescription.value = ''
    await loadScripts()
    // 自动选中新上传的脚本
    form.scriptId = res.script_id
  } catch (e) {
    ElMessage.error('脚本上传失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    uploadingScript.value = false
  }
}

async function deleteScript(scriptId) {
  try {
    await ElMessageBox.confirm('确认删除该脚本?', '提示', { type: 'warning' })
    await scriptApi.delete(scriptId)
    ElMessage.success('脚本已删除')
    await loadScripts()
    if (form.scriptId === scriptId) {
      form.scriptId = ''
    }
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  }
}

// ====== 文档/抽取相关 ======
function handleFileChange(file, uploadFileList) {
  fileList.value = uploadFileList
  selectedFile.value = file.raw
}

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

async function loadDocs() {
  try {
    const res = await docApi.list(projectId)
    docTasks.value = res.items || res || []
  } catch (e) {
    ElMessage.error('加载文档失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadEngines() {
  try {
    const res = await extractApi.engines()
    availableEngines.value = res.engines || []
  } catch (e) {
    ElMessage.error('加载引擎列表失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function viewDocDetail(row) {
  currentDoc.value = row
  docDetailVisible.value = true
  try {
    const doc = await docApi.getDoc(row.id)
    if (doc.md_content) {
      currentDoc.value = { ...row, ...doc }
    }
  } catch (e) {
    ElMessage.error('获取文档详情失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function downloadMd(row) {
  try {
    // 先从后端获取完整文档内容（列表中可能不含 md_content）
    const doc = await docApi.getDoc(row.id)
    const mdContent = doc.md_content || row.md_content
    if (!mdContent) {
      ElMessage.warning('该文档暂无解析内容')
      return
    }
    const blob = new Blob([mdContent], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = (row.file_name || 'document').replace(/\.[^.]+$/, '.md')
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('下载失败: ' + (e.response?.data?.detail || e.message))
  }
}

function goExtract(row) {
  currentDoc.value = row
  extractDialogVisible.value = true
  // 如果选择自定义脚本引擎，加载脚本列表
  if (form.extractMethod === 'CUSTOM_SCRIPT') {
    loadScripts()
  }
}

// 监听引擎切换，如果是 CUSTOM_SCRIPT 则加载脚本列表
watch(() => form.extractMethod, (newVal) => {
  if (newVal === 'CUSTOM_SCRIPT') {
    loadScripts()
  }
})

async function doExtract() {
  if (!currentDoc.value) return
  if (form.extractMethod === 'CUSTOM_SCRIPT' && !form.scriptId) {
    ElMessage.warning('请先选择或上传一个 Python 脚本')
    return
  }
  extracting.value = true
  try {
    // schemaIds：用户选择则用所选；未选则传空数组，由后端按项目全部 schema 处理
    await extractApi.extract(currentDoc.value.id, form.extractMethod, form.schemaIds || [], form.scriptId || undefined)
    ElMessage.success('抽取任务已启动')
    extractDialogVisible.value = false
    await loadExtractTasks()
  } catch (e) {
    ElMessage.error('抽取失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    extracting.value = false
  }
}

async function loadExtractTasks() {
  try {
    const res = await api.get('/data/tasks', { params: { project_id: projectId, task_type: 'EXTRACT' } })
    extractTasks.value = res || []
  } catch (e) {
    ElMessage.error('加载抽取任务失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadQualityTasks() {
  try {
    const res = await api.get('/data/tasks', { params: { project_id: projectId, task_type: 'QUALITY_CHECK' } })
    qualityTasks.value = res || []
  } catch (e) {
    ElMessage.error('加载质检任务失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function viewExtractResult(row) {
  try {
    // 按任务 ID 过滤，只显示该任务抽取的三元组
    const res = await extractApi.getTriples(projectId, null, null, row.id)
    extractedTriples.value = res || []
    extractResultVisible.value = true
  } catch (e) {
    ElMessage.error('加载结果失败: ' + (e.response?.data?.detail || e.message))
  }
}

function goQualityCheck(row) {
  currentDoc.value = row
  benchmarkFile.value = null
  qualityDialogVisible.value = true
}

function onBenchmarkFileChange(file, fileList) {
  // limit=1，取最新的一个
  benchmarkFile.value = file.raw || null
}

function onBenchmarkFileRemove() {
  benchmarkFile.value = null
}

// 质检对话框关闭时清理 upload 组件文件列表
watch(qualityDialogVisible, (v) => {
  if (!v) {
    benchmarkFile.value = null
    // 清除 el-upload 组件内部文件列表
    if (benchmarkUploadRef.value) {
      benchmarkUploadRef.value.clearFiles()
    }
  }
})

async function doQualityCheck() {
  if (!currentDoc.value) return
  // row 是 extractTask，doc_id 才是文档 ID，不能误用 task id
  const docId = currentDoc.value.doc_id || currentDoc.value.id
  if (!docId) {
    ElMessage.error('无法获取文档 ID，请刷新页面重试')
    return
  }
  checking.value = true
  try {
    await extractApi.qualityCheck(docId, form.qualityThreshold, benchmarkFile.value)
    ElMessage.success('质检任务已启动')
    qualityDialogVisible.value = false
  } catch (e) {
    ElMessage.error('质检失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    checking.value = false
  }
}

function goToHitl() {
  router.push(`/project/${projectId}/hitl`)
}

async function loadCurrentModel() {
  try {
    const res = await llmConfigApi.list(projectId)
    const configs = res || []
    const extractionCfg = configs.find(c => c.pipeline_stage === 'EXTRACTION')
    if (extractionCfg) {
      quickForm.api_provider = extractionCfg.api_provider || 'OPENAI'
      quickForm.base_url = extractionCfg.base_url || ''
      quickForm.api_key = extractionCfg.api_key || ''
      quickForm.model_name = extractionCfg.model_name || ''
      if (extractionCfg.model_name) {
        currentModelName.value = extractionCfg.model_name
      }
    }
  } catch (e) {
    ElMessage.error('加载模型配置失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function saveQuickModel() {
  try {
    const configs = await llmConfigApi.list(projectId)
    const configList = configs || []
    const extractionCfg = configList.find(c => c.pipeline_stage === 'EXTRACTION')
    if (extractionCfg) {
      extractionCfg.api_provider = quickForm.api_provider
      extractionCfg.base_url = quickForm.base_url
      extractionCfg.api_key = quickForm.api_key
      extractionCfg.model_name = quickForm.model_name
    } else {
      configList.push({
        pipeline_stage: 'EXTRACTION',
        api_provider: quickForm.api_provider,
        base_url: quickForm.base_url,
        api_key: quickForm.api_key,
        model_name: quickForm.model_name,
      })
    }
    await llmConfigApi.update(projectId, configList)
    currentModelName.value = quickForm.model_name || '未配置'
    ElMessage.success('模型配置已保存')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

// ====== 删除操作 ======
function onDocSelectionChange(sel) { docSelection.value = sel }
function onExtractSelectionChange(sel) { extractSelection.value = sel }
function onQualitySelectionChange(sel) { qualitySelection.value = sel }

async function deleteDoc(row) {
  try {
    await ElMessageBox.confirm(`确认删除文档「${row.file_name}」及其关联的所有三元组和任务?`, '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await docApi.delete(row.id)
    ElMessage.success('删除成功')
    await loadDocs()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteExtractTask(row) {
  try {
    await ElMessageBox.confirm(`确认删除抽取任务「${row.doc_name || ''}」?`, '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await extractApi.deleteTask(row.id)
    ElMessage.success('删除成功')
    await loadExtractTasks()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteQualityTask(row) {
  try {
    await ElMessageBox.confirm(`确认删除质检任务「${row.doc_name || ''}」?`, '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await extractApi.deleteQualityTask(row.id)
    ElMessage.success('删除成功')
    await loadQualityTasks()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function batchDeleteDocs() {
  try {
    await ElMessageBox.confirm(`确认批量删除 ${docSelection.value.length} 个文档?`, '批量删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    batchDeleting.value = true
    let ok = 0, fail = 0
    for (const row of docSelection.value) {
      try { await docApi.delete(row.id); ok++ } catch { fail++ }
    }
    ElMessage.success(`批量删除完成: 成功 ${ok} 条${fail ? ', 失败 ' + fail + ' 条' : ''}`)
    await loadDocs()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('批量删除失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    batchDeleting.value = false
  }
}

async function batchDeleteExtractTasks() {
  try {
    await ElMessageBox.confirm(`确认批量删除 ${extractSelection.value.length} 个抽取任务?`, '批量删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    batchDeleting.value = true
    let ok = 0, fail = 0
    for (const row of extractSelection.value) {
      try { await extractApi.deleteTask(row.id); ok++ } catch { fail++ }
    }
    ElMessage.success(`批量删除完成: 成功 ${ok} 条${fail ? ', 失败 ' + fail + ' 条' : ''}`)
    await loadExtractTasks()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('批量删除失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    batchDeleting.value = false
  }
}

async function batchDeleteQualityTasks() {
  try {
    await ElMessageBox.confirm(`确认批量删除 ${qualitySelection.value.length} 个质检任务?`, '批量删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    batchDeleting.value = true
    let ok = 0, fail = 0
    for (const row of qualitySelection.value) {
      try { await extractApi.deleteQualityTask(row.id); ok++ } catch { fail++ }
    }
    ElMessage.success(`批量删除完成: 成功 ${ok} 条${fail ? ', 失败 ' + fail + ' 条' : ''}`)
    await loadQualityTasks()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('批量删除失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    batchDeleting.value = false
  }
}

// ====== 生命周期 ======
let pollTimer = null

onMounted(async () => {
  await Promise.all([loadDocs(), loadEngines(), loadScripts(), loadSchemas(), loadExtractTasks(), loadQualityTasks()])
  // 仅当有进行中的任务时才轮询
  pollTimer = setInterval(async () => {
    const hasActive =
      docTasks.value.some(t => t.status === 'PENDING' || t.status === 'RUNNING' || t.status === 'PROCESSING') ||
      extractTasks.value.some(t => t.status === 'PENDING' || t.status === 'RUNNING') ||
      qualityTasks.value.some(t => t.status === 'PENDING' || t.status === 'RUNNING')
    if (hasActive) {
      await Promise.all([loadDocs(), loadExtractTasks(), loadQualityTasks()])
    }
  }, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
