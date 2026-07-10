<template>
  <div>
    <div class="kg-page-header">
      <h2>项目大厅</h2>
      <el-button type="primary" @click="showDialog = true">+ 新建项目</el-button>
    </div>

    <div class="kg-project-grid">
      <div v-for="p in projects" :key="p.id" class="kg-project-card" @click="enterProject(p)">
        <h3 style="margin-bottom: 8px;">{{ p.name }}</h3>
        <p style="color: #95a5a6; font-size: 13px;">{{ p.description || '暂无描述' }}</p>
        <p style="color: #bdc3c7; font-size: 12px; margin-top: 12px;">创建于 {{ formatDate(p.created_at) }}</p>
        <el-button
          type="danger"
          size="small"
          text
          @click.stop="deleteProject(p)"
          style="position: absolute; top: 12px; right: 12px;"
        >删除</el-button>
      </div>
    </div>

    <el-dialog v-model="showDialog" title="新建项目" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="项目名称">
          <el-input v-model="form.name" placeholder="如：医疗研报知识图谱" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="createProject">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi } from '../api'
import { useProjectStore } from '../stores'

const router = useRouter()
const projectStore = useProjectStore()
const projects = ref([])
const showDialog = ref(false)
const form = reactive({ name: '', description: '' })

onMounted(async () => {
  await loadProjects()
})

async function loadProjects() {
  try {
    projects.value = await projectApi.list()
  } catch (e) {
    ElMessage.error('加载项目失败')
  }
}

function enterProject(p) {
  projectStore.setCurrent(p)
  router.push(`/project/${p.id}/dashboard`)
}

async function createProject() {
  if (!form.name) {
    ElMessage.warning('请输入项目名称')
    return
  }
  try {
    const created = await projectApi.create(form)
    ElMessage.success('创建成功')
    showDialog.value = false
    form.name = ''
    form.description = ''
    await loadProjects()
  } catch (e) {
    ElMessage.error('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteProject(p) {
  try {
    await ElMessageBox.confirm(
      `确认删除项目「${p.name}」？\n\n该项目下的所有文档、三元组、审核记录、图谱数据将被永久删除，此操作不可撤销。`,
      '删除项目',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' }
    )
    await projectApi.delete(p.id)
    ElMessage.success(`项目「${p.name}」已删除`)
    // 如果删除的是当前项目，清理 store
    if (projectStore.current && projectStore.current.id === p.id) {
      projectStore.clear()
    }
    await loadProjects()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  }
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
