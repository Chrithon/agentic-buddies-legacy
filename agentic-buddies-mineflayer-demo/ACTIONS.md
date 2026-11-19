# NPC 原子动作 / 条件参数文档

> 来源：`behavior/actions.js`（mineflayer 侧可执行能力清单，与 agentic-buddies-core `core/models/models.py` 的 ActionType / ConditionType 枚举对齐）

## 用途

- 录入 `behavior_tree` 表（面板"行为树管理"页 `tree_definition` 字段）时的**参数参考手册**
- Harness 核心输出 `<behavior>` 节点数组 → 本库注册表分发 → mineflayer 执行

## 节点 JSON 格式

```json
// 动作节点
{"node_type": "action", "action_type": "move_to", "action_params": {"target": "player", "distance": 3}}

// 条件节点
{"node_type": "condition", "condition_type": "has_item", "condition_params": {"item": "oak_log", "count": 3}}

// 组合节点
{"node_type": "sequence", "children": [ ...子节点数组... ]}
{"node_type": "selector", "children": [ ... ]}
{"node_type": "parallel", "children": [ ... ], "parallel_policy": "all_succeed" | "any_succeed"}
```

> 顶层可为单个节点对象或节点数组（数组按 sequence 顺序执行）。

---

## 动作（19 种）

### 移动类

#### `move_to` 移动到

移动到目标位置/玩家/实体/方块附近，到达后动作完成。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `target` | string \| number[] | ✅ | - | `"player"`=最近玩家；实体名（如 `villager`）；方块名（如 `oak_log`）；或 `[x, y, z]` 坐标数组 |
| `distance` | number | - | `1` | 距目标多少格视为到达（格） |

```json
{"node_type":"action","action_type":"move_to","action_params":{"target":"tree","distance":2}}
```

#### `follow` 跟随

持续跟随最近玩家（长期动作，可被 `stop` / 新行为打断）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `distance` | number | - | `3` | 与玩家的保持距离（格） |

```json
{"node_type":"action","action_type":"follow","action_params":{"distance":3}}
```

#### `stop` 停止

停止一切移动与当前动作（取消 pathfinder 目标、清除控制状态）。

无参数。

```json
{"node_type":"action","action_type":"stop","action_params":{}}
```

#### `jump` 跳跃

原地跳跃（可指定次数与间隔，常用于表达情绪/示意）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `count` | number | - | `1` | 跳跃次数 |
| `delay_ms` | number | - | `250` | 每次跳跃的间隔毫秒数 |

```json
{"node_type":"action","action_type":"jump","action_params":{"count":3,"delay_ms":300}}
```

### 交互类

#### `say` 说话

在游戏内聊天栏输出一句话。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `text` | string | ✅ | - | 要说的话 |

```json
{"node_type":"action","action_type":"say","action_params":{"text":"你好，旅人"}}
```

#### `interact` 交互

与实体或方块交互（右键实体 / 激活方块）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `target` | string | ✅ | - | 实体名（如 `villager`）或方块名（如 `chest`） |

```json
{"node_type":"action","action_type":"interact","action_params":{"target":"villager"}}
```

#### `use_item` 使用物品

装备并使用背包中的物品。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `item` | string | ✅ | - | 物品名（如 `torch`、`bread`） |
| `hold_ms` | number | - | `500` | 激活后保持的毫秒数 |

```json
{"node_type":"action","action_type":"use_item","action_params":{"item":"torch","hold_ms":300}}
```

#### `hold_item` 手持物品

将背包中的物品装备到主手（仅手持，不激活使用）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `item` | string | ✅ | - | 物品名（如 `sword`、`torch`、`oak_log`） |

```json
{"node_type":"action","action_type":"hold_item","action_params":{"item":"sword"}}
```

#### `drop_item` 掉落物品

从背包中丢弃指定物品（可指定数量）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `item` | string | ✅ | - | 要丢弃的物品名（如 `oak_log`、`dirt`） |
| `count` | number | - | `1` | 丢弃数量（不超过背包持有量） |

```json
{"node_type":"action","action_type":"drop_item","action_params":{"item":"oak_log","count":5}}
```

#### `attack` 攻击

攻击指定目标一次（恐吓/警告用）；未指定时攻击最近的敌对生物。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `target` | string | - | - | 实体名；留空 = 最近敌对生物 |

```json
{"node_type":"action","action_type":"attack","action_params":{"target":"zombie"}}
```

#### `kill` 击杀

持续攻击指定实体直至其死亡（可被新指令中断）；未指定时攻击最近的敌对生物。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `target` | string | - | - | 实体名；留空 = 最近敌对生物 |

```json
{"node_type":"action","action_type":"kill","action_params":{"target":"sheep"}}
```

#### `look_at` 看向目标

原地转向看向目标（玩家/实体/坐标/方向词），保持位置不动。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `target` | string | - | `player` | `"player"`=最近玩家（默认）；实体名；`[x, y, z]` 坐标；**方向词** `back`（转身180°）/`front`/`left`/`right` |

```json
{"node_type":"action","action_type":"look_at","action_params":{}}
```

```json
{"node_type":"action","action_type":"look_at","action_params":{"target":"villager"}}
```

```json
{"node_type":"action","action_type":"look_at","action_params":{"target":"back"}}
```

#### `turn_back` 向后转

原地转身 180 度，面朝反方向。

无参数。

```json
{"node_type":"action","action_type":"turn_back","action_params":{}}
```

### 采集 / 制造类

#### `collect_block` 采集方块

移动到最近的指定方块旁并挖掘它。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `block` | string | ✅ | - | 方块名（如 `oak_log`、`diamond_ore`） |

```json
{"node_type":"action","action_type":"collect_block","action_params":{"block":"oak_log"}}
```

#### `gather` 拾取物品

移动到最近的可拾取掉落物旁（靠近后自动入包）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `item` | string | - | - | 物品名；留空 = 最近任意掉落物 |

```json
{"node_type":"action","action_type":"gather","action_params":{"item":"oak_log"}}
```

#### `craft` 合成

按背包可用的配方合成物品（2x2 工作台网格，无需工作台方块）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `item` | string | ✅ | - | 要合成的物品名（如 `oak_planks`、`stick`） |
| `count` | number | - | `1` | 合成数量 |

```json
{"node_type":"action","action_type":"craft","action_params":{"item":"oak_planks","count":4}}
```

#### `trade` 交易

与最近的村民交互打开交易窗口。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `target` | string | - | - | 村民实体名；留空 = 最近村民 |

```json
{"node_type":"action","action_type":"trade","action_params":{}}
```

#### `place_block` 摆放方块

在指定方向摆放背包中的方块（默认摆放在脚下上方，需背包有该方块）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `block` | string | ✅ | - | 要摆放的方块名（如 `cobblestone`、`oak_planks`） |
| `direction` | string | - | `up` | 摆放方向：`up`/`down`/`north`/`south`/`east`/`west` |

```json
{"node_type":"action","action_type":"place_block","action_params":{"block":"cobblestone","direction":"up"}}
```

### 其他

#### `wait` 等待

原地等待指定秒数（常用于行为树中的节奏控制）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `seconds` | number | - | `1` | 等待时长（秒） |

```json
{"node_type":"action","action_type":"wait","action_params":{"seconds":2}}
```

---

## 条件（6 种）

#### `has_item` 拥有物品

背包中指定物品数量是否达标。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `item` | string | ✅ | - | 物品名（如 `oak_log`） |
| `count` | number | - | `1` | 至少需要的数量 |

```json
{"node_type":"condition","condition_type":"has_item","condition_params":{"item":"oak_log","count":5}}
```

#### `health_above` 生命高于

NPC 当前生命值是否高于指定值。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `value` | number | ✅ | - | 生命值阈值（0-20） |

```json
{"node_type":"condition","condition_type":"health_above","condition_params":{"value":10}}
```

#### `health_below` 生命低于

NPC 当前生命值是否低于指定值。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `value` | number | ✅ | - | 生命值阈值（0-20） |

```json
{"node_type":"condition","condition_type":"health_below","condition_params":{"value":5}}
```

#### `distance_to_player` 距玩家距离

与最近玩家的距离是否符合比较条件。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `value` | number | ✅ | - | 比较基准距离（格） |
| `operator` | string | - | `<` | 比较符：`<` \| `<=` \| `>` \| `>=` \| `=` |

```json
{"node_type":"condition","condition_type":"distance_to_player","condition_params":{"value":10,"operator":">"}}
```

#### `has_target` 存在目标

世界中是否存在指定名称的实体。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `target` | string | ✅ | - | 实体名（如 `villager`、`zombie`） |

```json
{"node_type":"condition","condition_type":"has_target","condition_params":{"target":"zombie"}}
```

#### `is_in_world` 方块存在

世界中是否存在指定方块（用于寻路可行性判断）。

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `block` | string | ✅ | - | 方块名（如 `oak_log`） |
| `max_distance` | number | - | `64` | 搜索范围（格） |

```json
{"node_type":"condition","condition_type":"is_in_world","condition_params":{"block":"oak_log","max_distance":32}}
```

---

## 完整示例（砍树任务）

```json
{
  "node_type": "sequence",
  "children": [
    {"node_type": "action", "action_type": "move_to", "action_params": {"target": "tree"}},
    {"node_type": "action", "action_type": "collect_block", "action_params": {"block": "oak_log"}},
    {"node_type": "action", "action_type": "say", "action_params": {"text": "砍好了"}},
    {"node_type": "action", "action_type": "move_to", "action_params": {"target": "player", "distance": 3}}
  ]
}
```

## 完整示例（带条件分支）

```json
{
  "node_type": "selector",
  "children": [
    {
      "node_type": "sequence",
      "children": [
        {"node_type": "condition", "condition_type": "has_item", "condition_params": {"item": "oak_log", "count": 5}},
        {"node_type": "action", "action_type": "say", "action_params": {"text": "木材已备齐"}}
      ]
    },
    {
      "node_type": "sequence",
      "children": [
        {"node_type": "action", "action_type": "move_to", "action_params": {"target": "tree"}},
        {"node_type": "action", "action_type": "collect_block", "action_params": {"block": "oak_log"}}
      ]
    }
  ]
}
```

## 完整示例（并行 + 条件）

```json
{
  "node_type": "parallel",
  "parallel_policy": "all_succeed",
  "children": [
    {
      "node_type": "sequence",
      "children": [
        {"node_type": "condition", "condition_type": "health_below", "condition_params": {"value": 8}},
        {"node_type": "action", "action_type": "use_item", "action_params": {"item": "bread"}},
        {"node_type": "action", "action_type": "wait", "action_params": {"seconds": 2}}
      ]
    },
    {"node_type": "action", "action_type": "say", "action_params": {"text": "我稍作休整"}},
    {"node_type": "action", "action_type": "say", "action_params": {"text": "*擦拭长剑*"}}
  ]
}
```

## 更多参考示例

