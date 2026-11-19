import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import yaml
from alibabacloud_tea_openapi import models as aliyun_openapi_models
from alibabacloud_tea_util import models as aliyun_tea_util_models
from loguru import logger
from pydantic import BaseModel, Field, model_validator
from pydantic_ai import Agent, NativeOutput, PromptedOutput
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai_shields import NoRefusals, PromptInjection, SecretRedaction
from sqlalchemy import text

from core.models.models import MemoryContext
from core.modules.pii import sanitize as pii_sanitize
from memory.memory import add_memory, build_context, memory_enabled
from sql.sql_connect import _async_session_factory


def _resolve_env(value: str) -> str:
    """展开 conf.yaml 中的 ${VAR} 占位符"""

    def _replace(m: re.Match) -> str:
        return os.getenv(m.group(1), m.group(0))
    return re.sub(r"\$\{(\w+)\}", _replace, value)


_conf_path = Path(__file__).resolve().parents[1] / "conf.yaml"
_conf = yaml.safe_load(_conf_path.read_text())

# Mock 模式：跳过真实 LLM / TeleMem 调用（conf.yaml → mock: true）
_MOCK = bool(_conf.get("mock", False))

# =======================================================================
# 1. 过滤个人信息（身份证号、银行卡号、中国大陆手机号）
# =======================================================================


def filter_input(user_input: str) -> str:
    """对玩家输入做 PII 脱敏，返回替换后的文本。"""
    result = pii_sanitize(user_input)
    return result.text


# =======================================================================
# 2. 从Telmem和知识库读取NPC记忆、NPC提示词、世界观提示词和世界观
#    知识库
# =======================================================================


@dataclass
class NPCContext:
    """组装后的 NPC 完整上下文（步骤 2 输出）"""
    character_prompt: str | None = None          # 角色设定
    world_prompt: str | None = None              # 世界观设定
    memory: MemoryContext | None = None          # TeleMem 检索的记忆快照
    world_lore: str = ""                         # 世界观知识库检索文本（Dify retrieve 兼容）
    kb_config: "WorldKbConfig | None" = None     # 世界观知识库 API 配置


class WorldKbConfig(BaseModel):
    """世界观知识库 API 配置（对齐 worlds 表 kb_api_* 字段，Dify 知识库兼容）。

    - kb_api_url:     知识库 API 基地址（如 https://api.dify.ai/v1）
    - kb_api_headers: 请求头（如 {"Authorization": "Bearer xxx"}）
    - kb_api_timeout: 请求超时（秒）
    - kb_api_data:    请求数据（Dify retrieve 接口：
                      dataset_id 必填；retrieval_model / attachment_ids 可选）
    """
    kb_api_url: str | None = None
    kb_api_headers: dict = Field(default_factory=dict)
    kb_api_timeout: int = 30
    kb_api_data: dict = Field(default_factory=dict)


class KnowledgeChunk(BaseModel):
    """知识库检索命中的分段（Dify records[].segment 兼容）"""
    content: str
    score: float | None = None
    document_name: str | None = None


_USER_INPUT_PLACEHOLDER = "[user_input]"


def _substitute_user_input(data: dict, query: str) -> dict:
    """将请求数据中的 [user_input] 占位符替换为用户输入内容。

    通过 JSON 序列化往返实现深度替换：kb_api_data 任意字段（含嵌套）
    中的 "[user_input]" 都会被替换为玩家输入，便于配置动态请求模板
    （如 external_retrieval_model 的查询模板）。
    序列化失败时原样返回。
    """
    try:
        text = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return data
    text = text.replace(_USER_INPUT_PLACEHOLDER, query)
    try:
        return json.loads(text)
    except ValueError:
        return data


async def retrieve_world_knowledge(
    kb: WorldKbConfig,
    query: str,
) -> list[KnowledgeChunk]:
    """调用世界观知识库检索接口（Dify "从知识库检索分段" API 兼容）。

    POST {kb_api_url}/datasets/{dataset_id}/retrieve
    请求体：query + retrieval_model + attachment_ids（取自 kb_api_data）
    响应：records[].segment.content → KnowledgeChunk 列表

    kb_api_data / kb_api_headers 中的 "[user_input]" 占位符会替换为玩家输入。
    未配置知识库 / 调用失败 → 返回空列表（静默降级，不影响对话主流程）。
    """
    if not kb.kb_api_url:
        return []

    # [user_input] 占位符替换（深度替换 kb_api_data，headers 值替换）
    kb_data = _substitute_user_input(kb.kb_api_data, query)
    # HTTP 头仅允许 ASCII：替换后含非 ASCII（如中文用户输入）的头跳过并告警
    headers: dict = {}
    for key, value in (kb.kb_api_headers or {}).items():
        if not isinstance(value, str):
            continue
        replaced = value.replace(_USER_INPUT_PLACEHOLDER, query)
        try:
            replaced.encode("latin-1")
        except UnicodeEncodeError:
            logger.warning(
                "知识库请求头 {} 含非 ASCII 值（HTTP 头仅支持 ASCII），已忽略该头", key
            )
            continue
        headers[key] = replaced
    headers.setdefault("Content-Type", "application/json")

    dataset_id = kb_data.get("dataset_id") or kb.kb_api_data.get("dataset_id")
    # 兼容两种 kb_api_url 配置：
    # 1) base_url 形式（如 https://api.dify.ai/v1）→ 需配合 kb_api_data.dataset_id 拼接
    # 2) 完整 retrieve URL（如 .../datasets/{id}/retrieve）→ 直接使用
    url = kb.kb_api_url.rstrip("/")
    if dataset_id:
        url = f"{url}/datasets/{dataset_id}/retrieve"
    elif not url.endswith("/retrieve"):
        logger.warning("知识库 URL 无法解析（既非 base_url+dataset_id，也非完整 retrieve URL）")
        return []

    # 构造请求体（对齐 Dify 官方 retrieve 接口：query + attachment_ids + 检索模型配置）
    # - query 支持自定义模板（如 {"query": "关于[user_input]的资料"}），否则用原文
    # - attachment_ids 恒携带（未配置时默认空数组，避免部分版本缺字段报错）
    # - retrieval_model / external_retrieval_model 显式支持
    # - kb_api_data 中其余字段原样透传（dataset_id/query 等已处理字段除外）
    raw_query = kb_data.get("query")
    payload: dict = {
        "query": (raw_query[:250] if isinstance(raw_query, str) else query[:250]),
        "attachment_ids": kb_data.get("attachment_ids") or [],
    }
    for key in ("retrieval_model", "external_retrieval_model"):
        if kb_data.get(key):
            payload[key] = kb_data[key]
    for key, value in kb_data.items():
        if key in ("dataset_id", "query", "attachment_ids", "retrieval_model", "external_retrieval_model"):
            continue
        if value is not None:
            payload[key] = value

    try:
        async with httpx.AsyncClient(timeout=kb.kb_api_timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            logger.warning(
                "世界观知识库检索失败: HTTP {} - {}",
                response.status_code,
                response.text[:120],
            )
            return []
        data = response.json()
    except Exception as exc:
        logger.warning(
            "世界观知识库检索异常: {}（{}）", type(exc).__name__, str(exc)[:150]
        )
        return []

    chunks: list[KnowledgeChunk] = []
    for record in data.get("records", []):
        segment = record.get("segment") or {}
        content = segment.get("content")
        if content:
            chunks.append(
                KnowledgeChunk(
                    content=content,
                    score=record.get("score"),
                    document_name=(segment.get("document") or {}).get("name"),
                )
            )
    return chunks


async def build_npc_context(
    npc_id: int,
    session_uuid: str,
    current_query: str,
    *,
    player_uuid: str | None = None,
) -> NPCContext:
    """
    步骤 2：组装 NPC 对话所需的完整上下文

    来源：
    - DB npcs 表 → character_prompt
    - DB worlds 表 → world_prompt
    - TeleMem → 该 NPC + 当前会话的语义记忆
    - MCP 知识库 → 世界观 lore（后续扩展）
    """
    ctx = NPCContext()

    # ── 2a. 数据库：NPC 提示词 + 关联世界观（含知识库配置） ──
    async with _async_session_factory() as session:
        npc = (await session.execute(
            text("SELECT character_prompt, related_world FROM npcs WHERE id = :id"),
            {"id": npc_id},
        )).fetchone()
        if npc is None:
            raise ValueError(f"NPC {npc_id} not found")

        ctx.character_prompt = npc[0]

        if npc[1] is not None:
            world = (await session.execute(
                text("""
                    SELECT world_prompt, kb_api_url, kb_api_headers, kb_api_timeout, kb_api_data
                    FROM worlds WHERE id = :id
                """),
                {"id": npc[1]},
            )).fetchone()
            if world is not None:
                ctx.world_prompt = world[0]
                ctx.kb_config = WorldKbConfig(
                    kb_api_url=world[1],
                    kb_api_headers=world[2] or {},
                    kb_api_timeout=world[3] or 30,
                    kb_api_data=world[4] or {},
                )

    # ── 2c. 世界观知识库检索（Dify retrieve chunks 兼容，失败静默降级） ──
    if not _MOCK and ctx.kb_config and ctx.kb_config.kb_api_url:
        chunks = await retrieve_world_knowledge(ctx.kb_config, current_query)
        if chunks:
            ctx.world_lore = "\n".join(f"- {c.content}" for c in chunks)
            logger.info("世界观知识库命中 {} 条分段（NPC {}）", len(chunks), npc_id)

    # ── 2b. TeleMem：NPC 记忆检索 ──
    # legacy 安全默认：memory.enabled=false 时不初始化、不检索记忆
    if _MOCK or not memory_enabled():
        ctx.memory = MemoryContext(
            session_uuid=session_uuid,
            history=[],
            summary="(mock) 无历史记忆" if _MOCK else "(memory disabled) 长期记忆已关闭",
        )
    else:
        # 记忆检索（mem0 同步调用跑在线程池，可能被慢响应阻塞）：
        # 超时降级为空记忆，不阻塞对话主流程
        try:
            _mem_start = time.monotonic()
            ctx.memory = await asyncio.wait_for(
                build_context(
                    session_uuid=session_uuid,
                    npc_id=npc_id,
                    query=current_query,
                    player_uuid=player_uuid,
                ),
                timeout=25,
            )
            logger.info(
                "TeleMem 记忆检索命中 {} 条（NPC {}，耗时 {:.1f}s）",
                len(ctx.memory.history), npc_id, time.monotonic() - _mem_start,
            )
            for _mem_item in ctx.memory.history:
                _mem_text = getattr(_mem_item, "memory", None) or _mem_item
                logger.debug(
                    "  TeleMem 命中 [score={}] {}",
                    getattr(_mem_item, "score", "?"),
                    str(_mem_text)[:120],
                )
        except Exception as exc:
            logger.warning("记忆检索失败（{}），使用空记忆（不影响主流程）", type(exc).__name__)
            ctx.memory = MemoryContext(session_uuid=session_uuid, history=[], summary="")

    return ctx



# =======================================================================
# 3. 从数据库读取黑白名单，命中黑名单后按 block_policy 的
#    (category, risk_level) 决定 block/force_block/warning_prompt；
#    alert_enabled 仅表示命中后是否需要人工介入（写入 alert_required），
#    不影响策略本身是否生效。
#    （或使用阿里云提供的云端的内容审核服务）
#    如果检测到敏感词或者阿里云内容审核不通过，则输出兜底回答
# =======================================================================

_mod_cfg = _conf.get("content_moderation", {})


@dataclass
class ModerationResult:
    """内容审核结果（步骤 3 输出）"""
    blocked: bool = False
    filtered_text: str = ""
    fallback: str = ""                          # 拦截时的兜底回答
    warning: str = ""                           # 警告注入（不拦截但附加提示）
    category: str | None = None                 # 命中类别（用于 flagged_category）
    alert_required: bool = False                # 需人工介入/告警（由 alert_enabled 决定）
    hard_rule: bool = False                     # 命中自杀高风险硬规则（跳过 LLM）


# 自杀高风险安全话术（硬编码，不依赖 LLM 生成）：
# 跳出角色扮演 → 确认风险严重性 → 给出现实求助渠道 → 告知记录与专员跟进
SUICIDE_SAFETY_SCRIPT = (
    "我听到你说想自杀，这是一件非常严重的事。我想帮你，但我能做的有限。\n"
    "请你立即拨打全国心理援助热线 12356，或者联系一位你信任的人，让对方陪在你身边。\n"
    "我已经记录了你刚才的情况，稍后会有心理健康专员与你联系，确保有人能及时接应你。\n"
    "你不需要独自承受这一切。"
)


# 阿里云文本审核增强版 SDK（green20220302 / TextModerationPlus）为可选依赖：
# 未安装时仅 cloud 模式不可用，local 模式不受影响。
try:
    from alibabacloud_green20220302 import client as aliyun_green_client
    from alibabacloud_green20220302 import models as aliyun_green_models

    _GREEN_SDK_AVAILABLE = True
except ImportError:
    aliyun_green_client = None
    aliyun_green_models = None
    _GREEN_SDK_AVAILABLE = False
    logger.warning("阿里云文本审核增强版 SDK（alibabacloud_green20220302）未安装，cloud 模式不可用")

_aliyun_client: "aliyun_green_client.Client | None" = None


def _get_aliyun_client() -> "aliyun_green_client.Client | None":
    """惰性创建阿里云文本审核增强版（TextModerationPlus）客户端（连接复用）"""
    global _aliyun_client
    if _aliyun_client is not None:
        return _aliyun_client

    if not _GREEN_SDK_AVAILABLE:
        logger.warning("SDK 未安装，云端审核不可用")
        return None

    cloud_cfg = _mod_cfg.get("cloud", {})
    ak_id = _resolve_env(cloud_cfg.get("access_key_id", ""))
    ak_secret = _resolve_env(cloud_cfg.get("access_key_secret", ""))
    region = cloud_cfg.get("region", "cn-shanghai")

    if not ak_id or not ak_secret or ak_id.startswith("${"):
        logger.warning("阿里云 AccessKey 未配置，云端审核不可用")
        return None

    config = aliyun_openapi_models.Config(
        access_key_id=ak_id,
        access_key_secret=ak_secret,
        region_id=region,
        endpoint="green-cip.cn-shanghai.aliyuncs.com",  # 文本审核增强版端点
    )
    _aliyun_client = aliyun_green_client.Client(config)
    return _aliyun_client


async def _moderate_aliyun(user_text: str) -> ModerationResult:
    """调用阿里云文本审核增强版 TextModerationPlus 接口

    risk_level: high/medium → 直接拦截；low 且命中标签 → 附加警告；否则放行。
    """
    client = _get_aliyun_client()
    if client is None:
        return ModerationResult(filtered_text=user_text)

    scenes = _mod_cfg.get("cloud", {}).get("scenes") or ["llm_query_moderation"]
    request = aliyun_green_models.TextModerationPlusRequest(
        service=scenes[0],
        service_parameters=json.dumps({"content": user_text}, ensure_ascii=False),
    )
    runtime = aliyun_tea_util_models.RuntimeOptions()

    try:
        response = await asyncio.to_thread(
            client.text_moderation_plus_with_options, request, runtime
        )
        body = response.body
    except Exception as exc:
        logger.exception("阿里云内容审核调用失败: {}", exc)
        return ModerationResult(filtered_text=user_text)

    if body.code != 200:
        logger.error("阿里云审核响应异常: code={} message={}", body.code, body.message)
        return ModerationResult(filtered_text=user_text)

    data = body.data
    risk_level = data.risk_level if data else None
    result_items = data.result if data else None
    labels = ",".join(r.label for r in result_items if r.label != "nonLabel") if result_items else None
    descriptions = [r.description for r in result_items if r.description] if result_items else []
    reason = "; ".join(descriptions) if descriptions else None

    if risk_level in ("high", "medium"):
        logger.info("阿里云审核拦截: risk_level={} labels={} reason={}", risk_level, labels, reason)
        return ModerationResult(
            blocked=True,
            fallback="对不起，我无法回答。",
            category=labels,
        )

    if labels:
        logger.info("阿里云审核告警: risk_level={} labels={} reason={}", risk_level, labels, reason)
        return ModerationResult(
            filtered_text=user_text,
            warning=reason or labels,
            category=labels,
        )

    return ModerationResult(filtered_text=user_text)


async def moderate_content(user_text: str) -> ModerationResult:
    """
    步骤 3：内容审核 — 本地词库 + 云端（阿里云）双模式

    conf.yaml 控制：
    - mode=local: word_list 黑名单 + block_policy 策略
    - mode=cloud:   阿里云文本审核增强版（TextModerationPlus）
    """
    mode = _mod_cfg.get("mode", "local")

    if mode == "cloud":
        return await _moderate_aliyun(user_text)

    # ── 本地模式：拦截规则完全按 block_policy 表执行 ──
    async with _async_session_factory() as session:
        # 3a0. 白名单优先（包含匹配）：文本命中任意白名单词 → 直接放行，
        #      不再进行黑名单/策略检查（如"恶魔"白名单可豁免"肢解恶魔"中的暴力词）。
        #      空词条/纯空白词条直接跳过，避免 re.search("") 恒真导致全量放行。
        wl_rows = (await session.execute(text("""
            SELECT word FROM word_list WHERE list_type = 'whitelist'
        """))).fetchall()
        for (wl_word,) in wl_rows:
            if not wl_word or not wl_word.strip():
                continue
            if re.search(re.escape(wl_word), user_text):
                return ModerationResult(filtered_text=user_text)

        # 3a. 命中黑名单词条（同样跳过空词条，避免空串匹配所有输入）
        rows = (await session.execute(text("""
            SELECT w.word, w.risk_level, w.category
            FROM word_list w
            WHERE w.list_type = 'blacklist'
        """))).fetchall()

        hits: list[tuple[str, int, str | None]] = []
        for word, risk, cat in rows:
            if not word or not word.strip():
                continue
            if re.search(re.escape(word), user_text):
                hits.append((word, risk or 0, cat))

        if not hits:
            return ModerationResult(filtered_text=user_text)

        # 3a1. 按类别汇总风险：策略阈值只与该策略类别的命中风险比较，
        #      避免高风险类别把低风险类别"提级"触发。
        max_risk_by_cat: dict[str, int] = {}
        for _word, _risk, _cat in hits:
            if _cat:
                max_risk_by_cat[_cat] = max(
                    max_risk_by_cat.get(_cat, 0), _risk or 0
                )
        categories = set(max_risk_by_cat)

        # 3a2. 自杀高风险硬规则优先于 block_policy：
        #      自残实操类命中（risk >= 2）直接使用硬编码安全话术，
        #      避免被 warning_prompt 改写或降级；安全优先于其它类别策略。
        if max_risk_by_cat.get("suicide", 0) >= 2:
            return ModerationResult(
                filtered_text=user_text,
                category="suicide",
                alert_required=True,
                hard_rule=True,
            )

        # 3b. 查询 block_policy：
        #     - 策略是否生效只看 (category, risk_level)，与 alert_enabled 无关
        #     - alert_enabled 仅表示命中后是否需要人工介入（写入 alert_required）
        #     - 增加策略类型优先级，保证同一输入结果稳定
        if categories:
            policies = (await session.execute(text("""
                SELECT policy_type, warning_prompt, alert_enabled, risk_level, category
                FROM block_policy
                WHERE category = ANY(:cats)
                ORDER BY risk_level DESC,
                         CASE policy_type
                             WHEN 'force_block' THEN 4
                             WHEN 'block' THEN 3
                             WHEN 'warning_prompt' THEN 2
                             ELSE 1
                         END DESC,
                         category
            """), {"cats": list(categories)})).fetchall()
        else:
            policies = []

        # 3c. 判定：仅依据 block_policy（无匹配策略 → 放行）
        # 策略类型：block / force_block → 直接拦截；warning_prompt → 警告注入；
        # report_only 暂未实现（不改变回复，P0-4 再补 alert 传播）
        for ptype, warning_prompt, alert, prisk, category in policies:
            if max_risk_by_cat.get(category, 0) < (prisk or 0):
                continue   # 命中词风险低于策略阈值，不触发
            alert_required = bool(alert)
            if ptype in ("block", "force_block"):
                return ModerationResult(
                    blocked=True,
                    fallback="对不起，我无法回答。",
                    category=category,
                    alert_required=alert_required,
                )
            if ptype == "warning_prompt" and warning_prompt:
                return ModerationResult(
                    filtered_text=user_text,
                    warning=warning_prompt,
                    category=category,
                    alert_required=alert_required,
                )

    return ModerationResult(filtered_text=user_text)



# =======================================================================
# 4. 使用路由模型判断是简单任务、复杂任务还是纯闲聊，并检索编排所需工具
# =======================================================================


class RoutingDecision(BaseModel):
    """LLM 路由器输出 — 任务分类 + 工具/行为选择"""
    task_type: Literal["simple", "complex", "chat"]
    selected_mcp: list[str] = []
    selected_behaviors: list[str] = []


_router_cfg = _conf.get("llm_router", {})
_router_model_cfg = _router_cfg.get("router_model", {})
# 本地网关（LM Studio 等）不支持 json_object 响应格式：base_url 命中关键字即走 json_schema
_LOCAL_GATEWAY_KEYWORDS = list(_router_cfg.get("local_gateway_keywords", []))
# 精确模型名匹配（补充规则，conf.yaml 可选配置；缺省时由 local_gateway_keywords 兜底）
_DISABLE_JSON_MODE_MODELS = list(_router_cfg.get("disable_json_mode_models", []))


def _model_settings_for(model_name: str, base_url: str | None = None) -> dict | None:
    """按模型返回附加模型设置。

    通用规则（不依赖额外配置）：本地网关（local_gateway_keywords 命中）且模型名含
    "qwen3"（Qwen3/Qwen3.5 系列默认开启思考模式 thinking）时，通过 extra_body 传
    enable_thinking=false 关闭——加速响应 + 避免思考文本干扰 JSON 结构化输出。
    云端或非 Qwen3 模型返回 None（不附加任何设置）。
    """
    is_local_gateway = any(keyword in (base_url or "") for keyword in _LOCAL_GATEWAY_KEYWORDS)
    if is_local_gateway and "qwen3" in model_name:
        return {"extra_body": {"enable_thinking": False}}
    return None


def use_native_output(base_url: str | None, model_name: str) -> bool:
    """判断是否走 json_schema（NativeOutput）原生结构化输出。

    通用规则：base_url 命中本地网关关键字（127.0.0.1/localhost 等，LM Studio 类网关
    不支持 json_object 但支持 json_schema），或模型名命中 disable_json_mode_models。
    换任何本地模型都自动生效，无需改配置。
    """
    if any(keyword in (base_url or "") for keyword in _LOCAL_GATEWAY_KEYWORDS):
        return True
    return any(key in model_name for key in _DISABLE_JSON_MODE_MODELS)


def _model_profile_for(model_name: str, base_url: str | None = None):
    """按模型返回自定义 ModelProfile 回调；支持 json_object 的模型返回 None（用默认 profile）。

    本地网关（如 LM Studio / rwkv7）常不支持 response_format.type=json_object，
    命中时关闭该标志；结构化输出走 json_schema（NativeOutput）。
    """
    if use_native_output(base_url, model_name):
        def _disable_json_mode(profile):
            merged = dict(profile)
            merged["supports_json_object_output"] = False
            return merged
        return _disable_json_mode
    return None

_router_agent = Agent(
    model=OpenAIChatModel(
        _router_model_cfg.get("model", "gpt-4o-mini"),
        provider=OpenAIProvider(
            base_url=_router_model_cfg.get("base_url"),
            api_key=_resolve_env(_router_model_cfg.get("api_key", "")),
        ),
    ),
    system_prompt=(
        "你是一个游戏 NPC 任务路由器。根据玩家输入、可用 MCP 工具列表和行为树列表，"
        "选择所需的工具和行为树，并判定任务复杂度。只输出 JSON，不要解释。\n\n"
        "## 工具选择规则\n"
        "- 从可用工具列表中选择完成任务必需的 MCP 工具（如 web_search、knowledge_base 等）\n"
        "- 从可用行为树中选择执行任务所需的行为（如 follow、chop_tree、craft 等）\n"
        "- **通用规则：只要疑似对游戏内机制有疑问**（方块/物品/合成/获取方式/机制/数值/是否存在等，"
        "包括「怎么获得」「叫什么」「如何合成」「怎么制作」等不确定表达），就必须选择游戏 Wiki 类 MCP 工具\n"
        "- 闲聊（chat）→ 不选工具和行为树（返回空列表）\n\n"
        "## 分类标准\n"
        "chat: 无任务意图的聊天、问候、身份/背景询问、情绪表达，"
        "以及**一切征询角色态度/立场的问句**：\n"
        "  - 假设/条件提问（「如果王国遇到危险，你敢冲上去吗？」）\n"
        "  - 征询立场/意见（「你会为王国而战吗？」「你支持哪一边？」）\n"
        "  - 观点/评价询问（「骑士应该勇敢吗？」「这把剑怎么样？」）\n"
        "  - 身份/背景/情绪询问（「你是不是一名骑士？」「你害怕战斗吗？」）\n"
        "  例：「你好」「哈哈有趣」「你是做什么的？」\n"
        "simple: 单步动作指令，NPC 只需执行一次即可完成（祈使句，明确下达执行动作）\n"
        "  例：「跟我走」「去铁匠铺」「捡起地上的剑」\n"
        "complex: 多步任务，包含至少两个有依赖关系的步骤\n"
        "  例：「先去砍树，然后做一把木斧」「收集 5 个铁矿并送到铁匠铺」\n\n"
        "## 判定规则\n"
        "- **凡是问句：若在征询角色的身份、立场、意见、观点、情绪或假设情境下的反应"
        "（多为「你…吗？」「你…？」，主语是对方/角色自己，且没有让 NPC 立刻去执行某个动作）→ chat**\n"
        "- **只有在明确下达执行指令（祈使动词：去/拿/做/跟/捡/收集/砍/送/给等，要求 NPC 实际执行动作）时才判 simple/complex**\n"
        "- 无可执行意图 → chat\n"
        "- 单步 → simple，多步且有依赖 → complex\n"
        "- 模糊表达（「帮我搞把武器」）→ complex\n"
        "- **含具体坐标或需要空间路径规划的指令（如「走到坐标 100, 64, 200」「去 x=10 z=20 的地方」）→ complex——坐标类任务一律交由复杂模型处理**\n"
        "- **对游戏内机制/方块/物品/合成等的疑问（如「怎么获得」「叫什么」「如何合成」）→ simple（非 chat），并选中 Wiki 类 MCP**\n"
        "- 游戏机制命令（「打开背包」）→ chat\n"
        "- **只输出 JSON，不要任何其他内容**"
    ),
    output_type=PromptedOutput(RoutingDecision),
)


def _build_route_prompt(
    user_text: str,
    available_mcp: list[str],
    available_behaviors: list[str],
) -> str:
    """组装路由 prompt：工具列表 + 行为树列表 + 玩家输入"""
    mcp_str = ", ".join(available_mcp) if available_mcp else "(无可用 MCP 工具)"
    behavior_str = ", ".join(available_behaviors) if available_behaviors else "(无可用行为树)"

    return (
        f"## 可用 MCP 工具\n{mcp_str}\n\n"
        f"## 可用行为树\n{behavior_str}\n\n"
        f"## 玩家输入\n{user_text}"
    )


async def load_bound_behavior_template(
    npc_id: int,
    selected_behaviors: list[str],
) -> str | None:
    """加载该 NPC 绑定的行为树模板作为行为输出兜底。

    执行 LLM 未输出 <behavior> 时调用：按路由选中的行为树名称
    取第一个匹配的 tree_definition，序列化为 JSON 字符串返回。
    未绑定/未匹配 → None（保持纯聊天）。
    """
    if not selected_behaviors:
        return None

    async with _async_session_factory() as session:
        rows = (await session.execute(text("""
            SELECT bt.name, bt.tree_definition
            FROM behavior_tree bt
            JOIN npc_behavior_relations r ON bt.id = r.behavior_tree_id
            WHERE r.npc_id = :npc_id
              AND bt.name = ANY(:names)
            ORDER BY bt.id
            LIMIT 1
        """), {"npc_id": npc_id, "names": selected_behaviors})).fetchall()

    if not rows:
        return None

    tree_definition = rows[0].tree_definition
    if not isinstance(tree_definition, (dict, list)):
        return None

    # 复用行为树校验：结构非法则不兜底
    return _validate_behavior_json(json.dumps(tree_definition, ensure_ascii=False))


async def route_task(
    user_text: str,
    npc_id: int,
) -> RoutingDecision:
    """
    步骤 4：LLMRouter — 工具选择 + 行为选择 + 复杂度分类

    1. 从 DB 查询该 NPC 可用的 MCP 工具和行为树
    2. 将列表注入路由 prompt，由 LLM 选出所需项
    3. 返回 RoutingDecision（含 task_type + selected_* 列表）
    """
    if _MOCK:
        return RoutingDecision(task_type="chat", selected_mcp=[], selected_behaviors=[])

    async with _async_session_factory() as session:
        # 4a. 查询 NPC 关联的 MCP 工具
        mcp_rows = (await session.execute(text("""
            SELECT m.name
            FROM npc_mcp_relations r
            JOIN mcp m ON m.id = r.mcp_id
            WHERE r.npc_id = :npc_id
        """), {"npc_id": npc_id})).fetchall()
        available_mcp = [r[0] for r in mcp_rows]

        # 4b. 查询该 NPC 绑定的行为树（npc_behavior_relations 关联，非全表）
        bt_rows = (await session.execute(text("""
            SELECT bt.name
            FROM behavior_tree bt
            JOIN npc_behavior_relations r ON bt.id = r.behavior_tree_id
            WHERE r.npc_id = :npc_id
            ORDER BY bt.id
        """), {"npc_id": npc_id})).fetchall()
        available_behaviors = [r[0] for r in bt_rows]

    prompt = _build_route_prompt(user_text, available_mcp, available_behaviors)
    result = await _router_agent.run(prompt)
    return result.output



# =======================================================================
# 5. 将可用 MCP 转为 Pydantic AI MCPToolset，执行 MCP 技能后按复杂度
#    指派模型
# =======================================================================


@dataclass
class NPCReply:
    """执行 Agent 的结构化输出（<speak> + <behavior> 双段格式）"""
    speak: str = ""                           # NPC 要说的话
    behavior: str | None = None               # 行为树内容（JSON/行为描述，闲聊时为 None）
    model_config: dict | None = None          # 实际使用的模型映射（npcs.model_config）
    flagged: bool = False                     # 是否被内容审核拦截
    flagged_category: str | None = None       # 拦截类别


class BehaviorNode(BaseModel):
    """行为树节点（嵌套 Pydantic 模型，schema 层强制节点结构）。

    - node_type 必填且限定合法值
    - action 节点必须带 action_type；condition 节点必须带 condition_type（validator 校验）
    - 校验失败时 PydanticAI 自动重试（max_retries），从机制上杜绝"缺字段/乱结构"
    """
    node_type: Literal["action", "condition", "sequence", "selector", "parallel"]
    action_type: str | None = None
    condition_type: str | None = None
    action_params: dict = Field(default_factory=dict)
    condition_params: dict = Field(default_factory=dict)
    children: list["BehaviorNode"] = Field(default_factory=list)
    parallel_policy: str | None = None

    @model_validator(mode="after")
    def _check_node_fields(self) -> "BehaviorNode":
        if self.node_type == "action" and not self.action_type:
            raise ValueError("action 节点必须包含 action_type")
        if self.node_type == "condition" and not self.condition_type:
            raise ValueError("condition 节点必须包含 condition_type")
        if self.node_type in ("sequence", "selector", "parallel") and not self.children:
            raise ValueError("组合节点必须包含非空 children")
        return self


BehaviorNode.model_rebuild()


class NPCStructuredOutput(BaseModel):
    """执行 Agent 的强制结构化输出（PydanticAI output_type 驱动，API 层强制格式）。

    相比提示词约束 <speak>/<behavior> 标签，结构化输出将格式要求从"建议"升级为
    "硬性要求"：模型必须输出这两个字段，behavior 缺失/为空时由引擎按任务类型兜底。

    兼容性：部分自建/本地 OpenAI 兼容网关（如 rwkv7）会在输出外额外包装一层
    {"response": {...}}，通过 before validator 自动解包，无需区分模型。
    """
    speak: str = Field(description="NPC 在游戏内说的话，保持角色口吻")
    behavior: list[BehaviorNode] = Field(
        default_factory=list,
        description=(
            "可执行行为树节点数组（node_type/action_type/action_params 或 "
            "node_type/condition_type/condition_params 或组合节点 children）；"
            "仅闲聊无动作时输出空数组 []"
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _unwrap_response_wrapper(cls, data):
        """解包 {"response": {"speak": ..., "behavior": [...]}} 形式的外层包装。

        本地兼容网关（rwkv7 等）常强制模型输出 {"response": {...}} 结构，
        这里把内层字段并入顶层，保证解析一致。
        """
        if isinstance(data, dict) and isinstance(data.get("response"), dict):
            merged = dict(data)
            inner = merged.pop("response")
            merged.update(inner)
            return merged
        return data


class BehaviorPlanOutput(BaseModel):
    """编排 Agent 输出（复杂任务）：专注行为树生成，不涉及角色化表达"""
    behaviors: list[BehaviorNode] = Field(
        default_factory=list,
        description=(
            "可执行行为树节点数组（action/condition/sequence/selector/parallel）；"
            "仅闲聊无动作时输出空数组 []"
        ),
    )


class SpeakOutput(BaseModel):
    """回复 Agent 输出（复杂任务）：专注角色对话文本，不涉及行为树"""
    speak: str = Field(description="NPC 在游戏内说的话，保持角色口吻")


def _structured_to_reply(output: NPCStructuredOutput) -> NPCReply:
    """将结构化输出转为 NPCReply（节点校验 + 序列化）

    - behavior 为空数组 → None（纯聊天，由调用方按任务类型做模板兜底）
    - 节点结构非法 → 告警并置 None（防止垃圾行为传给引擎）
    """
    nodes = output.behavior or []
    behavior_json: str | None = None
    if nodes:
        nodes_dict = [n.model_dump(exclude_none=True) for n in nodes]
        behavior_json = _validate_behavior_json(json.dumps(nodes_dict, ensure_ascii=False))
        if behavior_json is None:
            logger.warning(
                "结构化行为节点不合法，降级为纯聊天: {}",
                json.dumps(nodes_dict, ensure_ascii=False)[:100],
            )
    return NPCReply(
        speak=(output.speak or "").strip(),
        behavior=behavior_json,
    )


# 合法节点类型（对齐 BehaviorNode / mineflayer 执行器）
_VALID_NODE_TYPES = {"action", "condition", "sequence", "selector", "parallel"}


def _validate_behavior_json(behavior_text: str) -> str | None:
    """校验 LLM 输出的 <behavior> 是否为合法行为树 JSON。

    - 顶层：节点对象或节点数组（数组按 sequence 处理）
    - 每个节点必须包含合法的 node_type；action 需 action_type，condition 需 condition_type
    - 不合法 → 返回 None（降级为纯聊天），并告警，避免垃圾行为传给引擎
    """
    if not behavior_text or not behavior_text.strip():
        return None

    def _check(node) -> bool:
        if not isinstance(node, dict):
            return False
        ntype = node.get("node_type")
        if ntype not in _VALID_NODE_TYPES:
            return False
        if ntype == "action" and not node.get("action_type"):
            return False
        if ntype == "condition" and not node.get("condition_type"):
            return False
        children = node.get("children")
        if children is not None:
            if not isinstance(children, list) or not all(_check(c) for c in children):
                return False
        return True

    try:
        parsed = json.loads(behavior_text)
    except (ValueError, TypeError):
        logger.warning("行为树 JSON 解析失败，降级为纯聊天: {}", behavior_text[:100])
        return None

    valid = _check(parsed) if isinstance(parsed, dict) else (
        isinstance(parsed, list) and all(_check(n) for n in parsed)
    )
    if not valid:
        logger.warning("行为树节点结构不合法，降级为纯聊天: {}", behavior_text[:100])
        return None
    return json.dumps(parsed, ensure_ascii=False)


def _normalize_mcp_url(url: str) -> str:
    """规范化 MCP URL（无协议前缀时补 https://）"""
    url = url.strip()
    if url and not re.match(r"^https?://", url, re.I):
        return f"https://{url}"
    return url


async def _build_mcp_toolsets(
    npc_id: int,
    selected_mcp: list[str],
) -> list:
    """
    将 NPC 可用的 MCP 服务转换为 Pydantic AI MCPToolset 列表

    DB mcp 表 → StreamableHttpTransport → MCPToolset
    仅转换路由阶段选中的 MCP（selected_mcp 按 name 匹配）
    include_instructions=True：自动注入 MCP server 自带的使用说明
    """
    from pydantic_ai.mcp import MCPToolset, StreamableHttpTransport

    if not selected_mcp:
        return []

    async with _async_session_factory() as session:
        rows = (await session.execute(text("""
            SELECT m.name, m.url, m.headers, m.timeout
            FROM npc_mcp_relations r
            JOIN mcp m ON m.id = r.mcp_id
            WHERE r.npc_id = :npc_id AND m.name = ANY(:names)
        """), {"npc_id": npc_id, "names": selected_mcp})).fetchall()

    toolsets: list = []
    for name, url, headers, timeout in rows:
        if not url:
            logger.warning("MCP '{}' 缺少 url，跳过", name)
            continue
        transport = StreamableHttpTransport(
            url=_normalize_mcp_url(url),
            headers=headers or None,
        )
        toolsets.append(MCPToolset(transport, include_instructions=True))
        logger.info("已挂载 MCP 工具集: {} ({})", name, url)

    return toolsets


async def _run_complex_parallel(
    *,
    decision: RoutingDecision,
    npc_context: NPCContext,
    user_text: str,
    model_name: str,
    base_url: str,
    api_key: str,
    mcp_toolsets: list,
    mcp_names: str,
    moderation_warning: str | None = None,
    memory_block: str = "",
) -> NPCReply:
    """复杂任务并行执行：编排 Agent（行为树）+ 回复 Agent（角色文本）。

    两个专业 Agent 通过 asyncio.gather 并行运行，互不依赖、各司其职：
    - 编排 Agent（planner）：专注行为编排——解析玩家指令为行为树节点，
      含坐标生成与路径规划，提示词只包含行为相关约束（减轻单一 Agent 的上下文负担）
    - 回复 Agent（speaker）：专注角色表达——角色/世界观/知识库/警告/MCP 技能包装，
      提示词不含行为树格式，只生成对话文本
    两个 Agent 都完成后才合并返回 NPCReply；任一异常向上抛出由外层降级链处理。
    """
    profile = _model_profile_for(model_name, base_url)
    model_settings = _model_settings_for(model_name, base_url)
    # 并行双 Agent 不重试（retries=0）：失败立即走外层降级链（fallback 单 Agent / 模板兜底），
    # 避免本地网关上的重试与并发排队叠加导致超时
    retries = 0

    # ── 编排 Agent：只关心行为树 ──
    planner_agent = Agent(
        model=OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
            profile=profile,
        ),
        model_settings=model_settings,
        system_prompt=(
            "你是游戏 NPC 行为编排器：把玩家指令解析为行为树，不生成角色对话。\n\n"
            "## 可用行为树\n"
            f"{', '.join(decision.selected_behaviors) if decision.selected_behaviors else '(无)'}\n\n"
            "## 节点格式\n"
            "动作节点：{\"node_type\":\"action\",\"action_type\":\"<类型>\",\"action_params\":{...}}\n"
            "条件节点：{\"node_type\":\"condition\",\"condition_type\":\"<类型>\",\"condition_params\":{...}}\n"
            "组合节点：{\"node_type\":\"sequence\",\"children\":[...]}\n"
            "可用动作：move_to(target, distance) | follow(distance) | stop | jump(count, delay_ms) | "
            "say(text) | interact(target) | use_item(item) | hold_item(item) | drop_item(item, count) | "
            "attack(target可选) | kill(target可选) | look_at(target可选，支持back/front/left/right) | turn_back | wait(seconds) | gather(item可选) | "
            "craft(item, count) | trade(target可选) | collect_block(block) | place_block(block, direction)\n"
            "可用条件：has_item(item, count) | health_above(value) | health_below(value) | "
            "distance_to_player(value, operator) | has_target(target) | is_in_world(block)\n"
            "**action_type 必须使用上述列表中的类型名，禁止使用行为树名称（如 follow_player 是行为树名，动作类型应为 follow）**\n\n"
            "## 坐标\n"
            "- 玩家给出明确坐标时，move_to 的 target 用 [x, y, z] 数组（或 \"x,y,z\"）\n"
            "- 未给坐标时用实体名/方块名\n\n"
            "## 方块名\n"
            "- 用游戏内实际方块名（如 oak_log）；玩家未指明具体树种时统一用 oak_log\n"
            "- 玩家指令无法转换为行为时，behaviors 输出空数组 []\n"
            "- 只输出行为 JSON，不要解释"
        ),
        capabilities=[
            SecretRedaction(),
            PromptInjection(sensitivity="medium"),
        ],
        retries=retries,
        output_type=PromptedOutput(
            BehaviorPlanOutput,
            name="behavior_plan",
            description="行为编排结果：behaviors 行为树节点数组",
        ),
    )

    # ── 回复 Agent：只关心角色对话 ──
    warning_block = (
        "\n\n## 系统警告提示（必须遵循）\n"
        f"{moderation_warning}\n"
        "请以角色口吻温暖地回应，遵循上述指引。"
    ) if moderation_warning else ""

    speaker_agent = Agent(
        model=OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
            profile=profile,
        ),
        model_settings=model_settings,
        toolsets=mcp_toolsets,   # 技能信息 → 角色化包装表达
        system_prompt=(
            f"{npc_context.character_prompt or ''}\n\n"
            f"{npc_context.world_prompt or ''}\n\n"
            f"{'## 世界观知识库资料（权威参考，回答相关问题时优先依据）\n' + npc_context.world_lore + '\n\n' if npc_context.world_lore else ''}"
            f"{memory_block}\n\n"
            f"{warning_block}\n\n"
            "## 系统赋予的 MCP 技能\n"
            f"你拥有以下技能：{mcp_names}\n"
            "- 技能是角色天生能力，仅玩家请求相关时调用\n"
            "- 使用后以角色口吻包装表达，不得提及技能名/工具名；失败时委婉应对\n\n"
            "## 职责\n"
            "只生成 NPC 对话文本（speak），保持角色口吻；行为编排由另一系统完成，无需输出行为内容。"
        ),
        capabilities=[
            SecretRedaction(),
            PromptInjection(sensitivity="medium"),
            NoRefusals(allow_partial=True),
        ],
        retries=retries,
        output_type=PromptedOutput(
            SpeakOutput,
            name="speak_output",
            description="NPC 对话文本：speak",
        ),
    )

    # 并行执行，两个都完成后才合并
    planner_result, speaker_result = await asyncio.gather(
        planner_agent.run(user_text),
        speaker_agent.run(user_text),
    )

    behavior_json: str | None = None
    if planner_result.output.behaviors:
        nodes = [n.model_dump(exclude_none=True) for n in planner_result.output.behaviors]
        behavior_json = _validate_behavior_json(json.dumps(nodes, ensure_ascii=False))
        if behavior_json is None:
            logger.warning("编排 Agent 行为结构不合法，降级为纯聊天")

    return NPCReply(
        speak=(speaker_result.output.speak or "").strip(),
        behavior=behavior_json,
    )


async def execute_task(
    decision: RoutingDecision,
    npc_context: NPCContext,
    npc_id: int,
    user_text: str,
    *,
    ooc_correction: bool = False,
    moderation_warning: str | None = None,
) -> NPCReply:
    """
    步骤 5：MCP 技能执行 + 按复杂度指派模型生成 NPC 回复

    流程：
    1. 将 NPC 可用的 MCP（selected_mcp）转换为 Pydantic AI MCPToolset
    2. 构建执行 Agent（挂载 MCP 技能 + 安全盾牌），Agent 运行时可调用 MCP 工具
    3. 模型选择：chat/simple → simple 模型，complex → complex 模型

    moderation_warning: 内容审核警告提示词（block_policy.warning_prompt）。
    命中警告时由 pool 强制走 chat 分支，并将警告注入 system_prompt，
    LLM 以角色口吻按警告指引回应（如心理危机关怀），不执行任何任务行为。
    """
    if _MOCK:
        return NPCReply(
            speak=f"(mock) 我是 NPC {npc_id}，收到你的消息：{user_text[:30]}",
            behavior=None,
        )

    async with _async_session_factory() as session:
        # 5a. 获取 NPC 模型映射
        row = (await session.execute(text(
            "SELECT model_config FROM npcs WHERE id = :id"
        ), {"id": npc_id})).fetchone()
        if row is None:
            raise ValueError(f"NPC {npc_id} not found")

        model_map: dict[str, str] = row[0]
        # 兼容两种键名：simple/complex（旧） 或 simple_task_model/complex_task_model（DB 实际）
        task_key = "complex" if decision.task_type == "complex" else "simple"
        model_name_raw = (
            model_map.get(task_key)
            or model_map.get(f"{task_key}_task_model")
            or next(iter(model_map.values()), "")
        )
        # 去除 provider 前缀（"deepseek:deepseek-v4-flash" → "deepseek-v4-flash"）
        model_name = model_name_raw.split(":", 1)[-1] if model_name_raw else ""

        # 5b. 查找 LLM 提供商
        provider_row = (await session.execute(text("""
            SELECT base_url, api_key FROM llm_providers
            WHERE models @> :model_json
            LIMIT 1
        """), {"model_json": f'[{{"name": "{model_name}"}}]'})).fetchone()

        if provider_row is None:
            raise ValueError(f"No provider found for model '{model_name}'")

        base_url, api_key = provider_row

    # 5c. 将可用 MCP 转为 Pydantic AI MCPToolset（执行 MCP 技能）
    mcp_toolsets = await _build_mcp_toolsets(npc_id, decision.selected_mcp)
    mcp_names = ", ".join(decision.selected_mcp) if decision.selected_mcp else "(无)"

    # 过往记忆注入（TeleMem 检索结果 → 角色经历，自然融入对话）
    memory_block = ""
    if npc_context.memory and npc_context.memory.history:
        memory_lines = []
        for item in npc_context.memory.history:
            mem_text = getattr(item, "memory", None) or str(item)
            if mem_text and str(mem_text).strip():
                memory_lines.append(f"- {str(mem_text).strip()}")
        if memory_lines:
            memory_block = (
                "\n\n## 你过往的相关记忆（作为角色的经历，可在对话中自然提及）\n"
                + "\n".join(memory_lines[:10])
            )

    # 复杂任务分派：
    # - 云端模型（多并发支持）：编排与回复并行（两个专业 Agent 各司其职，asyncio.gather，
    #   总耗时 ≈ max(编排, 回复)，显著降延迟）
    # - 本地网关（LM Studio 单模型实际串行排队）：并行无收益反而叠加排队耗时，
    #   回退单 Agent（一次调用同时生成 speak+behavior），保证 90s 内完成
    is_local_model = _model_profile_for(model_name, base_url) is not None
    if decision.task_type == "complex" and not is_local_model:
        return await _run_complex_parallel(
            decision=decision,
            npc_context=npc_context,
            user_text=user_text,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            mcp_toolsets=mcp_toolsets,
            mcp_names=mcp_names,
            moderation_warning=moderation_warning,
            memory_block=memory_block,
        )

    # OOC 重生成：注入纠正指令，要求严格回到角色设定内
    correction_block = (
        "\n\n## 上轮回复修正（必须执行）\n"
        "你上一轮的回复被角色一致性审查判定为偏离角色设定（OOC）。"
        "请重新回复：严格以角色设定和世界观为唯一知识边界，"
        "不要提及任何现实世界/系统/AI 概念，不要跳出角色，保持角色口吻。"
    ) if ooc_correction else ""

    # 内容审核警告：注入提示词，LLM 以角色口吻按警告指引回应（不执行任务）
    warning_block = (
        "\n\n## 系统警告提示（必须遵循）\n"
        f"{moderation_warning}\n"
        "请以角色口吻温暖地回应，遵循上述指引；本轮不执行任何任务行为（behavior 输出空数组 []）。"
    ) if moderation_warning else ""

    # 坐标职责边界（按任务类型注入）：
    # - simple/chat：简单模型只做模板/实体名匹配，禁止生成坐标
    # - complex：复杂模型是唯一负责坐标生成与路径规划的层级
    coordinate_block = (
        "\n\n## 坐标职责约束（简单任务）\n"
        "你正在执行的是简单任务：\n"
        "- 所有 target 参数只能使用实体名（\"player\"、\"sheep\"、\"zombie\"、\"villager\" 等）、"
        "方块名（如 oak_log）或 \"player\" 关键字\n"
        "- **禁止输出 [x, y, z] 坐标数组或坐标字符串**——含坐标的任务已由路由判定为复杂任务，"
        "不会分配给你\n"
        "- 保持模板化输出，不要进行空间推理"
        if decision.task_type != "complex" else
        "\n\n## 坐标职责（复杂任务）\n"
        "你正在执行的是复杂任务：\n"
        "- 当玩家给出明确坐标时，move_to 等动作的 target 使用 [x, y, z] 坐标数组（或 \"x,y,z\" 字符串）\n"
        "- 当玩家未给出坐标但描述位置时（如\"那座山脚下\"），结合上下文给出合理的坐标或使用实体名/方块名\n"
        "- 你是唯一负责坐标生成与路径规划的层级"
    )

    # 结构化输出统一走 PromptedOutput（提示式 JSON + 解析校验）：
    # - 云端模型（deepseek 等）：profile 开启 json_object，response_format 强制 JSON
    # - 本地网关（LM Studio）：profile 关闭 json_object（supports_json_object_output=False，
    #   不发 response_format，避免 json_object 400 与 json_schema "Invalid JSON Schema" 问题），
    #   纯提示词输出 JSON，由 retries + 解包 + 文本兜底 + 模板兜底保障链路完整。
    # 本地弱模型精简重试次数（1 次）防超时。
    structured_retries = 1 if is_local_model else 2

    output_type = PromptedOutput(
        NPCStructuredOutput,
        name="npc_response",
        description="NPC 回复结构：speak（说的话）+ behavior（行为树节点数组，闲聊为空数组）",
        )

    # 5d. 构建执行 Agent（挂载 MCP 技能 + 安全盾牌）
    model_settings = _model_settings_for(model_name, base_url)
    agent = Agent(
        model=OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
            profile=_model_profile_for(model_name, base_url),
        ),
        model_settings=model_settings,   # 如关闭 Qwen3.5 thinking（extra_body）
        toolsets=mcp_toolsets,   # MCP 技能：Agent 运行时可调用
        system_prompt=(
            f"{npc_context.character_prompt or ''}\n\n"
            f"{npc_context.world_prompt or ''}\n\n"
            f"{'## 世界观知识库资料（权威参考，回答相关问题时优先依据）\n' + npc_context.world_lore + '\n\n' if npc_context.world_lore else ''}"
            f"{memory_block}\n\n"
            f"{warning_block}\n\n"
            f"{correction_block}\n\n"
            f"{coordinate_block}\n\n"
            "## 系统赋予的 MCP 技能\n"
            f"你拥有以下技能：{mcp_names}\n"
            "- 技能是角色天生能力，仅玩家请求相关时调用\n"
            "- 使用后以角色口吻包装表达，不得提及技能名/工具名；失败时委婉应对，不中断对话\n\n"
            "## 输出格式（严格遵循）\n"
            "输出 JSON 对象（由系统结构化校验），仅两个字段：\n"
            "1. speak（字符串）：NPC 要说的话，保持角色口吻，必须存在\n"
            "2. behavior（数组）：可执行行为树节点；玩家有动作诉求时给出对应节点，"
            "仅闲聊无动作时输出空数组 []\n"
            "JSON 示例（仅示范字段结构，speak 内容严禁照抄）：{\"speak\":\"（此处填写角色针对玩家输入的真实回应）\",\"behavior\":[]}\n"
            "⚠️ speak 必须依据角色设定、世界观和玩家输入实际生成，禁止照抄示例或占位文本，不得出现\"遵命，我这就去\"等指令式套话\n"
            f"- 可用行为树: {', '.join(decision.selected_behaviors) if decision.selected_behaviors else '(无)'}\n"
            "### 行为树节点格式（引擎按此解析）\n"
            "节点类型 node_type：action / condition / sequence / selector / parallel\n"
            "动作节点：{\"node_type\":\"action\",\"action_type\":\"<类型>\",\"action_params\":{...}}\n"
            "条件节点：{\"node_type\":\"condition\",\"condition_type\":\"<类型>\",\"condition_params\":{...}}\n"
            "组合节点：{\"node_type\":\"sequence\",\"children\":[子节点]}\n"
            "可用动作：move_to(target, distance) | follow(distance) | stop | jump(count, delay_ms) | "
            "say(text) | interact(target) | use_item(item) | hold_item(item) | drop_item(item, count) | "
            "attack(target可选) | kill(target可选) | look_at(target可选，支持back/front/left/right) | turn_back | wait(seconds) | gather(item可选) | "
            "craft(item, count) | trade(target可选) | collect_block(block) | place_block(block, direction)\n"
            "可用条件：has_item(item, count) | health_above(value) | health_below(value) | "
            "distance_to_player(value, operator) | has_target(target) | is_in_world(block)\n"
            "**action_type 必须使用上述列表中的类型名（如 follow、move_to、kill），"
            "禁止使用行为树名称（如 follow_player 是行为树名，动作类型应为 follow）**\n"
            "**方块名必须用游戏内实际方块名**（如 oak_log）；玩家未指明具体树种时统一填 oak_log\n"
            "示例（砍树）：[{\"node_type\":\"action\",\"action_type\":\"move_to\",\"action_params\":{\"target\":\"oak_log\"}},"
            "{\"node_type\":\"action\",\"action_type\":\"collect_block\",\"action_params\":{\"block\":\"oak_log\"}},"
            "{\"node_type\":\"action\",\"action_type\":\"say\",\"action_params\":{\"text\":\"砍好了\"}}]\n"
            "**禁止使用 schema 以外的字段名，必须输出合法 JSON**"
            + (
                "\n\n## 输出硬性要求\n"
                "- 只输出 JSON 对象本身，禁止 Markdown 代码块、解释、思考过程或任何额外文本\n"
                "- 玩家指令无法转换为有效行为时，behavior 输出空数组 []"
                if is_local_model else ""
            )
        ),
        capabilities=[
            SecretRedaction(),                                    # 输出侧：拦截泄露的密钥/凭据
            PromptInjection(sensitivity="medium"),                # 输入侧：拦截提示词注入/越狱（medium 减少闲聊误伤）
            NoRefusals(allow_partial=True),                       # 输出侧：阻止拒答，允许含拒答语言但内容有实质
        ],
        retries=structured_retries,   # 结构化输出校验失败时自动重试（本地弱模型 1 次，云模型 2 次）
        output_type=output_type,
    )

    try:
        result = await agent.run(user_text)
        reply = _structured_to_reply(result.output)
    except UnexpectedModelBehavior:
        # 结构化输出校验失败（模型输出非 JSON/纯文本，重试仍失败）→ 文本模式兜底
        logger.warning("结构化输出校验失败，使用文本模式兜底")
        reply = await _run_text_mode(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            npc_context=npc_context,
            user_text=user_text,
            moderation_warning=moderation_warning,
            memory_block=memory_block,
        )
    except Exception as exc:
        # MCP 连接失败等异常 → 降级为无 MCP 的纯模型执行，避免对话中断
        logger.warning("Agent 执行异常（{}），降级为无 MCP 执行", type(exc).__name__)
        fallback_agent = Agent(
            model=OpenAIChatModel(
                model_name,
                provider=OpenAIProvider(base_url=base_url, api_key=api_key),
                profile=_model_profile_for(model_name, base_url),
            ),
            model_settings=model_settings,
            system_prompt=(
                f"{npc_context.character_prompt or ''}\n\n"
                f"{npc_context.world_prompt or ''}\n\n"
                f"{'## 世界观知识库资料（权威参考，回答相关问题时优先依据）\n' + npc_context.world_lore + '\n\n' if npc_context.world_lore else ''}"
            f"{memory_block}\n\n"
                f"{warning_block}\n\n"
                "## 输出说明（结构化输出，由系统强制校验）\n"
                "你的回复必须输出一个 JSON 对象，仅包含两个字段：\n"
                "1. speak（字符串）：NPC 要说的话，保持角色口吻\n"
                "2. behavior（数组）：可执行行为树节点数组；仅闲聊无动作时输出空数组 []"
            ),
            capabilities=[
                SecretRedaction(),
                PromptInjection(sensitivity="medium"),
                NoRefusals(allow_partial=True),
            ],
            retries=structured_retries,
            output_type=output_type,
        )
        try:
            result = await fallback_agent.run(user_text)
            reply = _structured_to_reply(result.output)
        except Exception as exc2:
            # 降级 Agent 仍失败（含结构化校验失败）→ 文本模式兜底
            logger.warning(
                "降级 Agent 仍无法结构化输出（{}），使用文本模式兜底", type(exc2).__name__
            )
            reply = await _run_text_mode(
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                npc_context=npc_context,
                user_text=user_text,
                moderation_warning=moderation_warning,
                memory_block=memory_block,
            )

    reply.model_config = model_map   # 记录实际使用的模型映射（日志用）
    return reply


async def _run_text_mode(
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    npc_context: NPCContext,
    user_text: str,
    moderation_warning: str | None = None,
    memory_block: str = "",
) -> NPCReply:
    """文本模式兜底：模型无法输出结构化 JSON 时，直接以角色口吻回复原文。

    不设置 output_type，模型自由输出文本作为 speak（无行为树能力）。
    """
    warning_block = (
        "\n\n## 系统警告提示（必须遵循）\n"
        f"{moderation_warning}\n"
        "请以角色口吻温暖地回应，遵循上述指引。"
    ) if moderation_warning else ""

    text_agent = Agent(
        model=OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
            profile=_model_profile_for(model_name, base_url),
        ),
        model_settings=_model_settings_for(model_name, base_url),
        system_prompt=(
            f"{npc_context.character_prompt or ''}\n\n"
            f"{npc_context.world_prompt or ''}\n\n"
            f"{'## 世界观知识库资料（权威参考，回答相关问题时优先依据）\n' + npc_context.world_lore + '\n\n' if npc_context.world_lore else ''}"
            f"{memory_block}\n\n"
            f"{warning_block}\n\n"
            "## 输出要求\n"
            "以角色口吻直接输出你作为 NPC 要说的话，不要输出任何 JSON、标签或系统说明。"
        ),
        capabilities=[
            SecretRedaction(),
            PromptInjection(sensitivity="medium"),
            NoRefusals(allow_partial=True),
        ],
    )
    result = await text_agent.run(user_text)
    return NPCReply(speak=str(result.output or "").strip())


# =======================================================================
# 6. 根据世界观知识库和NPC角色提示词判断是否OOC,如果是则直接输出兜底回答
# =======================================================================


class OOCDecision(BaseModel):
    """OOC 判定结果"""
    is_ooc: bool


_ooc_agent = Agent(
    model=OpenAIChatModel(
        _router_model_cfg.get("model", "gpt-4o-mini"),
        provider=OpenAIProvider(
            base_url=_router_model_cfg.get("base_url"),
            api_key=_resolve_env(_router_model_cfg.get("api_key", "")),
        ),
    ),
    system_prompt=(
        "你是一个 NPC 角色一致性审查员。"
        "判断 NPC 的回复是否超出角色设定（OOC — Out of Character）。\n\n"
        "## 知识边界基准（最重要）\n"
        "- **以角色设定和世界观为唯一知识边界基准**，而非现实世界标准\n"
        "- 若角色设定/世界观本身包含相关技术或知识（现代背景角色、赛博朋克/科幻世界观、"
        "科技发达世界等），角色使用这些概念是**正常的角色认知**，绝不判 OOC\n"
        "  · 例：2077 赛博朋克世界观中的 NPC 谈论网络、AI、义体 → 正常\n"
        "  · 例：现代背景角色谈论手机、社交媒体 → 正常\n"
        "- **审查时提供“世界观知识库资料”段落时，该资料属于世界观的一部分，"
        "NPC 依据知识库内容发言（人物、地名、事件、设定等）是正常角色认知，绝不判 OOC**\n"
        "- 仅当角色**明显超出**其设定和世界观允许的知识范围时才可能判 OOC\n"
        "  · 例：中世纪骑士突然谈论 AI 算法（设定中不存在该知识）→ OOC\n\n"
        "## OOC 判定标准（满足任一即为 OOC）\n"
        "- 提及**超出角色设定与世界观范围**的知识、科技或事件（参照上方基准）\n"
        "- 表现出对自身是 AI / NPC 的元意识（如「作为一个 AI 助手…」）\n"
        "- 直接拒绝角色扮演或跳出设定发言\n"
        "- 回复内容与角色设定或世界观明显矛盾\n\n"
        "## 系统赋予技能豁免（重要）\n"
        "- NPC 可能被系统赋予 MCP 技能（如联网搜索、知识查询、点单购物等服务能力），"
        "技能获取的信息或执行的操作属于角色能力的一部分\n"
        "- 技能相关信息以角色认知范围内可接受的方式表达即可，不算 OOC\n"
        "- 仅当 NPC 直接暴露系统级元信息（如「我是 AI」「调用了某某接口」）时才判 OOC\n\n"
        "## 判定规则\n"
        "- 仅基于给定的角色设定和世界观来判定\n"
        "- 角色合理范围内的个性表达不算 OOC\n"
        "- **只输出 JSON，不要任何其他内容**"
    ),
    output_type=PromptedOutput(OOCDecision),
)


def _build_ooc_prompt(
    npc_response: str,
    character_prompt: str | None,
    world_prompt: str | None,
    user_input: str,
    world_lore: str | None = None,
    mcp_skills: list[str] | None = None,
) -> str:
    """组装 OOC 审查 prompt"""
    skills = ", ".join(mcp_skills) if mcp_skills else "(无)"
    lore_block = (
        f"## 世界观知识库资料（权威参考，属于世界观的一部分，角色可正常提及）\n{world_lore}\n\n"
        if world_lore else ""
    )
    return (
        f"## 角色设定\n{character_prompt or '(未设定)'}\n\n"
        f"## 世界观\n{world_prompt or '(未设定)'}\n\n"
        f"{lore_block}"
        f"## 系统赋予 NPC 的技能\n{skills}\n\n"
        f"## 玩家输入\n{user_input}\n\n"
        f"## NPC 回复\n{npc_response}"
    )


async def check_ooc(
    npc_response: str,
    npc_context: NPCContext,
    user_input: str,
    *,
    mcp_skills: list[str] | None = None,
) -> tuple[str, bool]:
    """
    步骤 6：OOC 审查

    判定 NPC 回复是否超出角色设定。

    Returns:
        (回复文本, 是否OOC) — OOC 判定本身不替换回复，由调用方决定
        （pool 会带纠正提示重生成一次，仍 OOC 才兜底）。
    """
    if _MOCK:
        return npc_response, False

    prompt = _build_ooc_prompt(
        npc_response=npc_response,
        character_prompt=npc_context.character_prompt,
        world_prompt=npc_context.world_prompt,
        user_input=user_input,
        world_lore=npc_context.world_lore,
        mcp_skills=mcp_skills,
    )
    result = await _ooc_agent.run(prompt)
    is_ooc = bool(result.output.is_ooc)
    if is_ooc:
        logger.warning("OOC 审查判定越界: {}", npc_response[:80])
    return npc_response, is_ooc



# =======================================================================
# 7. 写入NPC记忆
# =======================================================================


async def save_memory(
    session_uuid: str,
    npc_id: int,
    user_input: str,
    npc_response: str,
    player_uuid: str | None = None,
) -> None:
    """
    步骤 7：将本轮对话写入 TeleMem 记忆系统

    作用域由 memory 模块统一构造（默认玩家级 npc{id}:p{uuid}），
    run_id=session_uuid 仅作会话归属标记。
    memory.enabled=false（legacy 默认）或缺少 player_uuid 时跳过写入。
    """
    if _MOCK or not memory_enabled():
        return

    _save_start = time.monotonic()
    result = await add_memory(
        messages=[
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": npc_response},
        ],
        npc_id=npc_id,
        player_uuid=player_uuid,
        run_id=session_uuid,
    )
    _saved = getattr(result, "results", None) or []
    logger.info(
        "TeleMem 记忆写入完成（NPC {}，耗时 {:.1f}s）：{} 条",
        npc_id, time.monotonic() - _save_start, len(_saved),
    )
    for _mem_item in _saved:
        logger.debug(
            "  TeleMem 写入 [{}] {}",
            getattr(_mem_item, "event", "?"),
            str(getattr(_mem_item, "memory", ""))[:120],
        )


# =======================================================================
# 8. 写入对话日志
# =======================================================================


# error_message 列存在性探测缓存（DB 结构冻结：列缺失时不写该列，改落本地日志）
_HAS_ERROR_MESSAGE_COL: bool | None = None


def _append_error_log(message: str) -> None:
    """error_message 列不可用时，把错误信息落到本地日志文件（db/ 已被 gitignore）"""
    try:
        log_path = Path(__file__).resolve().parents[1] / "db" / "core_errors.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")
    except Exception:
        logger.warning("错误日志文件写入失败（不影响主流程）")


async def _has_error_message_column(session) -> bool:
    """只读探测 conversation_logs.error_message 列是否存在（结果缓存，不修改结构）"""
    global _HAS_ERROR_MESSAGE_COL
    if _HAS_ERROR_MESSAGE_COL is None:
        try:
            _HAS_ERROR_MESSAGE_COL = bool((await session.execute(text("""
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'conversation_logs'
                  AND column_name = 'error_message'
                LIMIT 1
            """))).scalar())
        except Exception:
            _HAS_ERROR_MESSAGE_COL = False
    return _HAS_ERROR_MESSAGE_COL


async def log_conversation(
    session_uuid: str,
    npc_id: int,
    user_input: str,
    npc_response: str,
    *,
    player_uuid: str | None = None,
    model_config: dict | None = None,
    latency_ms: int = 0,
    flagged: bool = False,
    flagged_category: str | None = None,
    alert_required: bool = False,
    success: bool = True,
    error_message: str | None = None,
    exec_step: dict | None = None,
) -> None:
    """
    步骤 8：将本轮对话写入 conversation_logs 表

    记录玩家输入、NPC 回复、玩家 UUID、模型配置、延迟、审核状态等。
    玩家输入与 NPC 回复写入前统一做 PII 脱敏，避免身份证号/银行卡号/手机号明文落库。
    exec_step：管线执行步骤明细（审核分支/路由/行为来源/OOC 结果），供面板排查链路。
    日志写入失败不影响主流程。
    """
    try:
        async with _async_session_factory() as session:
            params = {
                "npc_id": npc_id,
                "player_uuid": player_uuid,
                "session_uuid": session_uuid,
                "player_input": pii_sanitize(user_input).text,
                "npc_response": pii_sanitize(npc_response).text,
                "model_config": json.dumps(model_config) if model_config else "{}",
                "latency_ms": latency_ms,
                "success": success,
                "flagged": flagged,
                "flagged_category": flagged_category,
                "alert_required": alert_required,
                "exec_step": json.dumps(exec_step, ensure_ascii=False) if exec_step else None,
            }
            if await _has_error_message_column(session):
                await session.execute(text("""
                    INSERT INTO conversation_logs
                        (npc_role_id, player_uuid, session_uuid, player_input, npc_response,
                         model_config, latency_ms, success, error_message,
                         flagged, flagged_category, alert_required, exec_step)
                    VALUES
                        (:npc_id, :player_uuid, :session_uuid, :player_input, :npc_response,
                         :model_config, :latency_ms, :success, :error_message,
                         :flagged, :flagged_category, :alert_required, :exec_step)
                """), {**params, "error_message": error_message})
            else:
                # 列不存在（旧库）：不写该列，错误信息落本地日志文件，保持结构冻结
                await session.execute(text("""
                    INSERT INTO conversation_logs
                        (npc_role_id, player_uuid, session_uuid, player_input, npc_response,
                         model_config, latency_ms, success,
                         flagged, flagged_category, alert_required, exec_step)
                    VALUES
                        (:npc_id, :player_uuid, :session_uuid, :player_input, :npc_response,
                         :model_config, :latency_ms, :success,
                         :flagged, :flagged_category, :alert_required, :exec_step)
                """), params)
                if error_message:
                    _append_error_log(
                        f"npc={npc_id} session={session_uuid} {error_message}"
                    )
            await session.commit()
    except Exception:
        logger.warning("对话日志写入失败（不影响主流程）")
        if error_message:
            _append_error_log(f"npc={npc_id} session={session_uuid} {error_message}")

