# Agentic Buddies 服务启动指南

> 四模块服务启动、配置与验证说明。推荐启动顺序：**backend → core → mineflayer-demo**；Minecraft 服务器需先在线（专用服务器默认 25565，并设置 `online-mode=false`；或把 `MC_PORT` 设为客户端 LAN 的实际端口）。

## 目录约定

以下命令假设四个模块目录并列在同一个仓库根目录，例如：

```text
agentic-buddies/
├── agentic-buddies-backend/
├── agentic-buddies-core/
├── agentic-buddies-dashboard/
└── agentic-buddies-mineflayer-demo/
```

从仓库根目录执行本文命令；若从某个模块目录内部执行，请把 `cd agentic-buddies-xxx` 改为 `cd ../agentic-buddies-xxx`。

## 模块与端口总览

| 模块 | 角色 | 端口 | 默认地址 |
|---|---|---|---|
| agentic-buddies-backend | 管理后台 API（FastAPI + PostgreSQL） | 8000 | http://localhost:8000 |
| agentic-buddies-core | Harness 对话引擎（FastAPI + pydantic-ai + TeleMem 可选） | 8001 | http://localhost:8001 |
| agentic-buddies-dashboard | 管理面板（Vue3 + Vite dev server） | 5173 | http://localhost:5173 |
| agentic-buddies-mineflayer-demo | Minecraft NPC 机器人（mineflayer + express） | 3000 | http://localhost:3000 |
| Minecraft 服务器 | 游戏服务器（外部依赖） | 25565 | localhost |

---

## 1. agentic-buddies-backend（管理后台 API）

```bash
cd agentic-buddies-backend

# 依赖安装（首次或依赖变更时；会创建 .venv，run.sh 依赖它）
uv sync

# 首次运行：从模板创建本地配置（conf.yaml / .env 均已被 .gitignore 忽略）
cp conf.yaml.example conf.yaml
cp .env.example .env

# 编辑 .env，至少填写 DATABASE_URL（需与 core/conf.yaml 的 database 段一致）

# 启动（读取 conf.yaml 的 server 段参数：host/port/reload）
./run.sh                 # 按 conf.yaml 配置启动
./run.sh --reload        # 强制热重载（覆盖 conf.yaml 的 reload: false）
```

**配置**（`.env` 文件）：

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | PostgreSQL 连接串（如 `postgresql+asyncpg://user:pass@localhost:5432/ab_database`） |
| `SECRET_KEY` | JWT 签名密钥。**不配置则每次启动随机生成，重启后所有 token 失效** |
| `CORS_ORIGINS` | 允许的前端源（逗号分隔，默认仅 `localhost:5173`；生产必须配置具体域名） |

`conf.yaml` 已加入 `.gitignore`，仓库只保留 `conf.yaml.example`；`server` 段驱动 `host/port/reload`，`auth` 段保存本地默认重置密码。数据库连接、JWT 密钥、CORS 仍在 `.env`。

| 段 | 关键项 | 说明 |
|---|---|---|
| `server` | `host` / `port` / `reload` | 服务启动参数 |
| `auth` | `default_reset_password` | 管理员重置用户密码后的默认密码；留空则重置接口失败关闭 |

**验证**：

```bash
curl http://localhost:8000/           # 服务信息
curl http://localhost:8000/api/npcs/  # NPC 列表（无鉴权接口）
```

---

## 2. agentic-buddies-core（Harness 对话引擎）

```bash
cd agentic-buddies-core

# 首次运行：复制本地配置（conf.yaml 已被 .gitignore 忽略）
cp conf.yaml.example conf.yaml
# 编辑 conf.yaml：database / llm_router / telemem / memory 等

# 依赖安装（首次或依赖变更时）
uv sync

# 启动（读取 conf.yaml 的 server 段参数：host/port/reload）
./run.sh                 # 按 conf.yaml 配置启动
./run.sh --reload        # 强制热重载（覆盖 conf.yaml 的 reload: false）

# 等价方式：python main.py（同样读取 conf.yaml）
# .venv/bin/python main.py
```

> ⚠️ **不要直接 `uvicorn main:app`**：uvicorn CLI 不读取 conf.yaml 的 `server.port`（默认 8000），会与 backend 冲突。请用 `./run.sh` 或 `python main.py`（二者都会读取 conf.yaml 的 host/port/reload 参数）。

**配置**（`conf.yaml`）：

| 段 | 关键项 | 说明 |
|---|---|---|
| `mock` | `true/false` | true=跳过真实 LLM 调用（无密钥时验证管线用）；仍需要 PostgreSQL（NPC/词库/日志） |
| `memory` | `enabled: false` | 默认关闭 TeleMem；改为 true 才初始化长期记忆 |
| `server` | `port: 8001` | 服务端口 |
| `database` | PostgreSQL 连接 | 与 backend 同一数据库 |
| `telemem` | LLM / embedder / FAISS | 仅在 `memory.enabled: true` 时需要真实 API Key |
| `llm_router` | 路由模型 | 任务复杂度分类模型 |
| `content_moderation` | `mode: local/cloud` | local=word_list+block_policy 词库拦截；cloud=阿里云 TextModerationPlus（需 SDK + AccessKey） |
| `npc_pool` | `max_concurrency: 5` | 并发上限 |

**注意**：
- `memory.enabled: false`（默认）不会连接 TeleMem；只有改为 `true` 才会初始化 FAISS 记忆并需要 `telemem` 密钥。
- 内容审核 cloud 模式需要 `alibabacloud-green20220302` + 阿里云 AK/SK；当前 SDK 是硬依赖，正常 `uv sync` 会安装。缺 AK/SK 时 `_moderate_aliyun` 当前会 fail-open（放行），不建议依赖；local 模式不受影响。

**验证**：

```bash
curl http://localhost:8001/health                          # {"status":"ok","service":"harness-core"}
curl http://localhost:8001/api/npcs/enabled                # 已启用 NPC 列表（供 mineflayer 读取）

# 对话接口直测（npc_id 需存在；core 本身不校验 is_enabled，mineflayer 只加载已启用 NPC）
curl -X POST http://localhost:8001/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"npc_id":15,"player_input":"你好","player_uuid":"e98509dc-4ea5-4029-8d25-eed1759d752c"}'
```

---

## 3. agentic-buddies-mineflayer-demo（NPC 机器人）

```bash
cd agentic-buddies-mineflayer-demo

# 依赖安装（首次）
npm install

# 启动（index.js 原生读取 conf.yaml；run.sh 负责校验/展示配置并启动）
./run.sh                 # 启动 NPC 机器人
NPC_ID=15 ./run.sh       # 指定 NPC（或改 conf.yaml 的 npc.id）
```

**配置**（`conf.yaml`，优先级：环境变量 > conf.yaml > 默认值）：

| 段 | 关键项 | 默认值 | 说明 |
|---|---|---|---|
| `core` | `api_url` / `chat_timeout_ms` | `http://localhost:8001` / 90000 | Harness 核心地址 |
| `backend` | `api_url` | `http://localhost:8000` | 管理端地址 |
| `minecraft` | `host` / `port` / `version` | `localhost` / `25565` / 自动协商 | 目标 Minecraft 服务器 |
| `npc` | `id` | 未设置 | 设置后只加载指定 NPC；未设置时加载全部已启用 NPC（对应 npcs 表） |
| `http` | `port` | `3000` | 控制接口端口 |
| `runtime` | `reconnect_delay_ms` / `max_queue` | 8000 / 5 | 断线重连间隔 / 消息队列上限 |

> bot 用户名取 `npcs.name` 并截断到 16 字符；游戏内 `@` 时请使用截断后的用户名。  
> Minecraft 服务器需允许离线登录（`online-mode=false`）；若用客户端 LAN，请把 `minecraft.port` / `MC_PORT` 设为实际端口。

**启动行为**：
1. 从 core 拉取已启用 NPC 列表；**无已启用 NPC → 提示并在管理面板启用后重试**（退出码 1）
2. 配置的 `npc.id` 不在已启用列表 → 提示可用的 NPC 并退出
3. bot 用户名**自动取 npcs 表的 name 字段**（如 knight），conf.yaml 的 username 仅兜底
4. 进入游戏后监听聊天：玩家 `@knight 内容` 触发对话管线

**环境变量覆盖**：`CORE_URL`、`BACKEND_URL`、`MC_HOST`、`MC_PORT`、`MC_USERNAME`、`MC_PASSWORD`、`MC_AUTH`、`NPC_ID`、`HTTP_PORT` 等。

**验证**：

```bash
curl http://localhost:3000/health     # bot 在线状态
curl http://localhost:3000/status     # 位置/状态机/队列/会话数

# 外部驱动一条消息（全链路：demo → core → LLM → 回复 + 日志落库）
curl -X POST http://localhost:3000/api/message \
  -H 'Content-Type: application/json' \
  -d '{"username":"Steve","player_input":"你好，骑士","player_uuid":"e98509dc-4ea5-4029-8d25-eed1759d752c"}'
```

---

## 4. agentic-buddies-dashboard（管理面板，可选）

```bash
cd agentic-buddies-dashboard

# 依赖安装（首次）
npm install

# 开发模式
npm run dev
```

- 访问 `http://localhost:5173`，登录后管理 NPC / 世界观 / 行为树 / 拦截策略 / 用户等
- 开发模式通过 vite 代理将 `/api` 转发到 backend（8000），无需额外配置

---

## 首次初始化（只做一次）

### 1. 数据库

`schema.sql` 位于仓库根目录，基准版本为 PostgreSQL 17。

```bash
# 以 ab_admin / ab_database 为例；请与 backend/.env、core/conf.yaml 保持一致
createdb -h localhost -U ab_admin -O ab_admin ab_database
psql -h localhost -U ab_admin -d ab_database -f schema.sql
```

> 如果 `ab_admin` 角色不存在，先用超级用户创建：`CREATE ROLE ab_admin LOGIN PASSWORD 'change-me';` 和 `CREATE DATABASE ab_database OWNER ab_admin;`。用户名/库名/密码不是固定的，按你的环境调整。

> 如果本机没有 `psql` / `createdb`，可以用 DBeaver 执行 `schema.sql`，或使用 Docker 中 PostgreSQL 的 `psql`。

当前仓库**不包含 seed.sql**，导入后数据库是空的。需要自行创建：

- 初始管理员：`users.is_enabled=true`、`users.is_admin=true`，`password_hash` 为 bcrypt；
- 至少一个 `worlds` 记录；
- 至少一个 `npcs` 记录，`is_enabled=true`，`owner` 指向管理员，`related_world` 指向 world；
- 需要真实 LLM 时，`llm_providers` 中要有与 `npcs.model_config` 匹配的模型。

否则 dashboard 无法登录，mineflayer 会因“没有已启用的 NPC”退出。

> 建议先创建管理员，然后登录 dashboard 创建 world / NPC 并启用；NPC 的 `name` 会作为 Minecraft 用户名，建议使用 3–16 位字母/数字/下划线。

### 2. 依赖与本地配置

```bash
cd agentic-buddies-backend
uv sync
cp conf.yaml.example conf.yaml
cp .env.example .env
# 编辑 .env，至少填 DATABASE_URL

cd ../agentic-buddies-core
cp conf.yaml.example conf.yaml
# 编辑 conf.yaml：database / llm_router / memory 等
# 无 LLM Key 时可把 mock 改为 true；memory.enabled 默认 false
uv sync

cd ../agentic-buddies-dashboard
npm install

cd ../agentic-buddies-mineflayer-demo
npm install

cd ..   # 回到仓库根目录
```

## 完整启动流程（推荐顺序）

> 先完成上面的“首次初始化”。如果使用已有的数据库/管理员/NPC，可跳过第 1 步。

```bash
# 0. 前置：Minecraft 服务器在线（专用服务器 25565 + online-mode=false，或设置 MC_PORT）、PostgreSQL 运行
# 在仓库根目录执行

# 1. 后端（conf.yaml 驱动）
cd agentic-buddies-backend
./run.sh &

# 2. 核心引擎（conf.yaml 驱动）
cd ../agentic-buddies-core
./run.sh &

# 3. NPC 机器人（conf.yaml 驱动，需先有已启用 NPC）
cd ../agentic-buddies-mineflayer-demo
./run.sh &

# 4.（可选）管理面板
cd ../agentic-buddies-dashboard
npm run dev
```

## 停止服务

```bash
# 需要安装 lsof
kill $(lsof -ti:8000)   # backend
kill $(lsof -ti:8001)   # core
kill $(lsof -ti:3000)   # mineflayer-demo
kill $(lsof -ti:5173)   # dashboard
```

## 常见问题排查

| 现象 | 原因 | 处理 |
|---|---|---|
| demo 提示"没有已启用的 NPC" | npcs 表无 `is_enabled=true` 记录 | 面板 → NPC 管理 → 启用目标 NPC |
| demo 提示"配置的 NPC #x 不存在或未启用" | `npc.id` 与已启用列表不符 | 修改 conf.yaml 或启用对应 NPC |
| backend 启动报 `DATABASE_URL 环境变量未设置` | 没有 `.env` 或未填 `DATABASE_URL` | `cp .env.example .env` 并填写 |
| backend `run.sh` 报 `.venv/bin/uvicorn` 不存在 | 未安装依赖 | 在 backend 执行 `uv sync` |
| core 启动报 `conf.yaml` 不存在 | 未复制本地配置 | `cp conf.yaml.example conf.yaml` |
| 导入 schema 报 `transaction_timeout` | 使用了 PostgreSQL 16 或更早 | 使用 PG17+，或删除 `schema.sql` 中的 `SET transaction_timeout = 0;` |
| dashboard 无法登录 / 没有可用账号 | `users` 表为空，或 `is_enabled`/`is_admin` 未设为 true | 按“首次初始化”创建管理员 |
| core 启动报 `alibabacloud_tea_*` 或 SDK 缺失 | 手动移除了阿里云 SDK；`core.py` 顶层导入 tea 模块 | 执行 `uv sync` 恢复依赖；`mode: local` 不能绕过 import 错误 |
| cloud 模式不拦截 | AK/SK 未配置（SDK 已安装）；`_moderate_aliyun` 当前 fail-open 放行 | 配置 `cloud.access_key_id/secret`，或改用 `mode: local` |
| 对话返回"对不起，我无法回答"且日志 flagged=true | 内容审核拦截（命中黑名单/云端拦截） | 查看 word_list / block_policy 配置 |
| 后端重启后全员 token 失效 | `SECRET_KEY` 未配置 | `.env` 配置固定 SECRET_KEY |
| mineflayer 连不上 Minecraft | `online-mode=true` 或端口不对 | 专用服务器设 `online-mode=false`；客户端 LAN 用实际 `MC_PORT` |
| 游戏内 @NPC 无反应 | demo 未连接 / 玩家未 @ 对名字 / 名字被截断 | 检查 demo 日志与 `@` 名字（= `npcs.name` 截断到 16 字符） |

## 相关文档

- 行为树录入参数参考：`agentic-buddies-mineflayer-demo/ACTIONS.md`
- 核心引擎代码结构：`agentic-buddies-core/README.md`（`core/core.py` 8 步管线）
