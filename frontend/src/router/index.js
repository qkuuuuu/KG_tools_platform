import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore, useProjectStore } from '../stores'
import { projectApi } from '../api'

const routes = [
  { path: '/', redirect: '/projects' },
  { path: '/projects', name: 'Projects', component: () => import('../views/Projects.vue') },
  { path: '/project/:id/dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/project/:id/config', name: 'Config', component: () => import('../views/Config.vue') },
  { path: '/project/:id/extract', name: 'Extract', component: () => import('../views/Extract.vue') },
  { path: '/project/:id/passed-triples', name: 'PassedTriples', component: () => import('../views/PassedTriples.vue') },
  { path: '/project/:id/hitl', name: 'HITL', component: () => import('../views/HITL.vue') },
  { path: '/project/:id/export', name: 'Export', component: () => import('../views/Export.vue') },
  { path: '/project/:id/fuse', redirect: to => `/fusion` },
  { path: '/fusion', name: 'Fusion', component: () => import('../views/Fuse.vue') },
  { path: '/project/:id/assistant', name: 'Assistant', component: () => import('../views/Assistant.vue') },
  { path: '/project/:id/graph', name: 'Graph', component: () => import('../views/Graph.vue') },
  { path: '/project/:id/search', name: 'Search', component: () => import('../views/Search.vue') },
  { path: '/project/:id/review-history', name: 'ReviewHistory', component: () => import('../views/ReviewHistory.vue') },
  { path: '/multi-graph', name: 'MultiGraph', component: () => import('../views/MultiGraph.vue') },
  { path: '/users', name: 'Users', component: () => import('../views/Users.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, from, next) => {
  const auth = useAuthStore()
  // 未登录时，App.vue 会显示 Login 组件，路由直接放行即可
  if (!auth.token) {
    next()
    return
  }

  // 项目路由：验证项目是否存在
  if (to.path.startsWith('/project/')) {
    const projectId = to.params.id
    const projectStore = useProjectStore()

    // 页面刷新时 store 可能未初始化，从 localStorage 恢复
    if (!projectStore.current) {
      projectStore.init()
    }

    // store 中有且 ID 匹配，直接放行
    if (projectStore.current && String(projectStore.current.id) === String(projectId)) {
      next()
      return
    }

    // 尝试从后端获取项目信息
    try {
      const project = await projectApi.get(projectId)
      projectStore.setCurrent(project)
      next()
    } catch (e) {
      // 项目不存在，重定向到项目列表
      next('/projects')
    }
    return
  }

  next()
})

export default router
