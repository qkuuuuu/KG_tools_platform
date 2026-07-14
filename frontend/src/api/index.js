import axios from 'axios'
import { useAuthStore } from '../stores'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
})

api.interceptors.request.use(config => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

api.interceptors.response.use(
  res => res.data,
  err => {
    if (err.response?.status === 401) {
      const auth = useAuthStore()
      auth.logout()
    }
    return Promise.reject(err)
  }
)

// ==================== 认证 ====================
export const authApi = {
  login: (username, password) => api.post('/auth/login', { username, password }),
  register: (data) => api.post('/auth/register', data),
}

// ==================== 用户 ====================
export const userApi = {
  list: () => api.get('/users/'),
  create: (data) => api.post('/users/', data),
  delete: (id) => api.delete(`/users/${id}`),
}

// ==================== 项目 ====================
export const projectApi = {
  list: () => api.get('/projects/'),
  create: (data) => api.post('/projects/', data),
  get: (id) => api.get(`/projects/${id}`),
  update: (id, data) => api.put(`/projects/${id}`, data),
  delete: (id) => api.delete(`/projects/${id}`),
}

// ==================== LLM 配置 ====================
export const llmConfigApi = {
  list: (projectId) => api.get(`/projects/${projectId}/llm-configs`),
  update: (projectId, configs) => api.put(`/projects/${projectId}/llm-configs`, configs),
  defaultPrompts: (projectId) => api.get(`/projects/${projectId}/llm-config-default-prompts`),
}

// ==================== 设备配置 ====================
export const deviceConfigApi = {
  list: (projectId) => api.get(`/projects/${projectId}/device-configs`),
  update: (projectId, configs) => api.put(`/projects/${projectId}/device-configs`, configs),
}

// ==================== Schema ====================
export const schemaApi = {
  list: (projectId) => api.get(`/projects/${projectId}/schemas`),
  update: (projectId, schemas) => api.put(`/projects/${projectId}/schemas`, schemas),
  deleteAll: (projectId) => api.delete(`/projects/${projectId}/schemas`),
  previewDsl: (projectId, dsl) => api.post(`/projects/${projectId}/schemas/preview-dsl`, { dsl }),
  importDsl: (projectId, dsl) => api.post(`/projects/${projectId}/schemas/import-dsl`, { dsl }),
}

// ==================== 文档 ====================
export const docApi = {
  list: (projectId) => api.get('/data/documents', { params: { project_id: projectId } }).then(res => res.items || res),
  upload: (formData, onProgress) => api.post('/data/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
  }),
  getTask: (taskId) => api.get(`/data/tasks/${taskId}`),
  getDoc: (docId) => api.get(`/data/documents/${docId}`),
  getDocContent: (docId) => api.get(`/data/documents/${docId}/content`),
  delete: (docId) => api.delete(`/data/documents/${docId}`),
}

// ==================== 抽取 ====================
export const extractApi = {
  engines: () => api.get('/data/engines'),
  extract: (docId, method, schemaIds, scriptId, customPrompt) => {
    const formData = new FormData()
    formData.append('doc_id', docId)
    formData.append('extraction_method', method)
    formData.append('schema_ids', schemaIds?.join(',') || '')
    if (scriptId) formData.append('script_id', scriptId)
    if (customPrompt) formData.append('custom_prompt', customPrompt)
    return api.post('/data/extract', formData)
  },
  qualityCheck: (docId, threshold, benchmarkFile, customPrompt) => {
    const formData = new FormData()
    formData.append('doc_id', docId)
    if (threshold !== undefined) formData.append('threshold', String(threshold))
    if (benchmarkFile) formData.append('benchmark_file', benchmarkFile)
    if (customPrompt) formData.append('custom_prompt', customPrompt)
    return api.post('/data/quality-check', formData)
  },
  disambiguate: (tripleIds, customPrompt) =>
    api.post('/data/disambiguate', { triple_ids: tripleIds, custom_prompt: customPrompt || '' }),
  getTriples: (projectId, status, limit, taskId) => {
    let url = `/data/triples/${projectId}`
    const params = []
    if (status) params.push(`status=${status}`)
    if (limit) params.push(`limit=${limit}`)
    if (taskId) params.push(`task_id=${taskId}`)
    if (params.length) url += '?' + params.join('&')
    return api.get(url)
  },
  getTripleStats: (projectId) => api.get(`/data/triples/${projectId}/stats`),
  deleteTask: (taskId) => api.delete(`/data/extract-tasks/${taskId}`),
  deleteQualityTask: (taskId) => api.delete(`/data/quality-tasks/${taskId}`),
  deleteTriple: (tripleId) => api.delete(`/data/triples/${tripleId}`),
}

// ==================== 自定义脚本 ====================
export const scriptApi = {
  upload: (file, description, onProgress) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('description', description || '')
    return api.post('/data/upload-script', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    })
  },
  list: () => api.get('/data/scripts'),
  delete: (scriptId) => api.delete(`/data/scripts/${scriptId}`),
}

// ==================== HITL ====================
export const hitlApi = {
  pending: (projectId, page = 1, pageSize = 20, ambiguousOnly = false) =>
    api.get(`/hitl/pending/${projectId}?page=${page}&page_size=${pageSize}${ambiguousOnly ? '&ambiguous_only=true' : ''}`),
  reviewed: (projectId, params) => api.get(`/hitl/reviewed/${projectId}?${params}`),
  assigned: (username) => api.get(`/hitl/assigned/${username}`),
  assign: (tripleId, username) => api.post('/hitl/assign', null, { params: { triple_id: tripleId, username } }),
  review: (data) => api.post('/hitl/review', data),
  revoke: (tripleId) => api.post(`/hitl/revoke/${tripleId}`),
  delete: (tripleId) => api.delete(`/hitl/triples/${tripleId}`),
  stats: (projectId) => api.get(`/hitl/stats/${projectId}`),
}

// ==================== 已通过三元组 ====================
export const passedTriplesApi = {
  stats: (projectId) => api.get(`/data/passed-triples/${projectId}/stats`),
  list: (projectId, params) => api.get(`/data/passed-triples/${projectId}`, { params }),
  syncNeo4j: (projectId) => api.post(`/data/passed-triples/${projectId}/sync-neo4j`),
}

// ==================== 融合 ====================
export const fusionApi = {
  suggestions: (projectId, method = 'hybrid') => api.get(`/fusion/suggestions/${projectId}?method=${method}`),
  llmDisambiguate: (projectId) => api.post(`/fusion/llm-disambiguate/${projectId}`),
  tripleDedup: (projectId) => api.post(`/fusion/triple-dedup/${projectId}`),
  merge: (entity1Name, entity2Name, standardName, projectId) =>
    api.post('/fusion/merge', null, { params: { entity_1_name: entity1Name, entity_2_name: entity2Name, standard_name: standardName, project_id: projectId } }),
  autoFuse: (projectId) => api.post(`/fusion/auto-fuse-passed/${projectId}`),
  autoFuseMulti: (projectIds) => api.post('/fusion/auto-fuse-multi', { project_ids: projectIds }),
  neo4jGraph: (limit) => api.get(`/fusion/neo4j-graph?limit=${limit || 500}`),
  neo4jClear: () => api.post('/fusion/neo4j-clear'),
  neo4jSyncMulti: (body) => api.post('/fusion/neo4j-sync-multi', body),
  neo4jSyncMerged: (body) => api.post('/fusion/neo4j-sync-merged', body),
}

// ==================== 导出 ====================
export const exportApi = {
  export: (projectId, format) => api.get(`/export/${projectId}?format=${format}`, { responseType: 'blob' }),
  neo4jSync: (projectId) => api.post(`/export/${projectId}/neo4j-sync`),
  importTtl: (projectId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post(`/export/${projectId}/import-ttl`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  graphData: (projectId) => api.get(`/export/${projectId}/graph-data`),
}

export default api

// ==================== 智能助手 ====================
export const assistantApi = {
  chat: (projectId, data) => api.post(`/assistant/${projectId}/chat`, data),
  suggestedQuestions: (projectId) => api.get(`/assistant/${projectId}/suggested-questions`),
  // 会话管理
  listSessions: (projectId) => api.get(`/assistant/${projectId}/sessions`),
  createSession: (projectId, title) => api.post(`/assistant/${projectId}/sessions`, { title }),
  updateSession: (projectId, sessionId, title) => api.put(`/assistant/${projectId}/sessions/${sessionId}`, { title }),
  deleteSession: (projectId, sessionId) => api.delete(`/assistant/${projectId}/sessions/${sessionId}`),
  listMessages: (projectId, sessionId) => api.get(`/assistant/${projectId}/sessions/${sessionId}/messages`),
}
