"""记忆操作入口 — TeleMem（Mem0 兼容），配置由 conf.yaml 驱动

安全约定（legacy 版本）：
- ``memory.enabled=false``（默认）时完全不初始化 TeleMem，也不读不写记忆，
  因此无需 embedding / LLM 密钥即可启动。
- ``memory.enabled=true`` 且 ``memory.player_isolation=true``（默认）时，
  强制玩家级作用域 ``npc{id}:p{uuid}``；缺少 player_uuid 则跳过本轮记忆，
  避免同一 NPC 的记忆在玩家之间串流。
- 检索结果会过滤 telemem 的全局 ``events`` 作用域
  （telemem 内部分检索会强制合并该作用域，可能造成跨 NPC 串流）。
"""

import asyncio
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import yaml
from loguru import logger

from core.models.models import MemoryContext, TeleMemResponse

if TYPE_CHECKING:  # 仅类型检查时导入，运行时不加载 mem0 / telemem
    import telemem as mem0

_conf_path = Path(__file__).resolve().parents[1] / "conf.yaml"
_conf = yaml.safe_load(_conf_path.read_text())
_telemem_config = _conf.get("telemem", {})
_mem_cfg = _conf.get("memory", {})

# 长期记忆总开关：legacy 默认关闭（配置缺失时同样视为关闭）
_MEMORY_ENABLED = bool(_mem_cfg.get("enabled", False))
# 玩家级隔离：开启记忆时默认强制，避免同 NPC 的跨玩家记忆串流
_PLAYER_ISOLATION = bool(_mem_cfg.get("player_isolation", True))

# telemem 的全局作用域：user_id 为空时写入，且会被所有检索合并
_GLOBAL_SCOPE = "events"

_memory: Optional["mem0.Memory"] = None
_init_error: Optional[str] = None


def memory_enabled() -> bool:
    """长期记忆是否启用（供 main.py 决定是否初始化 TeleMem）"""
    return _MEMORY_ENABLED


def _scope_user_id(npc_id: int, player_uuid: Optional[str]) -> Optional[str]:
    """构造记忆作用域标识。

    Returns:
        作用域字符串；``None`` 表示本轮跳过记忆（既不写入也不检索）。
    """
    if not _MEMORY_ENABLED:
        return None
    if not _PLAYER_ISOLATION:
        return str(npc_id)
    if not player_uuid:
        logger.warning(
            "memory.player_isolation=true 但缺少 player_uuid，跳过本轮记忆（NPC {}）",
            npc_id,
        )
        return None
    return f"npc{npc_id}:p{player_uuid}"


def _resolve_env(value: str) -> str:
    """展开 ${VAR} 形式的占位符为环境变量值"""
    import re

    def _replace(m: re.Match) -> str:
        return os.getenv(m.group(1), m.group(0))
    return re.sub(r"\$\{(\w+)\}", _replace, value)


def _build_telemem_config():
    """将 conf.yaml 的 telemem 段展开为 TeleMemoryConfig 对象（依赖惰性导入）"""
    from mem0.embeddings.configs import EmbedderConfig
    from mem0.llms.configs import LlmConfig
    from mem0.vector_stores.configs import VectorStoreConfig
    from telemem.configs import TeleMemoryConfig

    llm = _telemem_config.get("llm", {})
    embedder = _telemem_config.get("embedder", {})
    vs = _telemem_config.get("vector_store", {})

    def resolve(cfg: dict[str, Any]) -> dict[str, Any]:
        return {k: _resolve_env(v) if isinstance(v, str) else v for k, v in cfg.items()}

    vs_config = resolve(vs.get("config", {}))

    return TeleMemoryConfig(
        llm=LlmConfig(
            provider=llm.get("provider", "openai"),
            config=resolve(llm.get("config", {})),
        ),
        embedder=EmbedderConfig(
            provider=embedder.get("provider", "openai"),
            config=resolve(embedder.get("config", {})),
        ),
        vector_store=VectorStoreConfig(
            provider=vs.get("provider", "faiss"),
            config={
                "collection_name": vs_config.get("collection_name", "telemem"),
                "path": vs_config.get("path"),
                "embedding_model_dims": vs_config.get("embedding_model_dims", 1024),
            },
        ),
        history_db_path=vs_config.get("history_db_path", "db/history.db"),
        buffer_size=vs_config.get("buffer_size", 64),
        similarity_threshold=vs_config.get("similarity_threshold", 0.95),
    )


def _get_memory() -> "mem0.Memory":
    """延迟初始化 TeleMem Memory 实例（仅在 memory.enabled=true 时调用）"""
    global _memory, _init_error
    if _memory is None and _init_error is None:
        try:
            import telemem as mem0

            config = _build_telemem_config()
            _memory = mem0.Memory(config=config)
            # 给 mem0 底层 OpenAI 客户端注入超时：summary 生成/嵌入请求若响应慢，
            # 会同步阻塞 asyncio 线程池导致整个核心卡死（此前已出现）
            for llm_obj in (_memory.llm, getattr(_memory, "embedding_model", None)):
                client = getattr(llm_obj, "client", None)
                if client is not None and hasattr(client, "timeout"):
                    try:
                        client.timeout = 15.0
                    except Exception:
                        pass
            logger.info("TeleMem memory backend initialized")
        except Exception as exc:
            _init_error = str(exc)
            logger.warning("TeleMem init deferred: {}", exc)
            raise RuntimeError(
                "TeleMem requires OPENAI_API_KEY or valid telemem config in conf.yaml."
            ) from exc
    if _init_error is not None:
        raise RuntimeError(f"TeleMem not available: {_init_error}")
    return _memory


# 往Telemem添加记忆
async def add_memory(
    messages: list[dict[str, str]],
    *,
    npc_id: int,
    player_uuid: Optional[str] = None,
    run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> TeleMemResponse:
    """
    将对话轮次写入记忆系统

    Args:
        messages: [{"role": "user/assistant", "content": "..."}]
        npc_id: NPC ID（与 player_uuid 一起构成记忆作用域）
        player_uuid: 玩家 UUID；player_isolation 开启时必填
        run_id: 会话标识（映射 Mem0 的 run_id → 项目 session_uuid）
        agent_id: 可选，系统级 agent 标识
        metadata: 附加元数据（npc_id / player_uuid / run_id 会自动补齐）

    Returns:
        {"results": [{"id":..., "memory":..., "event":"ADD"}]}

    记忆关闭、或缺少 player_uuid 时直接返回空结果（不写入、不报错）。
    """
    user_id = _scope_user_id(npc_id, player_uuid)
    if user_id is None or user_id == _GLOBAL_SCOPE:
        return TeleMemResponse()

    merged_metadata = dict(metadata or {})
    merged_metadata.setdefault("npc_id", str(npc_id))
    if player_uuid:
        merged_metadata.setdefault("player_uuid", player_uuid)
    if run_id:
        merged_metadata.setdefault("session_uuid", run_id)

    result = await asyncio.to_thread(
        _get_memory().add,
        messages=messages,
        user_id=user_id,
        run_id=run_id,
        agent_id=agent_id,
        metadata=merged_metadata,
    )
    logger.debug(
        "TeleMem.add_memory 完成（scope={}, run_id={}），结果 {} 条",
        user_id, run_id, len(result.get("results", [])),
    )
    return TeleMemResponse(**result)


# 检索相关记忆
async def search_memory(
    query: str,
    *,
    npc_id: int,
    player_uuid: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 10,
    threshold: Optional[float] = None,
) -> TeleMemResponse:
    """
    从记忆中检索相关历史

    Args:
        query: 自然语言查询文本
        npc_id: NPC ID（与 player_uuid 一起构成记忆作用域）
        player_uuid: 玩家 UUID；player_isolation 开启时必填
        run_id: 会话标识（传则按会话过滤，默认不限会话）
        limit: 最大返回条数
        threshold: 相似度阈值 (0~1)，不传则自动调优

    Returns:
        {"results": [{"id":..., "memory":..., "score":...}]}

    记忆关闭、或缺少 player_uuid 时返回空结果。
    结果会过滤 telemem 的全局 ``events`` 作用域，防止跨 NPC 串流。
    """
    user_id = _scope_user_id(npc_id, player_uuid)
    if user_id is None or user_id == _GLOBAL_SCOPE:
        return TeleMemResponse()

    _search_start = time.monotonic()
    result = await asyncio.to_thread(
        _get_memory().search,
        query=query,
        user_id=user_id,
        run_id=run_id,
        limit=limit,
        threshold=threshold,
    )
    logger.debug(
        "TeleMem.search_memory 完成（scope={}, run_id={}, query={!r:.60}），耗时 {:.1f}s",
        user_id, run_id, query, time.monotonic() - _search_start,
    )
    # 防御：telemem 偶发返回畸形结果（如 None）时降级为空，不中断对话
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        logger.warning("记忆检索返回异常结构，降级为空结果")
        result = {"results": []}

    # 作用域白名单：只保留自身作用域（以及未标注 source 的旧数据）。
    # telemem 检索会强制合并 "events" 全局作用域，若该作用域有数据会注入
    # 所有 NPC 的上下文；这里同时兜底其它作用域混入的情况。
    raw_results = result.get("results") or []
    result["results"] = [
        item for item in raw_results
        if not isinstance(item, dict) or item.get("source") in (None, user_id)
    ]
    dropped = len(raw_results) - len(result["results"])
    if dropped:
        logger.warning(
            "已过滤 {} 条非本作用域记忆（scope={}，防止跨 NPC/跨玩家串流）",
            dropped, user_id,
        )
    return TeleMemResponse(**result)


async def check_global_scope(limit: int = 1) -> int:
    """自检：返回 ``events`` 全局作用域可见的记忆条数（正常应为 0）。

    记忆未启用或初始化失败时返回 0，不抛出异常（仅用于启动告警）。
    """
    if not _MEMORY_ENABLED:
        return 0
    try:
        result = await asyncio.to_thread(
            _get_memory().search,
            query="selfcheck",
            user_id=None,
            limit=limit,
        )
    except Exception as exc:
        logger.warning("全局作用域自检失败（{}），跳过", type(exc).__name__)
        return 0
    if not isinstance(result, dict):
        return 0
    hits = [
        item for item in (result.get("results") or [])
        if isinstance(item, dict) and item.get("source") == _GLOBAL_SCOPE
    ]
    return len(hits)


# 构建上下文快照
async def build_context(
    session_uuid: str,
    npc_id: int,
    query: str,
    *,
    player_uuid: Optional[str] = None,
    limit: int = 10,
) -> MemoryContext:
    """
    为 NPC 对话组装记忆上下文快照

    Args:
        session_uuid: 会话 UUID（仅用于上下文快照标记，不参与检索过滤）
        npc_id: NPC ID
        query: 当前玩家输入，用于语义检索相关记忆
        player_uuid: 玩家 UUID；player_isolation 开启时必填
        limit: 检索条数

    Returns:
        MemoryContext（含 history + session_uuid）

    注意：检索不传 run_id —— run_id 对应单次会话，若按其过滤，
    新会话将永远检索不到历史记忆，长期记忆（跨会话）失效。
    记忆关闭或缺 player_uuid 时返回空上下文。
    """
    response = await search_memory(
        query=query,
        npc_id=npc_id,
        player_uuid=player_uuid,
        limit=limit,
    )
    return MemoryContext(
        session_uuid=session_uuid,
        history=response.results,
    )
