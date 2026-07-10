<template>
  <div>
    <div class="kg-page-header">
      <h2>用户管理</h2>
      <el-button type="primary" @click="showDialog = true">+ 创建用户</el-button>
    </div>

    <div class="kg-card">
      <el-table :data="users" stripe style="width: 100%">
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="role" label="角色" width="120">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'">{{ row.role === 'admin' ? '管理员' : '审核员' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" type="danger" @click="deleteUser(row)" :disabled="row.username === authStore.username">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="showDialog" title="创建用户" width="400px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%;">
            <el-option label="审核员" value="reviewer" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="createUser">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { userApi } from '../api'
import { useAuthStore } from '../stores'

const authStore = useAuthStore()
const users = ref([])
const showDialog = ref(false)
const form = reactive({ username: '', password: '', role: 'reviewer' })

onMounted(async () => {
  await loadUsers()
})

async function loadUsers() {
  try {
    users.value = await userApi.list()
  } catch (e) {
    ElMessage.error('加载失败')
  }
}

async function createUser() {
  if (!form.username || !form.password) {
    ElMessage.warning('请填写完整信息')
    return
  }
  try {
    await userApi.create(form)
    ElMessage.success('创建成功')
    showDialog.value = false
    form.username = ''
    form.password = ''
    form.role = 'reviewer'
    await loadUsers()
  } catch (e) {
    ElMessage.error('创建失败')
  }
}

async function deleteUser(row) {
  try {
    await ElMessageBox.confirm(`确认删除用户 ${row.username}?`, '确认', { type: 'warning' })
    await userApi.delete(row.id)
    ElMessage.success('删除成功')
    await loadUsers()
  } catch (e) {
    // 取消或失败
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
