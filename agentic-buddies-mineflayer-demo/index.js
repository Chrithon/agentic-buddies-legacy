'use strict'

/**
 * Agentic Buddies — Mineflayer Demo 主入口（多 NPC 实例）
 *
 * 角色：Minecraft 世界中的 NPC 机器人群。启动时从 Harness 核心
 * （GET /api/npcs/enabled）读取**所有已启用 NPC**，为每个 NPC 创建
 * 独立的 mineflayer bot（用户名 = npcs.name），各自走完整对话管线。
 *
 * 数据流（每个 NPC 实例独立）：
 *   玩家在游戏内聊天 → bot.on('chat') 捕获
 *        ↓
 *   CoreClient.chatWithBehavior() → agentic-buddies-core (POST /api/chat)
 *        ↓
 *   NPC 回复文本（speak）→ bot.chat() 在游戏内说话
 *   behavior JSON → BehaviorExecutor.execute() 驱动 bot 执行动作
 *
 * 外部接入（express）：
 *   GET  /health          健康检查（各 NPC 在线状态）
 *   GET  /status          全部 NPC 状态（支持 ?npc_id= 筛选单个）
 *   POST /api/message     外部推送玩家消息（需 npc_id，缺省取第一个实例）
 *
 * 配置（环境变量，均有默认值）：
 *   MC_HOST / MC_PORT / MC_AUTH(offline|microsoft|mojang)
 *   NPC_ID           可选：显式指定时只加载该 NPC；缺省加载全部已启用 NPC
 *   CORE_URL / HTTP_PORT / MC_RECONNECT_MS / MAX_QUEUE
 */

const express = require('express')
const mineflayer = require('mineflayer')
const { pathfinder } = require('mineflayer-pathfinder')
const fs = require('fs')
const path = require('path')
const yaml = require('js-yaml')

const { CoreClient, BackendClient } = require('./api/api_connect.js')
const { BehaviorExecutor } = require('./behavior/executor.js')
const { ChatListener } = require('./behavior/listen.js')
const { NPCStateMachine, NPC_STATES } = require('./behavior/states.js')

// ---------------------------------------------------------------------------
// 配置加载（优先级：环境变量 > conf.yaml > 默认值）
// ---------------------------------------------------------------------------

function loadConf() {
  const confPath = path.join(__dirname, 'conf.yaml')
  try {
    return yaml.load(fs.readFileSync(confPath, 'utf8')) || {}
  } catch (error) {
    console.warn(`[config] conf.yaml 读取失败（${error.message}），使用默认配置`)
    return {}
  }
}

const conf = loadConf()
const mc = conf.minecraft || {}
const botCfg = conf.bot || {}
const npcCfg = conf.npc || {}
const httpCfg = conf.http || {}
const coreCfg = conf.core || {}
const backendCfg = conf.backend || {}
const runtimeCfg = conf.runtime || {}

const config = {
  mcHost: process.env.MC_HOST || mc.host || 'localhost',
  mcPort: Number(process.env.MC_PORT || mc.port || 25565),
  mcVersion: process.env.MC_VERSION || mc.version || undefined,
  viewDistance:
    process.env.MC_VIEW_DISTANCE || mc.view_distance
      ? Number(process.env.MC_VIEW_DISTANCE || mc.view_distance)
      : undefined,
  mcPassword: process.env.MC_PASSWORD || botCfg.password || '',
  mcAuth: process.env.MC_AUTH || botCfg.auth || 'offline',
  // NPC_ID 显式配置时只加载该 NPC；缺省加载全部已启用 NPC
  npcIdConfigured: Boolean(process.env.NPC_ID || npcCfg.id),
  npcId: Number(process.env.NPC_ID || npcCfg.id || 0),
  coreUrl: process.env.CORE_URL || coreCfg.api_url || 'http://localhost:8001',
  chatTimeoutMs: Number(coreCfg.chat_timeout_ms || 90000),
  backendUrl: process.env.BACKEND_URL || backendCfg.api_url || 'http://localhost:8000',
  httpPort: Number(process.env.HTTP_PORT || httpCfg.port || 3000),
  reconnectDelayMs: Number(process.env.MC_RECONNECT_MS || runtimeCfg.reconnect_delay_ms || 8000),
  maxQueue: Number(process.env.MAX_QUEUE || runtimeCfg.max_queue || 5),
}

// ---------------------------------------------------------------------------
// 全局状态
// ---------------------------------------------------------------------------

const coreClient = new CoreClient({
  baseUrl: config.coreUrl,
  chatTimeoutMs: config.chatTimeoutMs,
})

/** NPC 实例表：npcId -> instance */
const npcInstances = new Map()
let shuttingDown = false

// ---------------------------------------------------------------------------
// 单 NPC 实例：bot + 管线
// ---------------------------------------------------------------------------

/** 从 mineflayer 玩家表获取玩家 UUID（离线服为服务器下发的离线 UUID） */
function getPlayerUuid(instance, username, fallback = null) {
  return instance.bot?.players?.[username]?.uuid || fallback
}

/** 单条消息处理（核心管线，含队列调度）—— 绑定到某个 NPC 实例 */
async function processMessage(instance, username, playerInput, options = {}) {
  if (!username || !playerInput) return null

  if (instance.executing) {
    if (instance.queue.length >= config.maxQueue) {
      console.warn(`[pipeline] ${instance.npc.name} ← ${username} 消息被丢弃：队列已满`)
      return null
    }
    instance.queue.push({ username, playerInput, playerUuid: options.playerUuid })
    return null
  }

  instance.executing = true
  // 中断上一轮可能仍在执行的长时动作（如 follow 跟随 / 挖掘）
  if (instance.executor) instance.executor.cancel()
  instance.stateMachine.transition(NPC_STATES.THINKING, `收到 ${username} 的消息`)
  const started = Date.now()
  try {
    const sessionUuid = instance.sessions.get(username)
    const playerUuid = getPlayerUuid(instance, username, options.playerUuid || null)
    const result = await coreClient.chatWithBehavior({
      npcId: instance.npc.id,
      playerInput,
      sessionUuid,
      playerUuid,
    })
    instance.sessions.set(username, result.sessionUuid)

    // 1. 游戏内说话（多行拆分，避免超长消息被服务器截断）
    instance.stateMachine.transition(NPC_STATES.SPEAKING, 'core 返回回复')
    for (const line of result.speak.split('\n')) {
      if (line.trim()) instance.bot.chat(line.trim())
    }

    // 2. 执行行为树（闲聊时 behavior 为 null，跳过）
    let followActive = false
    if (result.behavior) {
      console.log(
        `[pipeline] ${instance.npc.name} ← ${username} 触发行为：${JSON.stringify(result.behavior).slice(0, 120)}...`,
      )
      instance.stateMachine.transition(NPC_STATES.EXECUTING, '执行行为树')
      await instance.executor.execute(result.behavior)
      followActive = hasFollowAction(result.behavior)
      if (followActive) {
        instance.stateMachine.transition(NPC_STATES.FOLLOWING, '行为树含跟随动作')
      }
    }

    console.log(
      `[pipeline] ${instance.npc.name} ← ${username}：${result.speak.slice(0, 40)}（${Date.now() - started}ms, session=${result.sessionUuid.slice(0, 8)}）`,
    )
    return result
  } catch (error) {
    console.error(`[pipeline] ${instance.npc.name} 处理 ${username} 的消息失败:`, error.message)
    if (instance.botOnline) instance.bot.chat('抱歉，我暂时无法回应…')
    return null
  } finally {
    instance.executing = false
    if (instance.stateMachine.isOnline() && instance.stateMachine.state !== NPC_STATES.OFFLINE) {
      instance.stateMachine.transition(NPC_STATES.IDLE, '本轮处理结束')
    }
    const next = instance.queue.shift()
    if (next && !shuttingDown) {
      setTimeout(
        () => processMessage(instance, next.username, next.playerInput, { playerUuid: next.playerUuid }),
        50,
      )
    }
  }
}

/** 递归判断行为树是否包含 follow 长时动作 */
function hasFollowAction(node) {
  if (!node) return false
  if (node.node_type === 'action' && node.action_type === 'follow') return true
  if (Array.isArray(node.children)) return node.children.some(hasFollowAction)
  return false
}

// ---------------------------------------------------------------------------
// NPC 实例创建（每 NPC 一个 bot）
// ---------------------------------------------------------------------------

function createNpcInstance(npc) {
  const username = npc.name.slice(0, 16) // Minecraft 用户名上限 16 字符
  const instance = {
    npc,
    username,
    bot: null,
    executor: null,
    listener: null,
    botOnline: false,
    stateMachine: new NPCStateMachine({}),
    sessions: new Map(),
    queue: [],
    executing: false,
    reconnectTimer: null,
    reconnectScheduled: false,
  }
  npcInstances.set(npc.id, instance)
  connectBot(instance)
  console.log(`[main] 已创建 NPC 实例 #${npc.id}（${instance.username}）`)
  return instance
}

/**
 * 为实例建立/重建 mineflayer bot（重连时复用同一 instance，避免旧 bot 事件链残留
 * 导致同名重复连接与 duplicate_login 互踢循环）。
 */
function connectBot(instance) {
  // 清理旧 bot：移除全部监听并断开，防止旧事件再次触发重连
  if (instance.bot) {
    instance.bot.removeAllListeners()
    try {
      instance.bot.end()
    } catch {
      /* 已断开则忽略 */
    }
  }
  instance.botOnline = false

  const options = {
    host: config.mcHost,
    port: config.mcPort,
    username: instance.username,
    auth: config.mcAuth,
    hideErrors: false,
  }
  if (config.mcPassword) options.password = config.mcPassword
  if (config.mcVersion) options.version = config.mcVersion
  if (config.viewDistance) options.viewDistance = config.viewDistance

  instance.bot = mineflayer.createBot(options)
  instance.bot.loadPlugin(pathfinder)
  instance.executor = new BehaviorExecutor(instance.bot, {
    onStatus: (node, status) => {
      console.log(
        `[behavior] ${instance.npc.name} ${node.node_type}:${node.action_type || node.condition_type || ''} ` +
          `${status.success ? '✓' : '✗'}${status.error ? `（${status.error.message}）` : ''}`,
      )
    },
  })

  instance.bot.on('spawn', () => {
    instance.botOnline = true
    instance.stateMachine.reset(NPC_STATES.IDLE, '进入世界')
    console.log(`[bot] ${instance.npc.name}（#${instance.npc.id}）已进入世界 ${config.mcHost}:${config.mcPort}`)
    // 确保生存模式：创造模式挖掘不掉落物品，NPC 无法获得/丢弃物品
    if (instance.bot.game?.gameMode && instance.bot.game.gameMode !== 'survival') {
      instance.bot.chat('/gamemode survival')
    }
  })

  // 玩家 @NPC → 走 Harness 管线
  instance.listener = new ChatListener(instance.bot, {
    botUsername: instance.username,
    onMention: (playerName, text) => processMessage(instance, playerName, text),
  })
  instance.listener.start()

  // 玩家离开/断开：清理会话与队列
  instance.bot.on('playerLeft', (player) => {
    instance.sessions.delete(player.username)
    const idx = instance.queue.findIndex((m) => m.username === player.username)
    if (idx !== -1) instance.queue.splice(idx, 1)
  })

  instance.bot.on('error', (err) => {
    console.error(`[bot] ${instance.npc.name} 连接错误:`, err.message)
  })

  instance.bot.on('kicked', (reason) => {
    console.warn(`[bot] ${instance.npc.name} 被服务器踢出:`, reason)
    instance.botOnline = false
    instance.stateMachine.transition(NPC_STATES.OFFLINE, '被服务器踢出')
    scheduleReconnect(instance)
  })

  instance.bot.on('end', () => {
    instance.botOnline = false
    instance.stateMachine.transition(NPC_STATES.OFFLINE, '连接断开')
    console.log(`[bot] ${instance.npc.name} 连接已断开`)
    scheduleReconnect(instance)
  })
}

function scheduleReconnect(instance) {
  if (shuttingDown || instance.reconnectTimer || instance.reconnectScheduled) return
  instance.reconnectScheduled = true
  console.log(`[bot] ${instance.npc.name} ${config.reconnectDelayMs / 1000}s 后尝试重连…`)
  instance.reconnectTimer = setTimeout(() => {
    instance.reconnectTimer = null
    instance.reconnectScheduled = false
    connectBot(instance) // 复用同一 instance 重建 bot
  }, config.reconnectDelayMs)
}

// ---------------------------------------------------------------------------
// Express 服务
// ---------------------------------------------------------------------------

const app = express()
app.use(express.json())

function instanceSummary(instance) {
  const pos = instance.bot?.entity?.position
  return {
    npc_id: instance.npc.id,
    name: instance.npc.name,
    bot_online: instance.botOnline,
    state: instance.stateMachine.state,
    state_label: instance.stateMachine.label,
    executing: instance.executing,
    queue_length: instance.queue.length,
    active_sessions: instance.sessions.size,
    position: pos ? [pos.x, pos.y, pos.z] : null,
    health: instance.bot?.health ?? null,
  }
}

app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    core_url: config.coreUrl,
    npc_count: npcInstances.size,
    npcs: [...npcInstances.values()].map((i) => ({
      npc_id: i.npc.id,
      name: i.npc.name,
      bot_online: i.botOnline,
    })),
  })
})

app.get('/status', (req, res) => {
  const npcId = Number(req.query.npc_id)
  if (npcId) {
    const instance = npcInstances.get(npcId)
    if (!instance) return res.status(404).json({ detail: `NPC #${npcId} 实例不存在` })
    return res.json({ ...instanceSummary(instance), state_history: instance.stateMachine.history(5) })
  }
  res.json({
    npc_count: npcInstances.size,
    npcs: [...npcInstances.values()].map((i) => instanceSummary(i)),
  })
})

app.post('/api/message', async (req, res) => {
  const { npc_id, username, player_input, session_uuid, player_uuid } = req.body || {}
  if (!username || !player_input) {
    return res.status(400).json({ detail: 'username 和 player_input 为必填项' })
  }
  // 缺省取第一个实例；显式 npc_id 时路由到对应实例
  const instance =
    (npc_id && npcInstances.get(Number(npc_id))) || [...npcInstances.values()][0]
  if (!instance) {
    return res.status(503).json({ detail: '没有可用的 NPC 实例' })
  }
  if (session_uuid) instance.sessions.set(username, session_uuid)

  const result = await processMessage(instance, username, player_input, {
    playerUuid: player_uuid || null,
  })
  if (!result) {
    return res.status(503).json({ detail: 'NPC 忙碌或处理失败，请稍后重试' })
  }
  res.json({
    npc_id: instance.npc.id,
    npc_name: instance.npc.name,
    username,
    player_uuid: player_uuid || null,
    session_uuid: result.sessionUuid,
    npc_response: result.speak,
    flagged: result.flagged,
    latency_ms: result.latencyMs,
  })
})

app.listen(config.httpPort, () => {
  console.log(`[http] 控制接口已启动: http://localhost:${config.httpPort}`)
})

// ---------------------------------------------------------------------------
// 优雅退出
// ---------------------------------------------------------------------------

async function shutdown() {
  shuttingDown = true
  console.log('\n[main] 正在关闭…')
  for (const instance of npcInstances.values()) {
    if (instance.reconnectTimer) clearTimeout(instance.reconnectTimer)
    if (instance.listener) instance.listener.stop()
    if (instance.executor) instance.executor.cancel()
    if (instance.bot) {
      instance.bot.removeAllListeners()
      instance.bot.end()
    }
  }
  setTimeout(() => process.exit(0), 300)
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

// ---------------------------------------------------------------------------
// 启动：从 Harness 核心读取已启用 NPC 并逐个创建实例
// ---------------------------------------------------------------------------

/**
 * 启动流程：
 * - 从 core（GET /api/npcs/enabled）读取所有已启用 NPC
 * - 无已启用 NPC → 明确提示后退出
 * - 显式配置 NPC_ID → 只加载该 NPC（必须命中已启用列表）
 * - 缺省 → 为每个已启用 NPC 创建独立 bot 实例
 */
async function boot() {
  console.log(`[main] Agentic Buddies Mineflayer Demo 启动`)
  console.log(`[main] core: ${config.coreUrl} | mc: ${config.mcHost}:${config.mcPort} (${config.mcAuth})`)

  let enabledNpcs
  try {
    enabledNpcs = await coreClient.getEnabledNpcs()
  } catch (error) {
    console.error(`[main] 无法从 Harness 核心读取已启用 NPC: ${error.message}`)
    console.error('[main] 请确认 agentic-buddies-core 已启动后重试')
    process.exit(1)
  }

  if (!Array.isArray(enabledNpcs) || enabledNpcs.length === 0) {
    console.error('[main] 没有已启用的 NPC。')
    console.error('[main] 请先在管理面板（agentic-buddies-dashboard）中将所需 NPC 设为启用后重试。')
    process.exit(1)
  }

  // 显式配置 NPC_ID：只加载该 NPC 并校验其已启用
  let targets = enabledNpcs
  if (config.npcIdConfigured) {
    const configured = enabledNpcs.find((n) => n.id === config.npcId)
    if (!configured) {
      const available = enabledNpcs.map((n) => `#${n.id} ${n.name}`).join('、')
      console.error(`[main] 配置的 NPC #${config.npcId} 不存在或未启用。`)
      console.error(`[main] 当前已启用的 NPC：${available}`)
      process.exit(1)
    }
    targets = [configured]
  }

  console.log(
    `[main] 已启用 NPC ${targets.length} 个：${targets.map((n) => `#${n.id} ${n.name}`).join('、')}`,
  )
  console.log(`[main] 连接 Minecraft 服务器 ${config.mcHost}:${config.mcPort}…`)

  // 为每个已启用 NPC 创建独立 bot 实例
  for (const npc of targets) {
    createNpcInstance(npc)
  }
}

boot()
