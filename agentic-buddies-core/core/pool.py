"""NPC Worker Pool — 管理多个 NPC 并发请求"""

import asyncio
import json
import time
from pathlib import Path

import yaml
from loguru import logger

from core.core import (
    NPCContext,
    NPCReply,
    RoutingDecision,
    SUICIDE_SAFETY_SCRIPT,
    build_npc_context,
    check_ooc,
    execute_task,
    filter_input,
    load_bound_behavior_template,
    log_conversation,
    moderate_content,
    route_task,
    save_memory,
)

_conf_path = Path(__file__).resolve().parents[1] / "conf.yaml"
_conf = yaml.safe_load(_conf_path.read_text())
_pool_cfg = _conf.get("npc_pool", {})
_mod_mode = _conf.get("content_moderation", {}).get("mode", "local")


def _resolve_used_model(model_config: dict | None, task_type: str) -> tuple[str, str | None]:
    """根据任务类型解析实际使用的模型（简单/复杂）。

    Returns:
        (model_used, model_name) — ("simple"|"complex", 去 provider 前缀的模型名)
        chat/simple 均走简单模型；complex 走复杂模型。
    """
    model_config = model_config or {}
    task_key = "complex" if task_type == "complex" else "simple"
    raw = (
        model_config.get(task_key)
        or model_config.get(f"{task_key}_task_model")
        or next(iter(model_config.values()), None)
    )
    model_name = raw.split(":", 1)[-1] if raw else None
    return task_key, model_name


class NPCPool:
    """NPC 请求并发管理 — asyncio.Semaphore 限流 + 7 步管线编排"""

    async def _background_save_memory(
        self,
        session_uuid: str,
        npc_id: int,
        user_input: str,
        npc_response: str,
        player_uuid: str | None = None,
    ) -> None:
        """后台记忆写入（30s 超时兜底，异常仅告警，绝不阻塞对话主流程）"""
        try:
            await asyncio.wait_for(
                save_memory(
                    session_uuid, npc_id, user_input, npc_response, player_uuid
                ),
                timeout=30,
            )
        except Exception as exc:
            logger.warning("后台记忆写入失败（{}），跳过", type(exc).__name__)

    def __init__(self, max_concurrency: int | None = None) -> None:
        max_cc = max_concurrency or _pool_cfg.get("max_concurrency", 5)
        self._sem = asyncio.Semaphore(max_cc)

    async def process(
        self,
        npc_id: int,
        session_uuid: str,
        user_input: str,
        *,
        player_uuid: str | None = None,
    ) -> NPCReply:
        """
        执行完整 7 步管线并返回最终 NPC 回复（speak + behavior）

        并发由 self._sem 控制，超出上限的请求排队等待。
        """
        start = time.monotonic()
        model_config: dict[str, str] | None = None
        final_response = ""
        final_behavior: str | None = None
        flagged = False
        flagged_category: str | None = None
        alert_required = False
        success = False
        error_message: str | None = None
        # 执行步骤明细（写入 conversation_logs.exec_step，供面板排查链路）
        exec_step: dict = {
            "moderation": {
                "mode": _mod_mode,
                "blocked": False,
                "category": None,
                "warning": None,
                "alert_required": False,
                "hard_rule": False,
            },
            "route": {"task_type": None, "selected_mcp": [], "selected_behaviors": []},
            "execution": {"model_used": None, "model_name": None, "behavior_source": "none"},
            "ooc": {"is_ooc": False, "retried": False, "fallback_used": False},
        }

        async with self._sem:
            try:
                # 1. PII 过滤
                filtered = filter_input(user_input)

                # 2. 构建 NPC 上下文
                ctx: NPCContext = await build_npc_context(
                    npc_id, session_uuid, filtered, player_uuid=player_uuid
                )

                # 3. 内容审核（local/cloud 分支）
                mod = await moderate_content(filtered)
                # alert_enabled 只决定"是否人工介入"，统一回写到日志字段，
                # 覆盖 block / warning / 自杀硬规则 / 放行四条路径
                alert_required = mod.alert_required
                exec_step["moderation"].update(
                    blocked=mod.blocked,
                    category=mod.category,
                    warning=mod.warning or None,
                    alert_required=mod.alert_required,
                    hard_rule=mod.hard_rule,
                )
                if mod.blocked:
                    flagged = True
                    flagged_category = mod.category
                    final_response = mod.fallback
                    success = True
                    return NPCReply(
                        speak=final_response,
                        flagged=flagged,
                        flagged_category=flagged_category,
                    )
                filtered = mod.filtered_text

                # 3a. 自杀高风险硬规则：跳过 LLM 生成，使用硬编码安全话术
                #     （跳出角色扮演 → 确认风险 → 求助渠道 → 告知专员跟进）。
                #     只有 hard_rule 才走这里，普通 alert_required 不会误触发。
                if mod.hard_rule:
                    final_response = SUICIDE_SAFETY_SCRIPT
                    success = True
                    return NPCReply(speak=final_response)

                # 3b. 命中警告提示词 → 强制走 talk 分支（跳过任务路由）：
                #     警告注入执行 Agent 提示词，LLM 以角色口吻按警告指引回应
                forced_chat = False
                if mod.warning:
                    forced_chat = True
                    decision = RoutingDecision(task_type="chat", selected_mcp=[], selected_behaviors=[])
                    exec_step["route"].update(
                        task_type="chat",
                        selected_mcp=[],
                        selected_behaviors=[],
                        forced_by_warning=True,
                    )
                else:
                    # 4. 路由分类 + 工具/行为选择
                    decision: RoutingDecision = await route_task(filtered, npc_id)
                    exec_step["route"].update(
                        task_type=decision.task_type,
                        selected_mcp=decision.selected_mcp,
                        selected_behaviors=decision.selected_behaviors,
                    )

                # 5. 执行任务 → speak + behavior 双段输出
                reply: NPCReply = await execute_task(
                    decision, ctx, npc_id, filtered,
                    moderation_warning=mod.warning,
                )
                model_config = reply.model_config   # 实际使用的模型映射
                final_response = reply.speak
                final_behavior = reply.behavior
                model_used, model_name = _resolve_used_model(model_config, decision.task_type)
                exec_step["execution"].update(model_used=model_used, model_name=model_name)
                if final_behavior is not None:
                    exec_step["execution"]["behavior_source"] = "llm"

                # 5b. 行为模板兜底：任务型指令（simple/complex）但执行 LLM 未输出 <behavior>
                #     时，从该 NPC 绑定的行为树中按路由选中名称加载模板作为行为输出，
                #     避免"嘴上答应却不动手"。
                if final_behavior is None and decision.task_type != "chat":
                    template_behavior = await load_bound_behavior_template(
                        npc_id, decision.selected_behaviors
                    )
                    if template_behavior is not None:
                        logger.info(
                            "行为模板兜底: task={} behaviors={}",
                            decision.task_type,
                            decision.selected_behaviors,
                        )
                        final_behavior = template_behavior
                        exec_step["execution"]["behavior_source"] = "template"

                # 6. OOC 审查（只审 speak 文本，MCP 技能获取的信息豁免）
                # 判定越界 → 带纠正提示重新生成一次，仍越界才兜底（避免单次误判吞掉正常回复）
                final_response, is_ooc = await check_ooc(
                    final_response,
                    ctx,
                    filtered,
                    mcp_skills=decision.selected_mcp,
                )
                exec_step["ooc"]["is_ooc"] = is_ooc
                if is_ooc:
                    logger.warning("OOC 判定越界，带纠正提示重生成一次")
                    exec_step["ooc"]["retried"] = True
                    retry_reply: NPCReply = await execute_task(
                        decision, ctx, npc_id, filtered,
                        ooc_correction=True,
                        moderation_warning=mod.warning,
                    )
                    final_response, is_ooc_again = await check_ooc(
                        retry_reply.speak,
                        ctx,
                        filtered,
                        mcp_skills=decision.selected_mcp,
                    )
                    if is_ooc_again:
                        logger.warning("重生成后仍 OOC，使用兜底回答")
                        exec_step["ooc"]["fallback_used"] = True
                        final_response = "对不起，我无法回答。"
                    else:
                        final_response = retry_reply.speak
                        # 重生成有行为 → 采用 LLM 行为；无行为 → 保留模板兜底结果，
                        # 避免重生成覆盖已加载的行为树模板
                        if retry_reply.behavior is not None:
                            final_behavior = retry_reply.behavior
                            exec_step["execution"]["behavior_source"] = "llm"

                # 7. 记忆写入（后台异步，不阻塞对话主流程）：
                #    mem0 summary 生成依赖 LLM（deepseek），响应慢/挂起时
                #    对话仍需立即返回，记忆在后台慢慢写入
                asyncio.create_task(
                    self._background_save_memory(
                        session_uuid, npc_id, filtered, final_response, player_uuid
                    )
                )

                success = True
                return NPCReply(speak=final_response, behavior=final_behavior)

            except Exception as exc:
                success = False
                flagged = True
                flagged_category = flagged_category or "internal_error"
                error_message = f"{type(exc).__name__}: {exc}"[:500]
                raise

            finally:
                # 8. 对话日志（无论成败都写，含执行步骤明细）
                latency_ms = int((time.monotonic() - start) * 1000)
                await log_conversation(
                    session_uuid=session_uuid,
                    npc_id=npc_id,
                    player_uuid=player_uuid,
                    user_input=user_input,
                    npc_response=final_response,
                    model_config=model_config,
                    latency_ms=latency_ms,
                    flagged=flagged,
                    flagged_category=flagged_category,
                    alert_required=alert_required,
                    success=success,
                    error_message=error_message,
                    exec_step=exec_step,
                )
