'use strict'

/**
 * NPC 行为状态机。
 *
 * 描述 mineflayer bot 的高层运行状态，供 index.js / listen.js / executor 协作时
 * 统一判断"NPC 现在在干什么"，避免并发行为互相干扰。
 *
 * 状态流转（由上层驱动，本模块为被动状态容器）：
 *
 *   OFFLINE ──spawn──▶ IDLE
 *   IDLE ──收到玩家@──▶ THINKING（等待 core 回复）
 *   THINKING ──core返回──▶ SPEAKING（输出回复文本）
 *   SPEAKING ──有行为树──▶ EXECUTING（执行动作）
 *   SPEAKING ──无行为树──▶ IDLE
 *   EXECUTING ──完成/失败──▶ IDLE
 *   任意在线状态 ──断线──▶ OFFLINE
 *
 * 对齐 core/core/models/models.py 的 NPCState.current_action 语义：
 * 状态机当前状态可映射为该字段（如 current_action="executing"）。
 */

const NPC_STATES = {
  /** 未连接 / 断线重连中 */
  OFFLINE: 'offline',
  /** 在线空闲，等待玩家 @ 提及 */
  IDLE: 'idle',
  /** 已收到玩家消息，正在与 Harness 核心通信（等待回复） */
  THINKING: 'thinking',
  /** 正在向游戏内输出 NPC 回复文本 */
  SPEAKING: 'speaking',
  /** 正在执行行为树动作 */
  EXECUTING: 'executing',
  /** 长期跟随玩家（follow 动作进行中，可被 stop/新行为打断） */
  FOLLOWING: 'following',
}

const STATE_LABELS = {
  offline: '离线',
  idle: '空闲',
  thinking: '思考中',
  speaking: '说话中',
  executing: '执行中',
  following: '跟随中',
}

/** 允许的合法流转（prev -> [next...]），非法流转仅告警不抛错 */
const ALLOWED_TRANSITIONS = {
  offline: ['idle'],
  idle: ['thinking', 'offline', 'following'],
  thinking: ['speaking', 'idle', 'offline'],
  speaking: ['executing', 'idle', 'offline'],
  executing: ['idle', 'offline', 'following'],
  following: ['thinking', 'idle', 'offline', 'executing'],
}

class NPCStateMachine {
  /**
   * @param {object} [options]
   * @param {function} [options.onStateChange]  (prevState, nextState, reason) => void
   * @param {object}   [options.logger]         日志对象，默认 console
   * @param {string}   [options.initialState]   初始状态，默认 offline
   */
  constructor(options = {}) {
    this.logger = options.logger || console
    this.onStateChange = options.onStateChange || (() => {})
    this._state = options.initialState || NPC_STATES.OFFLINE
    this._history = [] // [{state, reason, at}]
    this._record(this._state, 'init')
  }

  /** 当前状态（枚举值） */
  get state() {
    return this._state
  }

  /** 当前状态中文标签 */
  get label() {
    return STATE_LABELS[this._state] || this._state
  }

  /** 是否处于某个状态（支持传入多个，任一命中即可） */
  is(...states) {
    return states.includes(this._state)
  }

  /** 是否处于"可响应玩家"的在线状态 */
  isOnline() {
    return this._state !== NPC_STATES.OFFLINE
  }

  /** 最近 N 条状态流转记录（调试用） */
  history(n = 10) {
    return this._history.slice(-n)
  }

  /**
   * 状态流转
   * @param {string} next   目标状态（NPC_STATES 枚举值）
   * @param {string} [reason]  流转原因（日志/调试）
   * @returns {boolean} 是否发生了流转（同状态返回 false）
   */
  transition(next, reason = '') {
    const prev = this._state
    if (prev === next) return false

    const allowed = ALLOWED_TRANSITIONS[prev] || []
    if (!allowed.includes(next)) {
      this.logger.warn(
        `[state] 非法流转 ${STATE_LABELS[prev] || prev} → ${STATE_LABELS[next] || next}（${reason}），已忽略`,
      )
      return false
    }

    this._state = next
    this._record(next, reason)
    this.logger.log(
      `[state] ${STATE_LABELS[prev] || prev} → ${STATE_LABELS[next] || next}${reason ? `（${reason}）` : ''}`,
    )
    this.onStateChange(prev, next, reason)
    return true
  }

  /** 重置为指定状态（用于断线重连等强制场景，绕过流转校验） */
  reset(next, reason = 'reset') {
    const prev = this._state
    this._state = next
    this._record(next, reason)
    this.logger.log(
      `[state] ${STATE_LABELS[prev] || prev} → ${STATE_LABELS[next] || next}（强制${reason}）`,
    )
    this.onStateChange(prev, next, reason)
  }

  _record(state, reason) {
    this._history.push({ state, reason, at: new Date().toISOString() })
  }
}

module.exports = { NPCStateMachine, NPC_STATES, STATE_LABELS }
