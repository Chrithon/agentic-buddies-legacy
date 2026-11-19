'use strict'

/**
 * 原子动作 / 条件库（NPC 能力清单）。
 *
 * 这是 mineflayer 侧可执行的**全部**动作与条件定义，同时也是录入
 * agentic-buddies-backend `behavior_tree` 表的**动作参考手册**：
 *
 *   ┌─────────────────────────────────────────────────────────────────────┐
 *   │ 面板录入行为树（tree_definition JSONB）→ core 读取（route_task 展示）│
 *   │ → core 输出 <behavior> → 本库（executor 分发）→ mineflayer 执行      │
 *   └─────────────────────────────────────────────────────────────────────┘
 *
 * 每个定义包含：
 *   - type        动作/条件类型（对应 core ActionType / ConditionType 枚举）
 *   - label       中文名（面板展示用）
 *   - description 用途说明（面板 tooltip / 表单提示用）
 *   - params      参数 schema（面板生成参数表单用）：
 *                   name 参数键 | label 中文名 | type 类型 | required 必填
 *                   default 默认值 | description 说明 | enum 可选值
 *   - handler     实际执行函数 (ctx, params) => Promise<boolean>，失败抛错
 *
 * ctx（执行上下文，由 executor 注入）：
 *   { bot, options, helpers }
 *   helpers: { ensurePathfinder, waitGoalReached, nearestPlayer,
 *              findEntityByName, nearestHostile, findBlockByName, sleep }
 *
 * 节点 JSON 格式（写入 tree_definition / core 输出均为此格式）：
 *   动作:    {"node_type": "action",    "action_type": "move_to",
 *             "action_params": {"target": "player", "distance": 3}}
 *   条件:    {"node_type": "condition", "condition_type": "has_item",
 *             "condition_params": {"item": "oak_log", "count": 3}}
 *   组合:    {"node_type": "sequence", "children": [...]}  等
 */

const { goals } = require('mineflayer-pathfinder')
const Vec3 = require('vec3')

// ---------------------------------------------------------------------------
// 目标解析辅助
// ---------------------------------------------------------------------------

/** 模糊目标词 → 默认方块名（未指明具体树种时按橡树处理） */
const BLOCK_SYNONYMS = {
  tree: 'oak_log',
  log: 'oak_log',
  树: 'oak_log',
  原木: 'oak_log',
  木头: 'oak_log',
}

/** 解析方块目标词：模糊词映射到默认方块，其余原样返回 */
function resolveBlockName(name) {
  if (!name) return name
  return BLOCK_SYNONYMS[name] || name
}

/** 解析字符串坐标（"100,64,200" 或 "[100,64,200]"）→ 数组；非坐标返回 null */
function parseCoordString(value) {
  if (typeof value !== 'string') return null
  const cleaned = value.replace(/[\[\]]/g, '')
  const parts = cleaned.split(',').map((s) => Number(s.trim()))
  if (parts.length === 3 && parts.every((n) => Number.isFinite(n))) {
    return parts
  }
  return null
}

// ---------------------------------------------------------------------------
// 动作定义（对齐 core ActionType）
// ---------------------------------------------------------------------------

const ACTION_DEFS = [
  // ==================== 移动类 ====================
  {
    type: 'move_to',
    label: '移动到',
    description: '移动到目标位置/玩家/实体/方块附近，到达后动作完成。',
    params: [
      {
        name: 'target',
        label: '目标',
        type: 'string',
        required: true,
        description: '"player"=最近玩家 | 实体名（如 villager）| 方块名（如 oak_log）| [x,y,z] 坐标',
      },
      {
        name: 'distance',
        label: '到达距离',
        type: 'number',
        default: 1,
        description: '距目标多少格视为到达（格）',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers } = ctx
      helpers.ensurePathfinder()

      const target = p.target
      const distance = p.distance ?? ctx.options.moveDistance

      let goal
      if (target === 'player') {
        const player = helpers.nearestPlayer()
        if (!player) throw new Error('找不到玩家目标')
        goal = new goals.GoalNear(
          player.entity.position.x,
          player.entity.position.y,
          player.entity.position.z,
          distance,
        )
      } else if (Array.isArray(target)) {
        goal = new goals.GoalNear(target[0], target[1], target[2], distance)
      } else {
        // 字符串坐标（"100,64,200" / "[100,64,200]"）→ 解析为数组
        const coords = parseCoordString(target)
        if (coords) {
          goal = new goals.GoalNear(coords[0], coords[1], coords[2], distance)
        } else {
          const entity = helpers.findEntityByName(target)
          if (entity) {
            goal = new goals.GoalNear(
              entity.position.x,
              entity.position.y,
              entity.position.z,
              distance,
            )
          } else {
            // 方块名（模糊词如 tree 默认映射 oak_log）
            const block = helpers.findBlockByName(resolveBlockName(target))
            if (!block) throw new Error(`找不到目标「${target}」（实体或方块）`)
            goal = new goals.GoalNear(
              block.position.x,
              block.position.y,
              block.position.z,
              distance,
            )
          }
        }
      }

      bot.pathfinder.setGoal(goal)
      await helpers.waitGoalReached()
      return true
    },
  },
  {
    type: 'follow',
    label: '跟随',
    description: '持续跟随最近玩家（长期动作，可被 stop / 新行为打断）。',
    params: [
      {
        name: 'distance',
        label: '跟随距离',
        type: 'number',
        default: 3,
        description: '与玩家的保持距离（格）',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers } = ctx
      helpers.ensurePathfinder()

      const player = helpers.nearestPlayer()
      if (!player) throw new Error('找不到玩家目标')
      bot.pathfinder.setGoal(new goals.GoalFollow(player.entity, p.distance ?? 3), true)
      return true
    },
  },
  {
    type: 'stop',
    label: '停止',
    description: '停止一切移动与当前动作（取消 pathfinder 目标、清除控制状态）。',
    params: [],
    handler: (ctx) => {
      const { bot } = ctx
      if (bot.pathfinder) bot.pathfinder.setGoal(null)
      bot.clearControlStates()
      return true
    },
  },
  {
    type: 'jump',
    label: '跳跃',
    description: '原地跳跃（可指定次数与间隔，常用于表达情绪/示意）。',
    params: [
      {
        name: 'count',
        label: '次数',
        type: 'number',
        default: 1,
        description: '跳跃次数',
      },
      {
        name: 'delay_ms',
        label: '间隔(ms)',
        type: 'number',
        default: 250,
        description: '每次跳跃的间隔毫秒数',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers } = ctx
      const count = Math.max(1, p.count ?? 1)
      const delay = p.delay_ms ?? 250
      for (let i = 0; i < count; i++) {
        // mineflayer 无 bot.jump()，用控制状态起跳（按住约 200ms 完成一次跳跃）
        bot.setControlState('jump', true)
        await helpers.sleep(200)
        bot.setControlState('jump', false)
        if (i < count - 1) await helpers.sleep(delay)
      }
      return true
    },
  },

  // ==================== 交互类 ====================
  {
    type: 'say',
    label: '说话',
    description: '在游戏内聊天栏输出一句话。',
    params: [
      {
        name: 'text',
        label: '文本',
        type: 'string',
        required: true,
        description: '要说的话',
      },
    ],
    handler: (ctx, p) => {
      ctx.bot.chat(String(p.text ?? ''))
      return true
    },
  },
  {
    type: 'interact',
    label: '交互',
    description: '与实体或方块交互（右键实体 / 激活方块）。',
    params: [
      {
        name: 'target',
        label: '目标',
        type: 'string',
        required: true,
        description: '实体名（如 villager）或方块名（如 chest）',
      },
    ],
    handler: (ctx, p) => {
      const { bot, helpers } = ctx
      const target = p.target
      if (!target) throw new Error('interact 需要指定 target')

      const entity = helpers.findEntityByName(target)
      if (entity) {
        bot.useOn(entity)
        return true
      }
      const block = helpers.findBlockByName(target)
      if (block) {
        bot.activateBlock(block)
        return true
      }
      throw new Error(`找不到交互目标「${target}」`)
    },
  },
  {
    type: 'hold_item',
    label: '手持物品',
    description: '将背包中的物品装备到主手（仅手持，不激活使用）。',
    params: [
      {
        name: 'item',
        label: '物品',
        type: 'string',
        required: true,
        description: '物品名（如 sword、torch、oak_log）',
      },
    ],
    handler: async (ctx, p) => {
      const { bot } = ctx
      const itemName = p.item
      if (!itemName) throw new Error('hold_item 需要指定 item')

      const item = bot.inventory.items().find((i) => i.name === itemName)
      if (!item) throw new Error(`背包中没有「${itemName}」`)
      await bot.equip(item, 'hand')
      return true
    },
  },
  {
    type: 'drop_item',
    label: '掉落物品',
    description: '从背包中丢弃指定物品（可指定数量）。',
    params: [
      {
        name: 'item',
        label: '物品',
        type: 'string',
        required: true,
        description: '要丢弃的物品名（如 oak_log、dirt）',
      },
      {
        name: 'count',
        label: '数量',
        type: 'number',
        default: 1,
        description: '丢弃数量（不超过背包持有量）',
      },
    ],
    handler: async (ctx, p) => {
      const { bot } = ctx
      const itemName = p.item
      if (!itemName) throw new Error('drop_item 需要指定 item')

      const count = p.count ?? 1
      const item = bot.inventory.items().find((i) => i.name === itemName)
      if (!item) throw new Error(`背包中没有「${itemName}」`)
      // toss 的 itemType 参数是数字物品 ID（item.type），非字符串名
      await bot.toss(item.type, null, count)
      return true
    },
  },
  {
    type: 'use_item',
    label: '使用物品',
    description: '装备并使用背包中的物品（如使用火把、吃食物）。',
    params: [
      {
        name: 'item',
        label: '物品',
        type: 'string',
        required: true,
        description: '物品名（如 torch、bread）',
      },
      {
        name: 'hold_ms',
        label: '使用时长(ms)',
        type: 'number',
        default: 500,
        description: '激活后保持的毫秒数',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers } = ctx
      const itemName = p.item
      if (!itemName) throw new Error('use_item 需要指定 item')

      const item = bot.inventory.items().find((i) => i.name === itemName)
      if (!item) throw new Error(`背包中没有「${itemName}」`)
      await bot.equip(item, 'hand')
      bot.activateItem()
      await helpers.sleep(p.hold_ms ?? 500)
      return true
    },
  },
  {
    type: 'attack',
    label: '攻击',
    description: '攻击指定目标一次（恐吓/警告用）；未指定时攻击最近的敌对生物。',
    params: [
      {
        name: 'target',
        label: '目标',
        type: 'string',
        required: false,
        description: '实体名；留空=最近敌对生物',
      },
    ],
    handler: (ctx, p) => {
      const { bot, helpers } = ctx
      const entity = p.target ? helpers.findEntityByName(p.target) : helpers.nearestHostile()
      if (!entity) throw new Error('找不到攻击目标')
      bot.attack(entity)
      return true
    },
  },
  {
    type: 'kill',
    label: '击杀',
    description: '追逐并持续攻击指定实体直至其死亡（远离时自动追赶，近身时攻击）；未指定时攻击最近的敌对生物。',
    params: [
      {
        name: 'target',
        label: '目标',
        type: 'string',
        required: false,
        description: '实体名；留空=最近敌对生物',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers, isCancelled } = ctx
      helpers.ensurePathfinder()
      const entity = p.target ? helpers.findEntityByName(p.target) : helpers.nearestHostile()
      if (!entity) throw new Error('找不到攻击目标')

      const ATTACK_RANGE = 3.2   // 近战攻击距离（格）
      const timeoutMs = ctx.options.actionTimeoutMs || 60000
      const deadline = Date.now() + timeoutMs

      // 追逐 + 攻击循环：远离 → 跟随追赶；近身 → 停止并攻击
      while (entity.isValid && !isCancelled()) {
        if (Date.now() > deadline) throw new Error('击杀超时')

        const dist = bot.entity.position.distanceTo(entity.position)
        if (dist > ATTACK_RANGE) {
          // 追赶目标（动态跟随，保持攻击距离内）
          bot.pathfinder.setGoal(new goals.GoalFollow(entity, ATTACK_RANGE), true)
          await helpers.sleep(300)
        } else {
          // 近身：停止移动并攻击
          bot.pathfinder.setGoal(null)
          bot.lookAt(entity.position)
          bot.attack(entity)
          await helpers.sleep(600)   // 攻击冷却
        }
      }
      bot.pathfinder.setGoal(null)
      if (isCancelled()) throw new Error('执行已取消')
      return true
    },
  },
  {
    type: 'look_at',
    label: '看向目标',
    description: '原地转向看向目标（玩家/实体/坐标/方向词），保持位置不动。',
    params: [
      {
        name: 'target',
        label: '目标',
        type: 'string',
        required: false,
        default: 'player',
        description: '"player"=最近玩家（默认）| 实体名 | [x,y,z] 坐标 | 方向词（back/front/left/right）',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers } = ctx
      const target = p.target || 'player'

      // 方向词：相对当前朝向原地转向（back=180°、left=+90°、right=-90°、front=不变）
      const DIRECTION_WORDS = { back: 1, front: 0, left: 0.5, right: -0.5 }
      if (target in DIRECTION_WORDS) {
        await bot.look(
          bot.entity.yaw + Math.PI * DIRECTION_WORDS[target],
          bot.entity.pitch,
        )
        return true
      }

      let point
      if (target === 'player') {
        const player = helpers.nearestPlayer()
        if (!player) throw new Error('找不到玩家目标')
        point = player.entity.position
      } else if (Array.isArray(target)) {
        point = new Vec3(target[0], target[1], target[2])
      } else {
        const entity = helpers.findEntityByName(target)
        if (!entity) throw new Error(`找不到目标「${target}」`)
        point = entity.position
      }

      // lookAt 返回 Promise（force 默认 true，立即转向）
      await bot.lookAt(point)
      return true
    },
  },
  {
    type: 'turn_back',
    label: '向后转',
    description: '原地转身 180 度，面朝反方向。',
    params: [],
    handler: async (ctx) => {
      const { bot } = ctx
      await bot.look(bot.entity.yaw + Math.PI, bot.entity.pitch)
      return true
    },
  },

  {
    type: 'wait',
    label: '等待',
    description: '原地等待指定秒数（常用于行为树中的节奏控制）。',
    params: [
      {
        name: 'seconds',
        label: '秒数',
        type: 'number',
        default: 1,
        description: '等待时长（秒）',
      },
    ],
    handler: async (ctx, p) => {
      await ctx.helpers.sleep((p.seconds ?? 1) * 1000)
      return true
    },
  },

  // ==================== 采集/制造类 ====================
  {
    type: 'collect_block',
    label: '采集方块',
    description: '移动到最近的指定方块旁并挖掘它。',
    params: [
      {
        name: 'block',
        label: '方块',
        type: 'string',
        required: true,
        description: '方块名（如 oak_log、diamond_ore）',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers, isCancelled } = ctx
      helpers.ensurePathfinder()

      // 模糊词（tree/log/树/木头）默认映射为 oak_log
      const blockName = resolveBlockName(p.block)
      const block = helpers.findBlockByName(blockName)
      if (!block) throw new Error(`找不到方块「${blockName}」`)

      bot.pathfinder.setGoal(
        new goals.GoalNear(block.position.x, block.position.y, block.position.z, 2),
      )
      await helpers.waitGoalReached()

      const fresh = bot.blockAt(block.position)
      if (!fresh) throw new Error(`方块「${blockName}」已不存在`)
      await bot.dig(fresh, false)

      // 拾取掉落物：挖掘后物品变为掉落物实体，需靠近（0.5 格内自动入包）
      await helpers.sleep(300)   // 等待掉落物生成
      const deadline = Date.now() + 5000
      while (Date.now() < deadline && !(isCancelled?.() ?? false)) {
        const drop = bot.nearestEntity((e) => e.type === 'object')
        if (!drop) break
        const dist = bot.entity.position.distanceTo(drop.position)
        if (dist < 0.8) break
        bot.pathfinder.setGoal(
          new goals.GoalNear(drop.position.x, drop.position.y, drop.position.z, 0.6),
        )
        await helpers.waitGoalReached()
        await helpers.sleep(200)
      }
      bot.pathfinder.setGoal(null)
      return true
    },
  },
  {
    type: 'gather',
    label: '拾取物品',
    description: '移动到最近的可拾取掉落物旁（靠近后自动入包）。',
    params: [
      {
        name: 'item',
        label: '物品',
        type: 'string',
        required: false,
        description: '物品名；留空=最近任意掉落物',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers } = ctx
      helpers.ensurePathfinder()

      const itemName = p.item
      let itemEntity = null
      if (itemName) {
        itemEntity = bot.nearestEntity(
          (e) => e.type === 'object' && (e.displayName === itemName || e.name === itemName),
        )
      }
      if (!itemEntity) {
        itemEntity = bot.nearestEntity((e) => e.type === 'object')
      }
      if (!itemEntity) throw new Error(`找不到可拾取的物品「${itemName || '任意'}」`)

      bot.pathfinder.setGoal(
        new goals.GoalNear(
          itemEntity.position.x,
          itemEntity.position.y,
          itemEntity.position.z,
          1,
        ),
      )
      await helpers.waitGoalReached()
      return true
    },
  },
  {
    type: 'craft',
    label: '合成',
    description: '按背包可用的配方合成物品（2x2 工作台网格，无需工作台方块）。',
    params: [
      {
        name: 'item',
        label: '物品',
        type: 'string',
        required: true,
        description: '要合成的物品名（如 oak_planks、stick）',
      },
      {
        name: 'count',
        label: '数量',
        type: 'number',
        default: 1,
        description: '合成数量',
      },
    ],
    handler: async (ctx, p) => {
      const { bot } = ctx
      const itemName = p.item
      const count = p.count ?? 1
      if (!itemName) throw new Error('craft 需要指定 item')

      const recipes = bot.recipesFor(itemName, null, count)
      if (!recipes.length) throw new Error(`没有「${itemName}」的合成配方`)
      await bot.craft(recipes[0], count, null)
      return true
    },
  },
  {
    type: 'trade',
    label: '交易',
    description: '与最近的村民交互打开交易窗口。',
    params: [
      {
        name: 'target',
        label: '村民',
        type: 'string',
        required: false,
        description: '村民实体名；留空=最近村民',
      },
    ],
    handler: (ctx, p) => {
      const { bot, helpers } = ctx
      const villager = p.target
        ? helpers.findEntityByName(p.target)
        : bot.nearestEntity((e) => e.name === 'villager')
      if (!villager) throw new Error('找不到可交易的村民')
      bot.useOn(villager)
      return true
    },
  },
  {
    type: 'place_block',
    label: '摆放方块',
    description: '在指定方向摆放背包中的方块（默认摆放在脚下上方，需背包有该方块）。',
    params: [
      {
        name: 'block',
        label: '方块',
        type: 'string',
        required: true,
        description: '要摆放的方块名（如 cobblestone、oak_planks）',
      },
      {
        name: 'direction',
        label: '方向',
        type: 'string',
        enum: ['up', 'down', 'north', 'south', 'east', 'west'],
        default: 'up',
        description: '摆放方向（up=脚下上方，north/south/east/west=水平方向）',
      },
    ],
    handler: async (ctx, p) => {
      const { bot, helpers } = ctx
      const blockName = p.block
      if (!blockName) throw new Error('place_block 需要指定 block')

      const item = bot.inventory.items().find((i) => i.name === blockName)
      if (!item) throw new Error(`背包中没有「${blockName}」`)
      await bot.equip(item, 'hand')

      // 参考方块：脚下的方块（放置目标 = 参考方块 + 朝向向量）
      const referenceBlock = bot.blockAt(bot.entity.position.offset(0, -1, 0))
      if (!referenceBlock) throw new Error('脚下没有可作参考的方块')

      const faceVectors = {
        up: new Vec3(0, 1, 0),
        down: new Vec3(0, -1, 0),
        north: new Vec3(0, 0, -1),
        south: new Vec3(0, 0, 1),
        east: new Vec3(1, 0, 0),
        west: new Vec3(-1, 0, 0),
      }
      const faceVector = faceVectors[p.direction || 'up'] || faceVectors.up

      await bot.placeBlock(referenceBlock, faceVector)
      return true
    },
  },
]

// ---------------------------------------------------------------------------
// 条件定义（对齐 core ConditionType）
// ---------------------------------------------------------------------------

const CONDITION_DEFS = [
  {
    type: 'has_item',
    label: '拥有物品',
    description: '背包中指定物品数量是否达标。',
    params: [
      {
        name: 'item',
        label: '物品',
        type: 'string',
        required: true,
        description: '物品名（如 oak_log）',
      },
      {
        name: 'count',
        label: '数量',
        type: 'number',
        default: 1,
        description: '至少需要的数量',
      },
    ],
    handler: (ctx, p) => {
      const count = ctx.bot.inventory.count(p.item || '')
      return count >= (p.count ?? 1)
    },
  },
  {
    type: 'health_above',
    label: '生命高于',
    description: 'NPC 当前生命值是否高于指定值。',
    params: [
      {
        name: 'value',
        label: '阈值',
        type: 'number',
        required: true,
        description: '生命值阈值（0-20）',
      },
    ],
    handler: (ctx, p) => ctx.bot.health > (p.value ?? 0),
  },
  {
    type: 'health_below',
    label: '生命低于',
    description: 'NPC 当前生命值是否低于指定值。',
    params: [
      {
        name: 'value',
        label: '阈值',
        type: 'number',
        required: true,
        description: '生命值阈值（0-20）',
      },
    ],
    handler: (ctx, p) => ctx.bot.health < (p.value ?? 100),
  },
  {
    type: 'distance_to_player',
    label: '距玩家距离',
    description: '与最近玩家的距离是否符合比较条件。',
    params: [
      {
        name: 'value',
        label: '距离',
        type: 'number',
        required: true,
        description: '比较基准距离（格）',
      },
      {
        name: 'operator',
        label: '比较符',
        type: 'string',
        enum: ['<', '<=', '>', '>=', '='],
        default: '<',
        description: '距离 < / <= / > / >= / = 基准值',
      },
    ],
    handler: (ctx, p) => {
      const { bot, helpers } = ctx
      const player = helpers.nearestPlayer()
      if (!player) return false
      const dist = bot.entity.position.distanceTo(player.entity.position)
      const value = p.value ?? 1
      switch (p.operator || '<') {
        case '<': return dist < value
        case '<=': return dist <= value
        case '>': return dist > value
        case '>=': return dist >= value
        case '=': return Math.abs(dist - value) < 0.5
        default: return dist < value
      }
    },
  },
  {
    type: 'has_target',
    label: '存在目标',
    description: '世界中是否存在指定名称的实体。',
    params: [
      {
        name: 'target',
        label: '目标',
        type: 'string',
        required: true,
        description: '实体名（如 villager、zombie）',
      },
    ],
    handler: (ctx, p) => {
      if (!p.target) return false
      return ctx.helpers.findEntityByName(p.target) !== null
    },
  },
  {
    type: 'is_in_world',
    label: '方块存在',
    description: '世界中是否存在指定方块（用于寻路可行性判断）。',
    params: [
      {
        name: 'block',
        label: '方块',
        type: 'string',
        required: true,
        description: '方块名（如 oak_log）',
      },
      {
        name: 'max_distance',
        label: '搜索距离',
        type: 'number',
        default: 64,
        description: '搜索范围（格）',
      },
    ],
    handler: (ctx, p) => {
      if (!p.block) return false
      const block = ctx.bot.findBlock({
        matching: (b) => b.name === p.block,
        maxDistance: p.max_distance ?? 64,
      })
      return block !== null
    },
  },
]

// ---------------------------------------------------------------------------
// 注册表访问
// ---------------------------------------------------------------------------

const ACTION_MAP = new Map(ACTION_DEFS.map((d) => [d.type, d]))
const CONDITION_MAP = new Map(CONDITION_DEFS.map((d) => [d.type, d]))

/** 动作定义（元数据，不含 handler，便于面板/文档消费） */
function listActions() {
  return ACTION_DEFS.map(({ handler, ...meta }) => meta)
}

/** 条件定义（元数据） */
function listConditions() {
  return CONDITION_DEFS.map(({ handler, ...meta }) => meta)
}

function getAction(type) {
  return ACTION_MAP.get(type) || null
}

function getCondition(type) {
  return CONDITION_MAP.get(type) || null
}

/**
 * 执行动作
 * @param {object} ctx    执行上下文 { bot, options, helpers }
 * @param {string} type   动作类型
 * @param {object} params 动作参数
 * @returns {Promise<boolean>}
 */
async function runAction(ctx, type, params) {
  const def = ACTION_MAP.get(type)
  if (!def) throw new Error(`未知动作类型: ${type}`)
  return def.handler(ctx, params || {})
}

/**
 * 判定条件
 * @param {object} ctx    执行上下文 { bot, options, helpers }
 * @param {string} type   条件类型
 * @param {object} params 条件参数
 * @returns {Promise<boolean>}
 */
async function runCondition(ctx, type, params) {
  const def = CONDITION_MAP.get(type)
  if (!def) throw new Error(`未知条件类型: ${type}`)
  return def.handler(ctx, params || {})
}

module.exports = {
  ACTION_DEFS,
  CONDITION_DEFS,
  listActions,
  listConditions,
  getAction,
  getCondition,
  runAction,
  runCondition,
}
