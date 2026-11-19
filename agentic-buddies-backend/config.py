"""agentic-buddies-backend 本地配置加载。

`conf.yaml` 只用于本地/部署配置，包含 `server` 与 `auth` 段。
其中 `auth.default_reset_password` 属于敏感配置，仓库只保留
`conf.yaml.example`，真实的 `conf.yaml` 已被 `.gitignore` 忽略。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_CONF_PATH = Path(__file__).resolve().parent / "conf.yaml"


def _load_conf() -> dict:
    """读取 conf.yaml；文件缺失或格式错误时返回空字典。"""
    if not _CONF_PATH.exists():
        return {}
    try:
        with _CONF_PATH.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


_conf: dict = _load_conf()


def get_default_reset_password() -> str:
    """返回管理员重置用户密码时使用的默认密码。

    优先级：环境变量 ``DEFAULT_RESET_PASSWORD`` >
    ``conf.yaml`` 的 ``auth.default_reset_password``。

    未配置时返回空字符串；调用方必须失败关闭，禁止回退到硬编码密码。
    """
    value = os.getenv("DEFAULT_RESET_PASSWORD")
    if not value:
        auth = _conf.get("auth")
        if isinstance(auth, dict):
            value = auth.get("default_reset_password")
    if not isinstance(value, str):
        return ""
    return value.strip()
