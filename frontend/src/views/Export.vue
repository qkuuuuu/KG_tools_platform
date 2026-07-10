<template>
  <div>
    <div class="kg-page-header">
      <el-button size="small" @click="$router.push(`/project/${$route.params.id}/dashboard`)" style="margin-right: 12px;">&larr; 返回</el-button>
      <h2>资产导出 - {{ project?.name }}</h2>
    </div>

    <!-- 导出 -->
    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">三元组导出</h3>
      <p style="color: #95a5a6; margin-bottom: 16px;">导出当前项目的所有三元组数据，支持多种格式。</p>
      <div style="display: flex; gap: 12px; flex-wrap: wrap;">
        <el-button @click="doExport('csv')">CSV</el-button>
        <el-button @click="doExport('json')">JSON</el-button>
        <el-button @click="doExport('jsonld')">JSON-LD</el-button>
        <el-button @click="doExport('cypher')">Cypher脚本</el-button>
      </div>
    </div>

    <!-- 图谱可视化入口 -->
    <div class="kg-card">
      <h3 style="margin-bottom: 16px;">图谱可视化</h3>
      <el-button type="success" @click="$router.push(`/project/${projectId}/graph`)">
        查看知识图谱
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { exportApi } from '../api'
import { useProjectStore } from '../stores'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const project = computed(() => projectStore.current)
const projectId = route.params.id

async function doExport(format) {
  try {
    const res = await exportApi.export(projectId, format)
    const blob = new Blob([res], { type: 'application/octet-stream' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const ext = { csv: 'csv', json: 'json', jsonld: 'jsonld', cypher: 'cypher' }[format]
    a.download = `kg_export.${ext}`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败: ' + (e.response?.data?.detail || e.message))
  }
}
</script>
