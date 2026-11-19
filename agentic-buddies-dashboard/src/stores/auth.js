import { defineStore } from 'pinia'
import { authApi } from '../api'

/**
 * 解析 JWT payload（不校验签名，仅用于读取 exp 做前端预判）。
 * 解析失败返回 null。
 */
function parseJwtPayload(token) {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64))
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('access_token') || '',
    user: null,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    /** token 是否已过期（依据 JWT exp 前端预判，提前 30 秒视为过期） */
    isTokenExpired: (state) => {
      if (!state.token) return true
      const payload = parseJwtPayload(state.token)
      if (!payload?.exp) return true
      return payload.exp * 1000 <= Date.now() + 30 * 1000
    },
  },
  actions: {
    async login(username, password) {
      const data = await authApi.login(username, password)
      this.token = data.access_token
      this.user = data.user || null
      localStorage.setItem('access_token', this.token)
    },
    async fetchMe() {
      this.user = await authApi.me()
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('access_token')
    },
    /** 会话失效（过期或 401）：登出并标记原因，供登录页提示 */
    expireSession() {
      this.logout()
      sessionStorage.setItem('auth_expired', '1')
    },
  },
})
