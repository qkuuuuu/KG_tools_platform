<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push(`/project/${$route.params.id}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>三元组搜索</h2>
    </div>

    <div class="kg-card">
      <el-form :inline="true" @submit.prevent="doSearch">
        <el-form-item label="关键词">
          <el-input v-model="form.q" placeholder="输入关键词..." clearable style="width: 250px;" />
        </el-form-item>
        <el-form-item label="搜索字段">
          <el-select v-model="form.field" style="width: 120px;">
            <el-option label="全部" value="all" />
            <el-option label="主体" value="subject" />
            <el-option label="关系" value="predicate" />
            <el-option label="客体" value="object" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" clearable placeholder="全部" style="width: 120px;">
            <el-option label="待审核" value="PENDING" />
            <el-option label="已通过" value="PASSED" />
            <el-option label="已拒绝" value="REJECTED" />
            <el-option label="已融合" value="FUSED" />
          </el-select>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="form.confidenceRange" range :min="0" :max="100" style="width: 200px;" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="doSearch" :loading="loading">搜索</el-button>
          <el-button @click="resetForm">重置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="results.length" class="kg-card">
      <h3 style="margin-bottom: 12px;">搜索结果: {{ total }} 条</h3>
      <el-table :data="results" stripe style="width: 100%" max-height="600">
        <el-table-column prop="subject" label="主体" min-width="150">
          <template #default="{ row }">
            <span v-html="highlight(row.subject, form.q)"></span>
          </template>
        </el-table-column>
        <el-table-column prop="predicate" label="关系" width="150">
          <template #default="{ row }">
            <span v-html="highlight(row.predicate, form.q)"></span>
          </template>
        </el-table-column>
        <el-table-column prop="object" label="客体" min-width="150">
          <template #default="{ row }">
            <span v-html="highlight(row.object, form.q)"></span>
          </template>
        </el-table-column>
        <el-table-column prop="confidence" label="置信度" width="90">
          <template #default="{ row }">
            <el-tag :type="confType(row.confidence)" size="small">{{ row.confidence?.toFixed(0) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="method" label="方法" width="100" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top: 16px; text-align: right;">
        <el-pagination
          v-model:current-page="page"
          :page-size="20"
          :total="total"
          layout="prev, pager, next"
          @current-change="doSearch"
        />
      </div>
    </div>
    <div v-else-if="searched" class="kg-card" style="text-align: center; padding: 40px; color: #95a5a6;">
      未找到匹配的三元组
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const route = useRoute()
const projectId = route.params.id
const form = reactive({
  q: '',
  field: 'all',
  status: '',
  confidenceRange: [0, 100],
})
const results = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const searched = ref(false)

async function doSearch() {
  if (!form.q.trim()) {
    ElMessage.warning('请输入关键词')
    return
  }
  loading.value = true
  searched.value = true
  try {
    const params = new URLSearchParams({
      q: form.q,
      field: form.field,
      min_confidence: form.confidenceRange[0],
      max_confidence: form.confidenceRange[1],
      page: page.value,
      page_size: 20,
    })
    if (form.status) params.append('status', form.status)
    const res = await api.get(`/search/${projectId}/triples-search?${params}`)
    results.value = res.results || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error('搜索失败')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.q = ''
  form.field = 'all'
  form.status = ''
  form.confidenceRange = [0, 100]
  results.value = []
  total.value = 0
  searched.value = false
}

function highlight(text, keyword) {
  if (!text || !keyword) return text
  const regex = new RegExp(`(${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return text.replace(regex, '<mark style="background: #fff3cd; padding: 0 2px;">$1</mark>')
}

function confType(c) {
  if (!c) return 'info'
  if (c >= 90) return 'success'
  if (c >= 80) return 'warning'
  return 'danger'
}

function statusType(s) {
  const map = { PASSED: 'success', PENDING: 'warning', REJECTED: 'danger', FUSED: 'info' }
  return map[s] || 'info'
}
</script>
