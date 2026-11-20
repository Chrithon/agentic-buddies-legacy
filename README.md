# AgenticBuddies（Legacy · v1）

> [!CAUTION]
> ⚠️ 本项目已即将归档，不再维护，**不再接受 PR / Issue**；仅供考古与参考。

> 一句话：给 Minecraft 的 AI 同伴系统——玩家在面板里配置 NPC，核心引擎驱动对话与行为，Mineflayer 接入服务器。

## 这是什么？
AgenticBuddies 全套源代码（适用于 Mineflayer），由四个模块组成，按功能分三大块：

| 块 | 模块 | 技术栈 | 端口 |
|---|---|---|---|
| 面板 | `agentic-buddies-dashboard` + `agentic-buddies-backend` | Vue 3 + FastAPI + PostgreSQL | 5173 / 8000 |
| 核心 | `agentic-buddies-core` | PydanticAI + FastAPI + TeleMem | 8001 |
| 接入端 | `agentic-buddies-mineflayer-demo` | Mineflayer + Express | 3000 |

## 如何启动？
见 [STARTUP.md](STARTUP.md)

## 局限性和问题
目前该项目存在以下问题
1. 只做了初步的 TeleMem 接入，记忆未做完全隔离。
2. 只考虑了单人游戏环境（需要在玩家端启动局域网游戏）。
3. 受当时技术限制，未完全模块化。
4. 时间有限，仅适配 PostgreSQL，未适配本地 SQLite。
5. 决策路由耗时较长。
6. 采用阻塞式编排，未实现流式输出（同期育碧 Teammates 通过流式传输把响应从约 3s 压到 1.5s）。

## 许可证
MIT

## 接下来做什么？
v1 是论文期产物，已冻结；v2 参考 DeepSeek Harness 与 Cordis 思想重构，见 v2 仓库（待发布）。
