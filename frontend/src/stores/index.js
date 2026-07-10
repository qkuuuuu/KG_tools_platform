import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('kg_token') || '')
  const username = ref(localStorage.getItem('kg_username') || '')
  const role = ref(localStorage.getItem('kg_role') || '')

  const isLoggedIn = computed(() => !!token.value)

  async function login(user, pass) {
    const res = await authApi.login(user, pass)
    token.value = res.access_token
    username.value = res.username
    role.value = res.role
    localStorage.setItem('kg_token', res.access_token)
    localStorage.setItem('kg_username', res.username)
    localStorage.setItem('kg_role', res.role)
  }

  function logout() {
    token.value = ''
    username.value = ''
    role.value = ''
    localStorage.removeItem('kg_token')
    localStorage.removeItem('kg_username')
    localStorage.removeItem('kg_role')
  }

  return { token, username, role, isLoggedIn, login, logout }
})

export const useProjectStore = defineStore('project', () => {
  const current = ref(null)

  function setCurrent(project) {
    current.value = project
    if (project) {
      localStorage.setItem('kg_current_project', JSON.stringify(project))
    } else {
      localStorage.removeItem('kg_current_project')
    }
  }

  function init() {
    const saved = localStorage.getItem('kg_current_project')
    if (saved) {
      current.value = JSON.parse(saved)
    }
  }

  function clear() {
    current.value = null
    localStorage.removeItem('kg_current_project')
  }

  // 由 App.vue 在 onMounted 里调用 init()
  return { current, setCurrent, clear, init }
})

// ==================== 工作流状态（解析/抽取/质检，切换页面不丢失） ====================
export const useWorkflowStore = defineStore('workflow', () => {
  const _key = (projectId) => `kg_workflow_${projectId}`

  function load(projectId) {
    const raw = localStorage.getItem(_key(projectId))
    if (raw) return JSON.parse(raw)
    return {
      currentStep: 1,
      // Step 1
      parseEngine: 'auto',
      // Step 2
      extractMethod: 'LLM_PROMPT',
      // Step 3
      qualityThreshold: 90,
      // 持久化文档+任务ID
      currentDocId: null,
      parseTaskId: null,
      extractTaskId: null,
      qualityTaskId: null,
    }
  }

  function save(projectId, state) {
    localStorage.setItem(_key(projectId), JSON.stringify(state))
  }

  function reset(projectId) {
    localStorage.removeItem(_key(projectId))
  }

  return { load, save, reset }
})

// ==================== LLM 快捷配置（各页面顶部快速切换） ====================
export const useLLMQuickStore = defineStore('llm_quick', () => {
  // 缓存各阶段当前绑定的模型（避免每次切换页面都调接口）
  const cache = ref({})

  function setStage(stage, config) {
    cache.value[stage] = config
  }

  function getStage(stage) {
    return cache.value[stage] || null
  }

  return { cache, setStage, getStage }
})
