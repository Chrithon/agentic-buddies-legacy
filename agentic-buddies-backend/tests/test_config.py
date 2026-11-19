"""默认重置密码配置加载测试（不连接数据库）"""

import os
import unittest
from unittest.mock import patch

import config


class TestDefaultResetPassword(unittest.TestCase):
    """conf.yaml / 环境变量的优先级与失败关闭行为"""

    def test_env_var_has_highest_priority(self) -> None:
        with patch.object(config, "_conf", {"auth": {"default_reset_password": "ConfPass123"}}):
            with patch.dict(os.environ, {"DEFAULT_RESET_PASSWORD": "EnvPass123"}):
                self.assertEqual(config.get_default_reset_password(), "EnvPass123")

    def test_conf_value_is_used(self) -> None:
        with patch.object(config, "_conf", {"auth": {"default_reset_password": "ConfPass123"}}):
            with patch.dict(os.environ, {"DEFAULT_RESET_PASSWORD": ""}):
                self.assertEqual(config.get_default_reset_password(), "ConfPass123")

    def test_missing_value_returns_empty(self) -> None:
        with patch.object(config, "_conf", {}):
            with patch.dict(os.environ, {"DEFAULT_RESET_PASSWORD": ""}):
                self.assertEqual(config.get_default_reset_password(), "")

    def test_whitespace_value_returns_empty(self) -> None:
        with patch.object(config, "_conf", {"auth": {"default_reset_password": "   "}}):
            with patch.dict(os.environ, {"DEFAULT_RESET_PASSWORD": ""}):
                self.assertEqual(config.get_default_reset_password(), "")

    def test_non_string_value_returns_empty(self) -> None:
        with patch.object(config, "_conf", {"auth": {"default_reset_password": 12345678}}):
            with patch.dict(os.environ, {"DEFAULT_RESET_PASSWORD": ""}):
                self.assertEqual(config.get_default_reset_password(), "")


if __name__ == "__main__":
    unittest.main()
