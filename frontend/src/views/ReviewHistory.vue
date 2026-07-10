<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push(`/project/${$route.params.id}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>审核历史与统计</h2>
      <div style="display: flex; gap: 8px; margin-left: auto;">
        <el-button type="success" @click="syncToGraph" :loading="syncing">同步已通过三元组到图谱</el-button>
        <el-button @click="loadAll">刷新</el-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="kg-stat-row">
      <div class="kg-stat-item">
        <div class="kg-stat-value">{{ stats.total_reviews || 0 }}</div>
        <div class="kg-stat-label">总审核数</div>
      </div>
      <div class="kg-stat-item">
        <div class="kg-stat-value" style="color: #27ae60;">{{ stats.pass_rate || 0 }}%</div>
        <div class="kg-stat-label">通过率</div>
      </div>
      <div class="kg-stat-item">
        <div class="kg-stat-value" style="color: #3498db;">{{ stats.operator_distribution?.length || 0 }}</div>
        <div class="kg-stat-label">审核人数</div>
      </div>
    </div>

    <!-- 操作分布 -->
    <div class="kg-card" v-if="stats.action_distribution">
      <h3 style="margin-bottom: 16px;">操作分布</h3>
      <el-row :gutter="16">
        <el-col :span="8">
          <div style="text-align: center;">
            <div style="font-size: 24px; color: #27ae60;">{{ stats.action_distribution.PASS || 0 }}</div>
            <div>通过</div>
          </div>
        </el-col>
        <el-col :span="8">
          <div style="text-align: center;">
            <div style="font-size: 24px; color: #e74c3c;">{{ stats.action_distribution.REJECT || 0 }}</div>
            <div>拒绝</div>
          </div>
        </el-col>
        <el-col :span="8">
          <div style="text-align: center;">
            <div style="font-size: 24px; color: #f39c12;">{{ stats.action_distribution.MODIFY || 0 }}</div>
            <div>修改</div>
          </div>
        </el-col>
      </el-row>
    </div>

    <!-- 审核人贡献榜 -->
    <div class="kg-card" v-if="stats.operator_distribution?.length">
      <h3 style="margin-bottom: 16px;">审核人贡献榜</h3>
      <el-table :data="stats.operator_distribution" stripe style="width: 100%">
        <el-table-column prop="operator" label="审核人" />
        <el-table-column prop="count" label="审核数" width="120" />
      </el-table>
    </div>

    <!-- 历史记录 -->
    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">审核日志</h3>
      <el-form :inline="true" style="margin-bottom: 12px;">
        <el-form-item label="审核人">
          <el-input v-model="filter.operator" clearable placeholder="按审核人过滤" style="width: 150px;" />
        </el-form-item>
        <el-form-item label="操作">
          <el-select v-model="filter.action" clearable placeholder="全部" style="width: 120px;">
            <el-option label="通过" value="PASS" />
            <el-option label="拒绝" value="REJECT" />
            <el-option label="修改" value="MODIFY" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-select v-model="filter.days" style="width: 120px;">
            <el-option label="最近七天" value="7" />
            <el-option label="最近30天" value="30" />
            <el-option label="最近90天" value="90" />
            <el-option label="最近一年" value="365" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadHistory">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="history" stripe style="width: 100%" max-height="500">
        <el-table-column prop="action" label="操作" width="80">
          <template #default="{ row }">
            <el-tag :type="actionType(row.action)" size="small">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="operator" label="审核人" width="100" />
        <el-table-column label="修改前" min-width="200">
          <template #default="{ row }">
            <span v-if="row.old_data">
              {{ row.old_data.subject }} → {{ row.old_data.predicate }} → {{ row.old_data.object }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="修改后" min-width="200">
          <template #default="{ row }">
            <span v-if="row.new_data">
              {{ row.new_data.subject }} → {{ row.new_data.predicate }} → {{ row.new_data.object }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="timestamp" label="时间" width="180">
          <template #default="{ row }">{{ formatDate(row.timestamp) }}</template>
        </el-table-column>
      </el-table>

      <div style="margin-top: 16px; text-align: right;">
        <el-pagination
          v-model:current-page="page"
          :page-size="20"
          :total="total"
          layout="prev, pager, next"
          @current-change="loadHistory"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const route = useRoute()
const projectId = route.params.id
const stats = ref({})
const history = ref([])
const total = ref(0)
const page = ref(1)
const filter = reactive({ operator: '', action: '', days: 30 })
const syncing = ref(false)

onMounted(async () => {
  await Promise.all([loadStats(), loadHistory()])
})

async function loadAll() {
  await Promise.all([loadStats(), loadHistory()])
}

async function syncToGraph() {
  syncing.value = true
  try {
    const res = await api.post(`/fusion/auto-fuse-passed/${projectId}`)
    ElMessage.success(`同步成功: ${res.fused_count || 0} 条三元组已加入图谱`)
  } catch (e) {
    ElMessage.error('同步失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    syncing.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await api.get(`/review/${projectId}/stats?days=${filter.days}`)
  } catch (e) {
    ElMessage.error('加载统计失败')
  }
}

async function loadHistory() {
  try {
    const params = new URLSearchParams({
      days: filter.days,
      page: page.value,
      page_size: 20,
    })
    if (filter.operator) params.append('operator', filter.operator)
    if (filter.action) params.append('action', filter.action)
    const res = await api.get(`/review/${projectId}/history?${params}`)
    history.value = res.records || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error('加载历史失败')
  }
}

function actionType(a) {
  return { PASS: 'success', REJECT: 'danger', MODIFY: 'warning' }[a] || 'info'
}

function formatDate(s) {
  if (!s) return ''
  // 后端返回 ISO 格式带 Z 后缀，这里兼容旧格式：无时区标识的统一补 Z
  let str = String(s)
  if (!str.endsWith('Z') && !str.includes('+') && !str.includes('T') || str.includes(' ') && !str.endsWith('Z') && !str.includes('+')) {
    // 将 'YYYY-MM-DD HH:MM:SS' 转为 'YYYY-MM-DDTHH:MM:SSZ'
    str = str.replace(' ', 'T')
    if (!str.endsWith('Z') && !str.includes('+')) {
      str = str + 'Z'
    }
  }
  const d = new Date(str)
  if (isNaN(d)) return s
  return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}
</script>
