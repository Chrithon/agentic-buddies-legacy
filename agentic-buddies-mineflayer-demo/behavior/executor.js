'use strict'

/**
 * 行为树执行器 —— 消费 Harness（agentic-buddies-core）输出的 <behavior> JSON，
 * 驱动 mineflayer bot 按节点顺序执行动作 / 判定条件 / 组合节点。
 *
 * 节点格式对齐 core/core/models/models.py 的 BehaviorNode：
 *   {"node_type": "action",    "action_type": "move_to", "action_params": {...}}
 *   {"node_type": "condition", "condition_type": "has_item", "condition_params": {...}}
 *   {"node_type": "sequence",  "children": [...]}
 *   {"node_type": "selector",  "children": [...]}
 *   {"node_type": "parallel",  "children": [...], "parallel_policy": "all_succeed"|"any_succeed"}
 *
 * 顶层也兼容 core 实际输出的 JSON 数组（隐含按 sequence 顺序执行）。
 * 原子动作/条件的实现与元数据见 behavior/actions.js。
 */

const { runAction, runCondition } = require('./actions.js')

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

/** 解析 core 输出的 <behavior> 文本；已解析为对象/数组时原样返回 */
function parseBehavior(input) {
  if (typeof input !== 'string') return input
  let text = input
  const match = text.match(/<behavior>([\s\S]*?)<\/behavior>/)
  if (match) text = match[1]
  text = text.trim()
  if (!text) return null
  return JSON.parse(text)
}

/** 统一行为树入口：数组 → 包装为 sequence */
function normalizeRoot(behavior) {
  if (Array.isArray(behavior)) {
    return { node_type: 'sequence', children: behavior }
  }
  return behavior
}

// ---------------------------------------------------------------------------
// 执行器
// ---------------------------------------------------------------------------

class BehaviorExecutor {
  /**
   * @param {import('mineflayer').Bot} bot
   * @param {object} [options]
   * @param {number} [options.actionTimeoutMs=60000]  单个动作最长执行时间
   * @param {number} [options.moveDistance=1]         默认移动到达距离（方块）
   * @param {function} [options.onStatus]             节点状态回调 (node, {success, error, durationMs})
   */
  constructor(bot, options = {}) {
    this.bot = bot
    this.options = {
      actionTimeoutMs: options.actionTimeoutMs ?? 60000,
      moveDistance: options.moveDistance ?? 1,
      onStatus: options.onStatus ?? null,
    }
    this._cancelled = false
  }

  /** 取消当前执行（停止移动、标记取消，使进行中的动作尽快返回失败） */
  cancel() {
    this._cancelled = true
    if (this.bot.pathfinder) this.bot.pathfinder.setGoal(null)
    this.bot.clearControlStates()
  }

  /**
   * 执行行为树
   * @param {string|object|Array} behavior  core <behavior> 内容（JSON 文本/对象/数组）
   * @returns {Promise<{success: boolean, root: object}>}
   */
  async execute(behavior) {
    const root = normalizeRoot(parseBehavior(behavior))
    if (!root) {
      return { success: true, root: null } // 无行为内容 → 视为成功空执行
    }
    this._cancelled = false
    const result = await this.runNode(root)
    return { success: result.success, root }
  }

  // -------------------------------------------------------------------------
  // 节点分发
  // -------------------------------------------------------------------------

  async runNode(node) {
    if (this._cancelled) return { success: false, node, error: new Error('执行已取消') }

    const started = Date.now()
    try {
      let success = false
      switch (node.node_type) {
        case 'action':
          success = await this.runAction(node)
          break
        case 'condition':
          success = await this.runCondition(node)
          break
        case 'sequence':
          success = await this.runSequence(node)
          break
        case 'selector':
          success = await this.runSelector(node)
          break
        case 'parallel':
          success = await this.runParallel(node)
          break
        default:
          throw new Error(`未知节点类型: ${node.node_type}`)
      }
      const durationMs = Date.now() - started
      if (this.options.onStatus) {
        this.options.onStatus(node, { success, error: null, durationMs })
      }
      return { success, node, durationMs }
    } catch (error) {
      const durationMs = Date.now() - started
      if (this.options.onStatus) {
        this.options.onStatus(node, { success: false, error, durationMs })
      }
      return { success: false, node, error, durationMs }
    }
  }

  // -------------------------------------------------------------------------
  // 组合节点
  // -------------------------------------------------------------------------

  /** sequence：按序执行，任一失败即整体失败 */
  async runSequence(node) {
    for (const child of node.children || []) {
      const result = await this.runNode(child)
      if (!result.success) return false
    }
    return true
  }

  /** selector：按序尝试，任一成功即整体成功 */
  async runSelector(node) {
    for (const child of node.children || []) {
      const result = await this.runNode(child)
      if (result.success) return true
    }
    return false
  }

  /** parallel：并发执行全部子节点，按 parallel_policy 汇总 */
  async runParallel(node) {
    const children = node.children || []
    if (!children.length) return true
    const results = await Promise.all(children.map((child) => this.runNode(child)))
    const succeeded = results.filter((r) => r.success).length
    const policy = node.parallel_policy || 'all_succeed'
    if (policy === 'any_succeed') return succeeded > 0
    return succeeded === children.length
  }

  // -------------------------------------------------------------------------
  // 条件节点 / 动作节点（实现与元数据见 behavior/actions.js）
  // -------------------------------------------------------------------------

  /** 组装传给 actions.js 的执行上下文 */
  _ctx() {
    return {
      bot: this.bot,
      options: this.options,
      isCancelled: () => this._cancelled,
      helpers: {
        ensurePathfinder: () => this._ensurePathfinder(),
        waitGoalReached: () => this._waitGoalReached(),
        nearestPlayer: () => this._nearestPlayer(),
        findEntityByName: (name) => this._findEntityByName(name),
        nearestHostile: () => this._nearestHostile(),
        findBlockByName: (name, maxDistance) => this._findBlockByName(name, maxDistance),
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
      },
    }
  }

  async runCondition(node) {
    return runCondition(this._ctx(), node.condition_type, node.condition_params || {})
  }

  async runAction(node) {
    return runAction(this._ctx(), node.action_type, node.action_params || {})
  }

  // -------------------------------------------------------------------------
  // 内部辅助
  // -------------------------------------------------------------------------

  _ensurePathfinder() {
    if (!this.bot.pathfinder) {
      throw new Error('bot 未加载 mineflayer-pathfinder 插件，无法执行移动类动作')
    }
  }

  /** 等待 pathfinder 到达目标（带超时 + 取消检查） */
  _waitGoalReached() {
    const bot = this.bot
    const timeoutMs = this.options.actionTimeoutMs

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup()
        reject(new Error('移动超时'))
      }, timeoutMs)

      const onReached = () => {
        cleanup()
        resolve()
      }

      const checkCancelled = setInterval(() => {
        if (this._cancelled) {
          cleanup()
          reject(new Error('执行已取消'))
        }
      }, 200)

      function cleanup() {
        clearTimeout(timer)
        clearInterval(checkCancelled)
        bot.removeListener('goal_reached', onReached)
      }

      bot.once('goal_reached', onReached)
      // 已原地到达/无移动目标时立即完成
      if (!bot.pathfinder.isMoving) {
        setTimeout(onReached, 100)
      }
    })
  }

  _nearestPlayer() {
    for (const username of Object.keys(this.bot.players)) {
      const player = this.bot.players[username]
      if (player && player.entity && username !== this.bot.username) return player
    }
    return null
  }

  _findEntityByName(name) {
    return this.bot.nearestEntity(
      (e) => e.name === name || e.displayName === name || e.username === name,
    )
  }

  _nearestHostile() {
    return this.bot.nearestEntity(
      (e) => e.type === 'mob' && e.displayName !== undefined,
    )
  }

  _findBlockByName(name, maxDistance = 64) {
    return this.bot.findBlock({
      matching: (b) => b.name === name,
      maxDistance,
    })
  }
}

module.exports = { BehaviorExecutor, parseBehavior }
