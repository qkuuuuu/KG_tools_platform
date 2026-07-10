<template>
  <div v-if="isLogin" class="kg-layout">
    <!-- 侧边栏 -->
    <div class="kg-sidebar">
      <div class="kg-sidebar-logo">知识图谱平台</div>
      <div v-if="currentProject && !isOnProjectsList" style="padding: 0 24px 8px;">
        <el-button size="small" plain @click="goProjectsList" style="width: 100%;">&larr; 返回项目大厅</el-button>
      </div>
      <div class="kg-sidebar-menu">
        <router-link to="/projects">项目大厅</router-link>
        <template v-if="currentProject">
          <router-link :to="`/project/${currentProject.id}/search`">三元组搜索</router-link>
          <router-link :to="`/project/${currentProject.id}/assistant`">智能助手</router-link>
        </template>
        <router-link to="/fusion">融合</router-link>
        <router-link v-if="isAdmin" to="/users">用户管理</router-link>
      </div>
      <div style="padding: 16px 24px; border-top: 1px solid rgba(255,255,255,0.1); font-size: 13px;">
        <div>当前用户: {{ authStore.username }}</div>
        <div v-if="currentProject" style="margin-top: 4px; color: rgba(255,255,255,0.6);">
          当前项目: {{ currentProject.name }}
        </div>
        <div style="margin-top: 8px;">
          <el-button size="small" @click="logout">退出登录</el-button>
        </div>
      </div>
    </div>
    <!-- 主内容 -->
    <div class="kg-main">
      <router-view />
    </div>
  </div>
  <Login v-else />
</template>

<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore, useProjectStore } from './stores'
import Login from './views/Login.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const projectStore = useProjectStore()

const isLogin = computed(() => !!authStore.token)
const isAdmin = computed(() => authStore.role === 'admin')
const currentProject = computed(() => projectStore.current)
const isOnProjectsList = computed(() => {
  return route.path === '/projects' || route.path === '/'
})

function goProjectsList() {
  router.push('/projects')
}

onMounted(() => {
  projectStore.init()
})

function logout() {
  authStore.logout()
  projectStore.clear()
  router.push('/')
}
</script>
