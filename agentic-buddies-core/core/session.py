"""会话管理 — 过期时间 + 单会话轮数上限"""

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

_conf = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "conf.yaml").read_text()
).get("session", {})

DEFAULT_TIMEOUT_SECONDS = int(_conf.get("timeout_minutes", 5)) * 60
DEFAULT_MAX_TURNS = int(_conf.get("max_turns", 20))


@dataclass
class SessionState:
    """单个会话状态"""
    session_uuid: str
    last_activity: float
    turn_count: int = 0


class SessionManager:
    """NPC 对话会话生命周期管理（内存态，进程重启即失效）"""

    def __init__(
        self,
        timeout_seconds: int | None = None,
        max_turns: int | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self.max_turns = max_turns or DEFAULT_MAX_TURNS
        self._sessions: dict[str, SessionState] = {}

    def _is_valid(self, state: SessionState, now: float) -> bool:
        """会话未过期且未达轮数上限"""
        if now - state.last_activity > self.timeout_seconds:
            return False
        if state.turn_count >= self.max_turns:
            return False
        return True

    def get_or_create(self, session_uuid: str | None) -> tuple[str, bool]:
        """
        获取或创建会话

        Args:
            session_uuid: 客户端携带的会话 ID（可能为 None 或已失效）

        Returns:
            (session_uuid, is_new)
            - 有效会话：返回原 ID，is_new=False
            - 过期/超轮数/缺失：返回新 ID，is_new=True
        """
        now = time.monotonic()

        if session_uuid and session_uuid in self._sessions:
            state = self._sessions[session_uuid]
            if self._is_valid(state, now):
                state.turn_count += 1
                state.last_activity = now
                return session_uuid, False
            # 失效会话清理
            del self._sessions[session_uuid]

        new_uuid = str(uuid.uuid4())
        self._sessions[new_uuid] = SessionState(
            session_uuid=new_uuid,
            last_activity=now,
            turn_count=1,
        )
        return new_uuid, True

    def clear(self) -> None:
        """清空全部会话（测试/重置用）"""
        self._sessions.clear()
