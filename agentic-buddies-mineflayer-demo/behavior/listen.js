'use strict'

/**
 * 游戏内对话监听器。
 *
 * 监听 mineflayer bot 收到的聊天消息，识别玩家 @ 本 NPC（bot 用户名）的提及，
 * 命中后通过 onMention 回调交给上层（index.js）走 Harness 管线与 agentic-buddies-core 通信。
 *
 * 提及规则：
 * - 支持 @NPC_Test / ＠NPC_Test / NPC_Test（无 @ 前缀也识别），大小写不敏感
 * - 命中后剔除提及前缀，剩余内容作为玩家输入；仅提及无内容 → 空字符串
 * - 未提及本 NPC 的消息一律忽略（避免回应无关聊天）
 */

/** 从聊天消息中提取 @提及内容；未提及返回 null */
function extractMention(message, botUsername) {
  if (!message || !botUsername) return null
  const escaped = botUsername.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const mentionRe = new RegExp(`[@＠]?${escaped}`, 'i')
  const match = mentionRe.exec(message)
  if (!match) return null

  // 提及位于消息开头（标准 @NPC 用法）→ 只取提及之后的内容
  if (match.index === 0 || /^\s*$/.test(message.slice(0, match.index))) {
    return message
      .slice(match.index + match[0].length)
      .replace(/^[\s,，。:：、.!！?？]+/, '')
      .trim()
  }

  // 提及在句中 → 剔除提及及其相邻标点，保留其余内容
  return message
    .replace(new RegExp(`[\\s,，。:：、]*[@＠]?${escaped}[\\s,，。:：、]*`, 'gi'), ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

class ChatListener {
  /**
   * @param {import('mineflayer').Bot} bot
   * @param {object} options
   * @param {function} options.onMention   命中提及时的回调 (username, text)
   * @param {object}   [options.logger]    日志对象，默认 console
   */
  constructor(bot, options = {}) {
    this.bot = bot
    // 显式传入 bot 用户名（连接完成前 bot.username 可能为空）
    this.botUsername = options.botUsername || bot.username || ''
    this.onMention = options.onMention || (() => {})
    this.logger = options.logger || console
    this._handler = this._handler.bind(this)
    this._started = false
  }

  start() {
    if (this._started) return
    this.bot.on('chat', this._handler)
    this._started = true
    this.logger.log(
      `[listen] 开始监听游戏内对话，玩家 @${this.botUsername} 时触发 NPC 响应`,
    )
  }

  stop() {
    if (!this._started) return
    this.bot.removeListener('chat', this._handler)
    this._started = false
    this.logger.log('[listen] 已停止监听')
  }

  _handler(username, message) {
    if (username === this.botUsername) return // 忽略自己的发言

    const text = extractMention(message, this.botUsername)
    if (text === null) return // 未提及本 NPC，忽略

    this.logger.log(
      `[listen] ${username} @了 NPC：${text || '（仅提及，无内容）'}`,
    )
    this.onMention(username, text)
  }
}

module.exports = { ChatListener, extractMention }
