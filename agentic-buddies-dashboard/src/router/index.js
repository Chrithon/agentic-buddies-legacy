import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

// 路由与后端 API 模块一一对应（见 agentic-buddies-backend/main.py）
const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('../layout/AppLayout.vue'),
    redirect: '/npcs',
    children: [
      {
        // 对应 /api/npcs
        path: 'npcs',
        name: 'npcs',
        component: () => import('../views/NpcListView.vue'),
        meta: { title: 'NPC 管理' },
      },
      {
        path: 'npcs/:id',
        name: 'npc-detail',
        component: () => import('../views/NpcDetailView.vue'),
        meta: { title: 'NPC 详情' },
      },
      {
        // 对应 /api/worlds
        path: 'worlds',
        name: 'worlds',
        component: () => import('../views/WorldListView.vue'),
        meta: { title: '世界观管理' },
      },
      {
        // 对应 /api/behavior-trees
        path: 'behavior-trees',
        name: 'behavior-trees',
        component: () => import('../views/BehaviorTreeListView.vue'),
        meta: { title: '行为树管理' },
      },
      {
        // 对应 /api/llm-providers
        path: 'llm-providers',
        name: 'llm-providers',
        component: () => import('../views/LlmProviderListView.vue'),
        meta: { title: 'LLM 提供商' },
      },
      {
        // 对应 /api/mcp
        path: 'mcp',
        name: 'mcp',
        component: () => import('../views/McpListView.vue'),
        meta: { title: 'MCP 服务' },
      },
      {
        // 对应 /api/word-list
        path: 'word-list',
        name: 'word-list',
        component: () => import('../views/WordListView.vue'),
        meta: { title: '敏感词表' },
      },
      {
        // 对应 /api/logs
        path: 'logs',
        name: 'logs',
        component: () => import('../views/ChatLogListView.vue'),
        meta: { title: '对话日志' },
      },
      {
        // 对应 /api/users，仅管理员可见/可访问
        path: 'users',
        name: 'users',
        component: () => import('../views/UserListView.vue'),
        meta: { title: '用户管理', admin: true },
      },
      {
        // 对应 /api/block-policies
        path: 'block-policies',
        name: 'block-policies',
        component: () => import('../views/BlockPolicyListView.vue'),
        meta: { title: '拦截策略' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('../views/NotFoundView.vue'),
    meta: { public: true, title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 登录守卫：非公开页面且无 token 时跳转登录页；admin 页面校验角色
router.beforeEach(async (to) => {
  document.title = to.meta.title
    ? `${to.meta.title} - Agentic Buddies`
    : 'Agentic Buddies Dashboard'

  const authStore = useAuthStore()

  // token 已过期：主动登出并跳登录页（避免带着废 token 发请求）
  if (authStore.isLoggedIn && authStore.isTokenExpired) {
    authStore.expireSession()
    return to.meta.public
      ? { name: 'login' }
      : { name: 'login', query: { redirect: to.fullPath } }
  }

  if (!to.meta.public && !authStore.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && authStore.isLoggedIn) {
    return { name: 'npcs' }
  }

  // 刷新页面后 user 为空，先从 token 恢复用户信息；失败（401 等）则跳登录
  if (authStore.isLoggedIn && !authStore.user) {
    try {
      await authStore.fetchMe()
    } catch {
      authStore.expireSession()
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }

  // 管理员页面守卫
  if (to.meta.admin && !authStore.user?.is_admin) {
    return { name: 'npcs' }
  }
})

export default router
