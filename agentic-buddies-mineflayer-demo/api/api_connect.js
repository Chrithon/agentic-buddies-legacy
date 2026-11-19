'use strict'

/**
 * agentic-buddies-core（Harness）HTTP 客户端。
 *
 * 对接 core/main.py 的接口：
 *   GET  /health           健康检查
 *   POST /api/chat         玩家输入 → NPC 回复（结构化字段，非原始文本）
 *   GET  /api/npc/{id}/state   NPC 状态查询（可选）
 *
 * core 返回（ChatAPIResponse）：
 *   {
 *     session_uuid: string,      // 会话 ID（新会话时自动生成，需回传保持上下文）
 *     session_new: boolean,
 *     npc_response: string,      // NPC 的说话文本（<speak> 内容）
 *     behavior_tree: string|null,// <behavior> 的 JSON 文本（节点数组），闲聊为 null
 *     latency_ms: number,
 *     flagged: boolean
 *   }
 *
 * 同时提供 parseSpeakBehavior() 兼容解析带 <speak>/<behavior> 标签的原始文本
 * （core 未来版本或 mock 输出可能返回这种格式）。
 */

const DEFAULT_BASE_URL = process.env.CORE_URL || 'http://localhost:8001'
const DEFAULT_CHAT_TIMEOUT_MS = 90_000 // core 内部 60s 超时，客户端留足余量

/** 从含 <speak>/<behavior> 标签的原始文本中解析结构化内容 */
function parseSpeakBehavior(text) {
  if (!text || typeof text !== 'string') {
    return { speak: text ?? '', behavior: null }
  }
  const speakMatch = text.match(/<speak>([\s\S]*?)<\/speak>/)
  const behaviorMatch = text.match(/<behavior>([\s\S]*?)<\/behavior>/)
  return {
    speak: speakMatch ? speakMatch[1].trim() : text.trim(),
    behavior: behaviorMatch ? behaviorMatch[1].trim() : null,
  }
}

/** 将 <behavior> JSON 文本解析为节点数组/对象；解析失败返回 null 并告警 */
function parseBehavior(behaviorText) {
  if (!behaviorText) return null
  try {
    return JSON.parse(behaviorText)
  } catch (error) {
    console.warn('[api_connect] <behavior> 内容不是合法 JSON:', error.message)
    return null
  }
}

class CoreClient {
  /**
   * @param {object} [options]
   * @param {string} [options.baseUrl]  core 服务地址，默认 http://localhost:8001
   * @param {number} [options.chatTimeoutMs]  /api/chat 超时
   */
  constructor(options = {}) {
    this.baseUrl = (options.baseUrl || DEFAULT_BASE_URL).replace(/\/+$/, '')
    this.chatTimeoutMs = options.chatTimeoutMs ?? DEFAULT_CHAT_TIMEOUT_MS
  }

  /** GET /health */
  async health() {
    return this._request('/health')
  }

  /** GET /api/npcs/enabled —— 读取所有已启用的 NPC */
  async getEnabledNpcs() {
    return this._request('/api/npcs/enabled')
  }

  /**
   * POST /api/chat —— 发送玩家输入并获取 NPC 回复
   * @param {object} payload
   * @param {number} payload.npcId
   * @param {string} payload.playerInput
   * @param {string} [payload.sessionUuid]  回传上次的会话 ID 保持上下文；缺省开新会话
   * @param {string} [payload.playerUuid]
   * @returns {Promise<object>} core 的 ChatAPIResponse（含 behavior_tree 文本）
   */
  async chat({ npcId, playerInput, sessionUuid, playerUuid }) {
    return this._request('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        npc_id: npcId,
        player_input: playerInput,
        session_uuid: sessionUuid ?? null,
        player_uuid: playerUuid ?? null,
      }),
    })
  }

  /**
   * 便捷方法：发送消息并返回解析后的行为树（可直接交给 BehaviorExecutor 执行）
   * @returns {Promise<{sessionUuid: string, sessionNew: boolean, speak: string,
   *                    behavior: Array|object|null, latencyMs: number, flagged: boolean}>}
   */
  async chatWithBehavior(payload) {
    const data = await this.chat(payload)
    return {
      sessionUuid: data.session_uuid,
      sessionNew: data.session_new ?? false,
      speak: data.npc_response ?? '',
      behavior: parseBehavior(data.behavior_tree),
      latencyMs: data.latency_ms ?? 0,
      flagged: data.flagged ?? false,
    }
  }

  /** GET /api/npc/{npcId}/state */
  async getNpcState(npcId) {
    return this._request(`/api/npc/${npcId}/state`)
  }

  // -------------------------------------------------------------------------

  async _request(path, options = {}) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.chatTimeoutMs)
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        signal: controller.signal,
      })
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        const detail = body?.detail
        throw new Error(
          `core 接口 ${path} 返回 ${response.status}: ${detail || response.statusText}`,
        )
      }
      return body
    } catch (error) {
      if (error.name === 'AbortError') {
        throw new Error(`core 接口 ${path} 请求超时`)
      }
      throw error
    } finally {
      clearTimeout(timer)
    }
  }
}

// ---------------------------------------------------------------------------
// agentic-buddies-backend 客户端（NPC 数据源）
// ---------------------------------------------------------------------------

const DEFAULT_BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

/**
 * 管理端（agentic-buddies-backend）客户端。
 * 对接 GET /api/npcs/ 读取 NPC 列表（公开接口，无需鉴权）。
 */
class BackendClient {
  /**
   * @param {object} [options]
   * @param {string} [options.baseUrl]  管理端地址，默认 http://localhost:8000
   * @param {number} [options.timeoutMs]
   */
  constructor(options = {}) {
    this.baseUrl = (options.baseUrl || DEFAULT_BACKEND_URL).replace(/\/+$/, '')
    this.timeoutMs = options.timeoutMs ?? 10000
  }

  /** GET /api/npcs/ — 全部 NPC */
  async listNpcs() {
    const data = await this._request('/api/npcs/')
    return Array.isArray(data) ? data : []
  }

  /** 仅返回已启用的 NPC（is_enabled=true） */
  async getEnabledNpcs() {
    const all = await this.listNpcs()
    return all.filter((npc) => npc.is_enabled)
  }

  async _request(path) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.timeoutMs)
    try {
      const response = await fetch(`${this.baseUrl}${path}`, { signal: controller.signal })
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(
          `管理端接口 ${path} 返回 ${response.status}: ${body?.detail || response.statusText}`,
        )
      }
      return body
    } catch (error) {
      if (error.name === 'AbortError') throw new Error(`管理端接口 ${path} 请求超时`)
      throw error
    } finally {
      clearTimeout(timer)
    }
  }
}

module.exports = { CoreClient, BackendClient, parseSpeakBehavior, parseBehavior }
