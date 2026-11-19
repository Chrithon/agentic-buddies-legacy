/**
 * 与后端路由一一对应的 API 模块（见 agentic-buddies-backend/main.py）。
 */
import { http } from './request'

// ---------- /api/auth ----------
export const authApi = {
  login: (username, password) => http.post('/auth/login', { username, password }),
  me: () => http.get('/auth/me'),
  // 本人修改密码：{ old_password, new_password, confirm_password }
  changePassword: (data) => http.post('/auth/password', data),
}

// ---------- /api/npcs ----------
export const npcApi = {
  list: (params) => http.get('/npcs/', params),
  create: (data) => http.post('/npcs/', data),
  detail: (id) => http.get(`/npcs/${id}`),
  update: (id, data) => http.put(`/npcs/${id}`, data),
  remove: (id) => http.delete(`/npcs/${id}`),
  // NPC 与 MCP 绑定关系
  listMcp: (id) => http.get(`/npcs/${id}/mcp`),
  bindMcp: (id, mcpId) => http.post(`/npcs/${id}/mcp`, { mcp_id: mcpId }),
  unbindMcp: (id, mcpId) => http.delete(`/npcs/${id}/mcp/${mcpId}`),
  // NPC 与行为树绑定关系
  listBehaviorTrees: (id) => http.get(`/npcs/${id}/behavior-trees`),
  bindBehaviorTree: (id, treeId) =>
    http.post(`/npcs/${id}/behavior-trees`, { behavior_tree_id: treeId }),
  unbindBehaviorTree: (id, treeId) => http.delete(`/npcs/${id}/behavior-trees/${treeId}`),
}

// ---------- /api/worlds ----------
export const worldApi = {
  list: () => http.get('/worlds/'),
  create: (data) => http.post('/worlds/', data),
  detail: (id) => http.get(`/worlds/${id}`),
  update: (id, data) => http.put(`/worlds/${id}`, data),
  remove: (id) => http.delete(`/worlds/${id}`),
}

// ---------- /api/behavior-trees ----------
export const behaviorTreeApi = {
  list: () => http.get('/behavior-trees/'),
  create: (data) => http.post('/behavior-trees/', data),
  detail: (id) => http.get(`/behavior-trees/${id}`),
  update: (id, data) => http.put(`/behavior-trees/${id}`, data),
  remove: (id) => http.delete(`/behavior-trees/${id}`),
}

// ---------- /api/llm-providers ----------
export const llmProviderApi = {
  list: () => http.get('/llm-providers/'),
  create: (data) => http.post('/llm-providers/', data),
  detail: (id) => http.get(`/llm-providers/${id}`),
  update: (id, data) => http.put(`/llm-providers/${id}`, data),
  remove: (id) => http.delete(`/llm-providers/${id}`),
  // 从提供商 OpenAI 兼容接口拉取模型列表
  fetchModels: (baseUrl, apiKey) =>
    http.post('/llm-providers/fetch-models', { base_url: baseUrl, api_key: apiKey || null }),
}

// ---------- /api/mcp ----------
export const mcpApi = {
  list: (params) => http.get('/mcp/', params),
  create: (data) => http.post('/mcp/', data),
  detail: (id) => http.get(`/mcp/${id}`),
  update: (id, data) => http.put(`/mcp/${id}`, data),
  remove: (id) => http.delete(`/mcp/${id}`),
  referencedNpcs: (id) => http.get(`/mcp/${id}/npcs`),
}

// ---------- /api/word-list ----------
export const wordListApi = {
  list: (params) => http.get('/word-list/', params),
  create: (data) => http.post('/word-list/', data),
  detail: (id) => http.get(`/word-list/${id}`),
  update: (id, data) => http.put(`/word-list/${id}`, data),
  remove: (id) => http.delete(`/word-list/${id}`),
}

// ---------- /api/logs ----------
export const chatLogApi = {
  list: (params) => http.get('/logs/', params),
  detail: (id) => http.get(`/logs/${id}`),
}

// ---------- /api/users（仅管理员） ----------
export const userApi = {
  list: () => http.get('/users/'),
  create: (data) => http.post('/users/', data),
  update: (id, data) => http.put(`/users/${id}`, data),
  // 重置为 conf.yaml 中配置的默认密码（无需传参）
  resetPassword: (id) => http.put(`/users/${id}/password`),
  unlock: (id) => http.post(`/users/${id}/unlock`),
  remove: (id) => http.delete(`/users/${id}`),
}

// ---------- /api/block-policies ----------
export const blockPolicyApi = {
  list: (params) => http.get('/block-policies/', params),
  create: (data) => http.post('/block-policies/', data),
  detail: (id) => http.get(`/block-policies/${id}`),
  update: (id, data) => http.put(`/block-policies/${id}`, data),
  remove: (id) => http.delete(`/block-policies/${id}`),
}
