'use strict'
// 从 actions.js 元数据生成 Markdown 参数文档（一次性脚本）
const fs = require('fs')
const path = require('path')
const { listActions, listConditions } = require('../behavior/actions.js')

const esc = (s) => String(s).replace(/\|/g, '\\|')

const rows = (defs, typeKey) => defs
  .map((d) => {
    const paramRows = d.params
      .map(
        (p) =>
          `| \`${esc(p.name)}\` | ${esc(p.label)} | ${esc(p.type)} | ${p.required ? '✔' : '—'} | ${
            p.default !== undefined ? `\`${esc(p.default)}\`` : '—'
          }${p.enum ? `（${p.enum.map((e) => `\`${esc(e)}\``).join('/')}）` : ''} | ${esc(p.description)} |`,
      )
      .join('\n')
    const paramsBlock =
      d.params.length === 0
        ? '_无参数_'
        : `| 参数 | 中文名 | 类型 | 必填 | 默认值 | 说明 |\n| --- | --- | --- | --- | --- | --- |\n${paramRows}`
    return [
      `### \`${esc(d.type)}\` — ${esc(d.label)}`,
      '',
      esc(d.description),
      '',
      paramsBlock,
      '',
    ].join('\n')
  })
  .join('\n')

const doc = `# 行为树动作 / 条件参数参考

> 本文档由 \`behavior/actions.js\` 的元数据自动生成，与代码保持一致。
> 用途：作为 **agentic-buddies-backend \`behavior_tree\` 表** 录入时的参数手册，
> 以及 Harness 核心输出 \`<behavior>\` 时的格式约定。

## 节点 JSON 格式

\`\`\`json
// 动作节点
{"node_type": "action", "action_type": "move_to", "action_params": {"target": "player", "distance": 3}}

// 条件节点
{"node_type": "condition", "condition_type": "has_item", "condition_params": {"item": "oak_log", "count": 3}}

// 组合节点
{"node_type": "sequence", "children": [ ...子节点数组... ]}
{"node_type": "selector", "children": [ ... ]}
{"node_type": "parallel", "children": [ ... ], "parallel_policy": "all_succeed" | "any_succeed"}

// 顶层可直接写节点数组（按 sequence 顺序执行）
[
  {"node_type": "action", "action_type": "move_to", "action_params": {"target": "tree"}},
  {"node_type": "action", "action_type": "collect_block", "action_params": {"block": "oak_log"}}
]
\`\`\`

---

## 动作（Action，共 ${listActions().length} 个）

| 类型 | 中文名 | 说明 |
| --- | --- | --- |
${listActions().map((a) => `| \`${esc(a.type)}\` | ${esc(a.label)} | ${esc(a.description)} |`).join('\n')}

${rows(listActions())}
## 条件（Condition，共 ${listConditions().length} 个）

| 类型 | 中文名 | 说明 |
| --- | --- | --- |
${listConditions().map((c) => `| \`${esc(c.type)}\` | ${esc(c.label)} | ${esc(c.description)} |`).join('\n')}

${rows(listConditions())}
## 行为树录入示例（tree_definition JSONB）

\`\`\`json
{
  "name": "chop_tree",
  "description": "砍一棵橡树",
  "tree_definition": {
    "node_type": "sequence",
    "children": [
      {"node_type": "action", "action_type": "move_to", "action_params": {"target": "tree"}},
      {"node_type": "action", "action_type": "collect_block", "action_params": {"block": "oak_log"}},
      {"node_type": "action", "action_type": "say", "action_params": {"text": "砍好了"}},
      {"node_type": "action", "action_type": "move_to", "action_params": {"target": "player", "distance": 3}}
    ]
  }
}
\`\`\`
`

const out = path.join(__dirname, '..', 'ACTIONS.md')
fs.writeFileSync(out, doc, 'utf8')
console.log(`已生成: ${out}（${doc.length} 字符）`)
