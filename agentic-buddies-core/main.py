# main.py — Harness 核心 FastAPI 入口
import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import text

from core.pool import NPCPool
from core.session import SessionManager
from memory.memory import _get_memory, check_global_scope, memory_enabled
from sql.sql_connect import _engine, _async_session_factory


# ============================================================
# 服务配置（conf.yaml → server 段）
# ============================================================

_conf = yaml.safe_load(
    (Path(__file__).resolve().parent / "conf.yaml").read_text()
).get("server", {})


# ============================================================
# API 请求/响应模型
# ============================================================

class ChatAPIRequest(BaseModel):
    npc_id: int
    player_input: str
    session_uuid: Optional[str] = None
    player_uuid: Optional[str] = None


class ChatAPIResponse(BaseModel):
    session_uuid: str
    session_new: bool = False
    npc_response: str
    behavior_tree: Optional[str] = None
    latency_ms: int
    flagged: bool = False


# ============================================================
# 生命周期管理
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的资源管理"""
    logger.info("Harness 核心启动中...")

    # 1. TeleMem 长期记忆（legacy 默认关闭：不初始化，无需密钥即可启动）
    if memory_enabled():
        _get_memory()
        logger.info("TeleMem 连接成功")
        try:
            global_hits = await check_global_scope()
            if global_hits:
                logger.warning(
                    "检测到 {} 条 events 全局作用域记忆，存在跨 NPC 串流风险（检索侧已过滤）",
                    global_hits,
                )
        except Exception as exc:
            logger.warning("记忆作用域自检失败（{}），跳过", type(exc).__name__)
    else:
        logger.info("长期记忆已关闭（memory.enabled=false），跳过 TeleMem 初始化")

    # 2. Worker Pool（并发数由 conf.yaml npc_pool.max_concurrency 控制）
    pool = NPCPool()
    app.state.pool = pool
    logger.info("Worker Pool 已就绪")

    # 3. 会话管理器（超时/轮数上限由 conf.yaml session 段控制）
    session_manager = SessionManager()
    app.state.session_manager = session_manager
    logger.info("Session Manager 已就绪")

    yield

    # 关闭时释放资源
    logger.info("正在释放资源...")
    await _engine.dispose()
    logger.info("资源已释放")


# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(
    title="Agentic Buddies Harness",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置（允许 Mineflayer 等前端调用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# API 路由
# ============================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "harness-core"}


@app.get("/api/npcs/enabled")
async def list_enabled_npcs():
    """列出所有已启用的 NPC（供 Mineflayer 等引擎侧启动时读取）"""
    async with _async_session_factory() as session:
        result = await session.execute(
            text("""
                SELECT id, name
                FROM npcs
                WHERE is_enabled = true
                ORDER BY id
            """)
        )
        return [
            {"id": row.id, "name": row.name}
            for row in result.fetchall()
        ]


@app.post("/api/chat", response_model=ChatAPIResponse)
async def chat(request: ChatAPIRequest):
    """NPC 对话接口：接收玩家输入，返回 NPC 回复"""
    pool: NPCPool = app.state.pool
    session_manager: SessionManager = app.state.session_manager

    # 会话校验：过期/超轮数 → 自动开新会话（返回新 session_uuid）
    session_uuid, is_new = session_manager.get_or_create(request.session_uuid)

    start = time.monotonic()
    try:
        reply = await asyncio.wait_for(
            pool.process(
                npc_id=request.npc_id,
                session_uuid=session_uuid,
                user_input=request.player_input,
                player_uuid=request.player_uuid,
            ),
            timeout=90.0,   # 复杂任务并行双 Agent（编排+回复）耗时更长，放宽至 90s
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="NPC 响应超时")

    latency_ms = int((time.monotonic() - start) * 1000)
    return ChatAPIResponse(
        session_uuid=session_uuid,
        session_new=is_new,
        npc_response=reply.speak,
        behavior_tree=reply.behavior,
        latency_ms=latency_ms,
        flagged=reply.flagged,
    )


@app.get("/api/npc/{npc_id}/state")
async def get_npc_state(npc_id: int):
    """获取 NPC 当前状态（供 Mineflayer 查询）"""
    return {
        "npc_id": npc_id,
        "status": "idle",
        "current_action": None,
        "session_active": False,
    }


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=_conf.get("host", "0.0.0.0"),
        port=_conf.get("port", 8001),
        reload=_conf.get("reload", False),
    )
