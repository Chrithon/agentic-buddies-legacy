#!/usr/bin/env bash
# agentic-buddies-backend 启动器
#
# 读取 conf.yaml 的 server 段参数（host / port / reload）后启动 uvicorn，
# 不修改任何 Python 代码。在任意目录下均可执行。
#
# 用法：
#   ./run.sh               按 conf.yaml server 段启动
#   ./run.sh --reload      强制热重载（覆盖 conf.yaml 的 reload: false）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 优先使用项目 venv，缺失时回退系统 python
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

# 从 conf.yaml 读取 server 段参数
read -r HOST PORT RELOAD <<< "$("$PYTHON" - << 'EOF'
import yaml

try:
    server = yaml.safe_load(open("conf.yaml"))["server"]
except Exception as exc:
    print(f"读取 conf.yaml 失败: {exc}", file=__import__("sys").stderr)
    raise SystemExit(1)

print(
    server.get("host", "0.0.0.0"),
    server.get("port", 8000),
    str(server.get("reload", False)).lower(),
)
EOF
)"

if [[ "${1:-}" == "--reload" ]]; then
  RELOAD="true"
fi

ARGS=(--host "$HOST" --port "$PORT")
if [[ "$RELOAD" == "true" ]]; then
  ARGS+=(--reload)
fi

echo "[run] conf.yaml → host=$HOST port=$PORT reload=$RELOAD"
exec .venv/bin/uvicorn main:app "${ARGS[@]}"
