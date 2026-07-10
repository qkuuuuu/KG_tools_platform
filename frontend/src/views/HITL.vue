<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push(`/project/${$route.params.id}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>人工审核工作台</h2>
      <div style="display: flex; align-items: center; gap: 12px; margin-left: auto;">
        <el-popover trigger="click" width="420" @before-enter="loadQuickModel">
          <template #reference>
            <el-button size="small">审核模型: {{ quickForm.model_name || '未配置' }}</el-button>
          </template>
          <div style="padding: 12px;">
            <h4 style="margin: 0 0 12px;">快速切换 置信度审批 模型</h4>
            <el-form label-width="80px" size="small">
              <el-form-item label="服务商">
                <el-select v-model="quickForm.api_provider" style="width: 100%;">
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
        <el-button @click="loadAll">刷新</el-button>
      </div>
    </div>

    <!-- 统计 -->
    <div class="kg-stat-row">
      <div class="kg-stat-item">
        <div class="kg-stat-value">{{ stats.total || 0 }}</div>
        <div class="kg-stat-label">总数</div>
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

    <!-- Tab 切换 -->
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- 待审核 -->
      <el-tab-pane label="待审核" name="pending">
        <div class="kg-card">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <span style="color: #95a5a6; font-size: 13px;">点击"通过"/"拒绝"后自动提交，无需额外操作</span>
            <el-button type="primary" size="small" @click="batchPass" :disabled="!selectedRows.length">批量通过 ({{ selectedRows.length }})</el-button>
          </div>
          <el-table :data="triples" @selection-change="onSelectionChange" stripe style="width: 100%">
            <el-table-column type="selection" width="50" />
            <el-table-column prop="subject" label="主体" min-width="150">
              <template #default="{ row }">
                <el-input v-if="editingId === row.id" v-model="editData.subject" size="small" />
                <span v-else>{{ row.subject }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="predicate" label="关系" min-width="120">
              <template #default="{ row }">
                <el-input v-if="editingId === row.id" v-model="editData.predicate" size="small" />
                <span v-else>{{ row.predicate }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="object" label="客体" min-width="150">
              <template #default="{ row }">
                <el-input v-if="editingId === row.id" v-model="editData.object" size="small" />
                <span v-else>{{ row.object }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="llm_confidence" label="置信度" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.llm_confidence != null" :type="confidenceType(row.llm_confidence)">{{ row.llm_confidence.toFixed(1) }}</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="extraction_method" label="方法" width="120" />
            <el-table-column label="操作" width="280" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="success" @click="quickAction(row, 'PASS')">通过</el-button>
                <el-button size="small" type="danger" @click="quickAction(row, 'REJECT')">拒绝</el-button>
                <el-button size="small" @click="toggleEdit(row)">{{ editingId === row.id ? '完成' : '修改' }}</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div style="margin-top: 16px; text-align: right;">
            <el-pagination
              v-model:current-page="page"
              :page-size="20"
              :total="stats.pending || 0"
              layout="prev, pager, next"
              @current-change="loadPending"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- 已审核 -->
      <el-tab-pane label="已审核" name="reviewed">
        <div class="kg-card">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div style="display: flex; gap: 8px;">
              <el-radio-group v-model="reviewedFilter" @change="loadReviewed">
                <el-radio-button value="all">全部</el-radio-button>
                <el-radio-button value="PASSED">已通过</el-radio-button>
                <el-radio-button value="REJECTED">已拒绝</el-radio-button>
              </el-radio-group>
            </div>
            <span style="color: #95a5a6; font-size: 13px;">撤回 = 退回待审核 | 删除 = 彻底删除</span>
          </div>
          <el-table :data="reviewedTriples" stripe style="width: 100%">
            <el-table-column prop="subject" label="主体" min-width="150" />
            <el-table-column prop="predicate" label="关系" min-width="120" />
            <el-table-column prop="object" label="客体" min-width="150" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'PASSED' ? 'success' : 'danger'" size="small">{{ row.status === 'PASSED' ? '已通过' : '已拒绝' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="extraction_method" label="方法" width="120" />
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="warning" @click="revokeTriple(row)">撤回</el-button>
                <el-button size="small" type="danger" @click="deleteTriple(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div style="margin-top: 16px; text-align: right;">
            <el-pagination
              v-model:current-page="reviewedPage"
              :page-size="20"
              :total="reviewedTotal"
              layout="prev, pager, next"
              @current-change="loadReviewed"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 上下文预览 -->
    <div v-if="contextText" class="kg-card">
      <h3 style="margin-bottom: 12px;">原文上下文</h3>
      <div style="background: #f9f9f9; padding: 16px; border-radius: 4px; max-height: 300px; overflow-y: auto; white-space: pre-wrap;">{{ contextText }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { hitlApi, llmConfigApi } from '../api'
import { useAuthStore } from '../stores'

const quickForm = reactive({ api_provider: 'OPENAI', base_url: '', api_key: '', model_name: '' })
async function loadQuickModel() {
  try {
    const configs = await llmConfigApi.list(projectId)
    const cfg = configs.find(c => c.pipeline_stage === 'VERIFICATION')
    if (cfg) {
      quickForm.api_provider = cfg.api_provider || 'OPENAI'
      quickForm.base_url = cfg.base_url || ''
      quickForm.model_name = cfg.model_name || ''
    }
  } catch (e) {
    ElMessage.error('加载快捷模型配置失败')
  }
}
async function saveQuickModel() {
  try {
    await llmConfigApi.update(projectId, [{ ...quickForm, pipeline_stage: 'VERIFICATION' }])
    ElMessage.success('模型配置已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const route = useRoute()
const projectId = route.params.id
const authStore = useAuthStore()

// 待审核
const triples = ref([])
const stats = ref({})
const page = ref(1)
const selectedRows = ref([])
const editingId = ref(null)
const editData = reactive({ subject: '', predicate: '', object: '' })
const contextText = ref('')

// 已审核
const reviewedTriples = ref([])
const reviewedTotal = ref(0)
const reviewedPage = ref(1)
const reviewedFilter = ref('all')

const activeTab = ref('pending')

onMounted(async () => {
  await loadAll()
})

async function loadAll() {
  await Promise.all([loadPending(), loadStats(), loadReviewed()])
}

async function loadPending() {
  try {
    triples.value = await hitlApi.pending(projectId, page.value)
  } catch (e) {
    ElMessage.error('加载待审核失败')
  }
}

async function loadStats() {
  try {
    stats.value = await hitlApi.stats(projectId)
  } catch (e) {
    ElMessage.error('加载统计失败')
  }
}

async function loadReviewed() {
  try {
    const params = new URLSearchParams()
    params.set('page', reviewedPage.value)
    params.set('page_size', 20)
    if (reviewedFilter.value !== 'all') {
      params.set('status', reviewedFilter.value)
    }
    // 调用后端获取已审核三元组
    const res = await hitlApi.reviewed(projectId, params.toString())
    reviewedTriples.value = res.records || []
    reviewedTotal.value = res.total || 0
  } catch (e) {
    // 后端 reviewed 接口失败时提示用户，不清空已有数据
    ElMessage.error('加载已审核列表失败: ' + (e.response?.data?.detail || e.message))
  }
}

function onTabChange(tab) {
  if (tab === 'reviewed') {
    loadReviewed()
  }
}

function onSelectionChange(rows) {
  selectedRows.value = rows
}

function confidenceType(c) {
  if (c == null) return 'info'
  if (c >= 90) return 'success'
  if (c >= 80) return 'warning'
  return 'danger'
}

// 快速操作：点通过/拒绝后立即提交，从列表移除
async function quickAction(row, action) {
  // 如果正在编辑，先退出编辑
  if (editingId.value === row.id) {
    editingId.value = null
  }

  if (!authStore.username) {
    ElMessage.error('无法获取当前用户名，请重新登录')
    return
  }

  const payload = {
    operator: authStore.username,
    reviews: [{ triple_id: row.id, action }]
  }

  try {
    const res = await hitlApi.review(payload)
    if (res.processed_count > 0) {
      ElMessage.success(`${action === 'PASS' ? '通过' : '拒绝'}成功`)
      // 从列表移除这条
      triples.value = triples.value.filter(t => t.id !== row.id)
      // 刷新统计和已审核列表
      await Promise.all([loadStats(), loadReviewed()])
    } else {
      ElMessage.warning('未处理任何三元组')
    }
  } catch (e) {
    ElMessage.error('操作失败: ' + (e.response?.data?.detail || e.message))
  }
}

// 批量通过
async function batchPass() {
  if (!selectedRows.value.length) return
  if (!authStore.username) {
    ElMessage.warning('无法获取当前用户名，请重新登录')
    return
  }
  const reviews = selectedRows.value.map(row => ({ triple_id: row.id, action: 'PASS' }))
  try {
    const res = await hitlApi.review({ operator: authStore.username, reviews })
    ElMessage.success(`批量通过 ${res.processed_count} 条`)
    selectedRows.value = []
    await Promise.all([loadPending(), loadStats(), loadReviewed()])
  } catch (e) {
    ElMessage.error('批量操作失败')
  }
}

function toggleEdit(row) {
  if (editingId.value === row.id) {
    // 退出编辑 -> 提交修改
    submitEdit(row)
  } else {
    editingId.value = row.id
    editData.subject = row.subject
    editData.predicate = row.predicate
    editData.object = row.object
  }
  contextText.value = row.chunk_text || ''
}

async function submitEdit(row) {
  if (!authStore.username) return
  const payload = {
    operator: authStore.username,
    reviews: [{
      triple_id: row.id,
      action: 'MODIFY',
      modified_subject: editData.subject,
      modified_predicate: editData.predicate,
      modified_object: editData.object,
    }]
  }
  try {
    const res = await hitlApi.review(payload)
    if (res.processed_count > 0) {
      // 更新本地数据
      row.subject = editData.subject
      row.predicate = editData.predicate
      row.object = editData.object
      ElMessage.success('修改已提交，自动通过')
      // 从待审核移除
      triples.value = triples.value.filter(t => t.id !== row.id)
      await Promise.all([loadStats(), loadReviewed()])
    }
    editingId.value = null
  } catch (e) {
    ElMessage.error('修改失败')
  }
}

// 撤回：将 PASSED/REJECTED 改回 PENDING
async function revokeTriple(row) {
  try {
    await ElMessageBox.confirm('撤回后该三元组将回到待审核列表，确认？', '撤回确认', { type: 'warning' })
  } catch { return }

  try {
    await hitlApi.revoke(row.id)
    ElMessage.success('已撤回到待审核')
    reviewedTriples.value = reviewedTriples.value.filter(t => t.id !== row.id)
    reviewedTotal.value--
    await Promise.all([loadStats(), loadPending()])
  } catch (e) {
    ElMessage.error('撤回失败: ' + (e.response?.data?.detail || e.message))
  }
}

// 删除：彻底删除
async function deleteTriple(row) {
  try {
    await ElMessageBox.confirm('删除后无法恢复，确认彻底删除？', '删除确认', { type: 'error' })
  } catch { return }

  try {
    await hitlApi.delete(row.id)
    ElMessage.success('已彻底删除')
    reviewedTriples.value = reviewedTriples.value.filter(t => t.id !== row.id)
    reviewedTotal.value--
    await loadStats()
  } catch (e) {
    ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}
</script>
