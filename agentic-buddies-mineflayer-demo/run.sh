#!/usr/bin/env bash
# agentic-buddies-mineflayer-demo 启动器
#
# 读取 conf.yaml 关键参数并启动 node index.js（index.js 内部已按 conf.yaml 加载配置，
# 此处仅展示并校验配置可读）。
#
# 用法：
#   ./run.sh               启动 NPC 机器人
#   NPC_ID=15 ./run.sh     指定 NPC（也可改 conf.yaml 的 npc.id）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 校验 conf.yaml 可解析并展示关键参数（node + js-yaml）
node -e "
const yaml = require('js-yaml');
const fs = require('fs');
let c = {};
try {
  c = yaml.load(fs.readFileSync('conf.yaml', 'utf8')) || {};
} catch (e) {
  console.error('[run] 读取 conf.yaml 失败:', e.message);
  process.exit(1);
}
const core = (c.core && c.core.api_url) || 'http://localhost:8001';
const mc = (c.minecraft && c.minecraft.host) || 'localhost';
const port = (c.minecraft && c.minecraft.port) || 25565;
const http = (c.http && c.http.port) || 3000;
const npc = (c.npc && c.npc.id) || '未配置(启动时自动取第一个已启用NPC)';
console.log('[run] conf.yaml → core=' + core + ' mc=' + mc + ':' + port + ' http=' + http + ' npc=' + npc);
"

exec node index.js
