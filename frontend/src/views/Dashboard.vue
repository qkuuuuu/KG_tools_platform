<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="router.push('/projects')" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>数据总览 - {{ project?.name }}</h2>
    </div>

    <div class="kg-stat-row">
      <div class="kg-stat-item">
        <div class="kg-stat-value">{{ stats.total || 0 }}</div>
        <div class="kg-stat-label">总三元组</div>
      </div>
      <div class="kg-stat-item">
        <div class="kg-stat-value" style="color: #f39c12;">{{ stats.pending || 0 }}</div>
        <div class="kg-stat-label">待审核</div>
      </div>
      <div class="kg-stat-item">
        <div class="kg-stat-value" style="color: #27ae60;">{{ stats.passed || 0 }}</div>
        <div class="kg-stat-label">已通过</div>
      </div>
      <div class="kg-stat-item">
        <div class="kg-stat-value" style="color: #e74c3c;">{{ stats.rejected || 0 }}</div>
        <div class="kg-stat-label">已拒绝</div>
      </div>
    </div>

    <!-- 项目功能入口 -->
    <div class="kg-card" style="margin-bottom: 20px;">
      <h3 style="margin-bottom: 16px;">项目功能</h3>
      <div style="display: flex; gap: 12px; flex-wrap: wrap;">
        <el-button type="primary" @click="$router.push(`/project/${projectId}/extract`)">文档抽取</el-button>
        <el-button type="warning" @click="$router.push(`/project/${projectId}/hitl`)">人工审核</el-button>
        <el-button @click="$router.push(`/project/${projectId}/config`)">模型配置</el-button>
        <el-button @click="$router.push(`/project/${projectId}/review-history`)">审核历史</el-button>
        <el-button type="success" @click="$router.push(`/project/${projectId}/export`)">导出</el-button>
        <el-button @click="$router.push(`/project/${projectId}/graph`)">图谱可视化</el-button>
        <el-button @click="$router.push(`/project/${projectId}/search`)">三元组搜索</el-button>
        <el-button type="danger" plain :loading="dedupLoading" @click="tripleDedup">LLM 三元组消歧</el-button>
      </div>
    </div>

    <!-- 三元组预览 -->
    <div class="kg-card" style="margin-bottom: 20px;">
      <h3 style="margin-bottom: 16px;">最新三元组</h3>
      <el-table :data="triples" stripe style="width: 100%" max-height="400">
        <el-table-column prop="subject" label="主体" min-width="150" />
        <el-table-column prop="predicate" label="关系" width="180" />
        <el-table-column prop="object" label="客体" min-width="150" />
        <el-table-column prop="confidence" label="置信度" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.confidence != null" :type="confType(row.confidence)" size="small">{{ row.confidence?.toFixed(0) }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="method" label="方法" width="120" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="!triples.length" style="text-align: center; color: #95a5a6; padding: 40px 0;">
        暂无三元组，请先 <router-link :to="`/project/${projectId}/extract`">上传文档并抽取</router-link>
      </p>
    </div>

    <!-- 文档列表 -->
    <div class="kg-card">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
        <h3 style="margin: 0;">文档列表</h3>
        <el-button type="primary" size="small" @click="goToExtract">+ 上传新文档</el-button>
      </div>
      <el-table :data="documents" stripe style="width: 100%">
        <el-table-column prop="file_name" label="文件名" min-width="200" />
        <el-table-column prop="parse_engine_used" label="解析引擎" width="120" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="docStatusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="llm_parse_score" label="解析评分" width="100" />
        <el-table-column prop="created_at" label="上传时间" width="180">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="viewDoc(row)">查看</el-button>
            <el-button size="small" @click="reparseDoc(row)">重新解析</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 文档内容预览弹窗 -->
    <el-dialog v-model="docDialogVisible" :title="currentDoc?.file_name || '文档内容'" width="800px">
      <div v-if="currentDoc">
        <el-descriptions :column="2" border style="margin-bottom: 16px;">
          <el-descriptions-item label="解析引擎">{{ currentDoc.parse_engine_used }}</el-descriptions-item>
          <el-descriptions-item label="解析评分">{{ currentDoc.llm_parse_score }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ currentDoc.status }}</el-descriptions-item>
          <el-descriptions-item label="上传时间">{{ formatDate(currentDoc.created_at) }}</el-descriptions-item>
        </el-descriptions>
        <el-input
          v-model="currentDoc.md_content"
          type="textarea"
          :rows="16"
          readonly
          placeholder="无解析内容"
        />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { extractApi, docApi, fusionApi } from '../api'
import { useProjectStore } from '../stores'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const project = computed(() => projectStore.current)
const projectId = route.params.id
const stats = ref({ total: 0, pending: 0, passed: 0, rejected: 0 })
const triples = ref([])
const documents = ref([])
const docDialogVisible = ref(false)
const currentDoc = ref(null)
const dedupLoading = ref(false)

async function loadStats() {
  try {
    stats.value = await extractApi.getTripleStats(projectId)
  } catch (e) {
    ElMessage.error('加载统计失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function loadTriples() {
  try {
    // 只加载50条用于预览，统计走专用接口
    triples.value = await extractApi.getTriples(projectId, null, 50)
  } catch (e) {
    ElMessage.error('加载三元组失败: ' + (e.response?.data?.detail || e.message))
  }
}

onMounted(async () => {
  await Promise.all([loadStats(), loadTriples()])
  try {
    const res = await docApi.list(projectId)
    documents.value = res?.items || res || []
  } catch (e) {
    ElMessage.error('加载文档列表失败: ' + (e.response?.data?.detail || e.message))
  }
})

async function tripleDedup() {
  dedupLoading.value = true
  try {
    const res = await fusionApi.tripleDedup(projectId)
    ElMessage.success(res.message || `消歧完成：合并 ${res.total_merged || 0} 条`)
    await Promise.all([loadStats(), loadTriples()])  // 刷新统计+预览
  } catch (e) {
    ElMessage.error('消歧失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    dedupLoading.value = false
  }
}

function goToExtract() {
  router.push(`/project/${projectId}/extract`)
}

async function viewDoc(row) {
  try {
    currentDoc.value = await docApi.getDoc(row.id)
    docDialogVisible.value = true
  } catch (e) {
    currentDoc.value = row
    docDialogVisible.value = true
  }
}

async function reparseDoc(row) {
  // 跳转到抽取页并带上文档 ID，便于在该页定位该文档进行重新抽取/解析
  router.push({ path: `/project/${projectId}/extract`, query: { doc_id: row.id } })
}

function confType(c) {
  if (c >= 90) return 'success'
  if (c >= 70) return 'warning'
  return 'danger'
}

function statusType(s) {
  const map = { PASSED: 'success', PENDING: 'warning', REJECTED: 'danger', FUSED: 'info', MERGED: 'info' }
  return map[s] || 'info'
}

function docStatusType(s) {
  const map = { DONE: 'success', PROCESSING: 'warning', FAILED: 'danger', PENDING: 'info' }
  return map[s] || 'info'
}

function formatDate(s) {
  if (!s) return ''
  // 后端存 UTC 时间但无 Z 后缀，补上 Z 让 JS 按 UTC 解析
  let str = String(s)
  if (!str.endsWith('Z') && !str.includes('+') && !str.match(/\d{2}:\d{2}:\d{2}\.\d/)) {
    str = str + 'Z'
  }
  const d = new Date(str)
  if (isNaN(d)) return s
  return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
</script>
