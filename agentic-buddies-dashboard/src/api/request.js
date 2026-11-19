/**
 * 基于 axios 的统一 HTTP 请求封装。
 * - baseURL 为 /api，开发环境由 vite proxy 转发到后端（见 vite.config.js）
 * - 请求拦截器：自动携带 Authorization Bearer token
 * - 响应拦截器：401 清除 token 并跳转登录页；统一提取后端 detail 错误信息
 */
import axios from 'axios'

const service = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

// ---------- 请求拦截器 ----------
service.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    // 前置检查：token 已过期则不发出请求，直接跳登录
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      if (payload.exp && payload.exp * 1000 <= Date.now()) {
        localStorage.removeItem('access_token')
        sessionStorage.setItem('auth_expired', '1')
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
        return Promise.reject(new Error('登录已过期，请重新登录'))
      }
    } catch {
      // JWT 格式异常，静默放行由后端判断
    }
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ---------- 响应拦截器 ----------
service.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const { response } = error

    if (response?.status === 401) {
      // 登录接口本身的 401（密码错误）不视为会话失效，由登录页自行处理
      const isLoginRequest = error.config?.url?.includes('/auth/login')
      if (!isLoginRequest) {
        localStorage.removeItem('access_token')
        sessionStorage.setItem('auth_expired', '1')
        // 避免在登录页重复跳转
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
      }
    }

    // 后端 FastAPI 错误格式：{ detail: "..." } 或 { detail: [...] }（参数校验错误）
    const detail = response?.data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join('；')
          : error.message || '网络请求失败'

    return Promise.reject(new Error(message))
  }
)

export const http = {
  get: (path, params) => service.get(path, { params }),
  post: (path, data) => service.post(path, data),
  put: (path, data) => service.put(path, data),
  delete: (path) => service.delete(path),
}

export default service
