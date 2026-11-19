"""词库写入口校验测试（黑名单必须带 category + risk_level）"""

import os
import unittest

# 允许在没有 .env 的环境下导入（只做 Pydantic 校验，不连接数据库）
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)

from pydantic import ValidationError

from api.word_list import WordCreate, WordUpdate


class TestWordCreateValidation(unittest.TestCase):
    """新建词条校验"""

    def test_blacklist_requires_category_and_risk_level(self) -> None:
        with self.assertRaises(ValidationError):
            WordCreate(word="测试词", list_type="blacklist")

    def test_blacklist_requires_risk_level(self) -> None:
        with self.assertRaises(ValidationError):
            WordCreate(word="测试词", list_type="blacklist", category="violence")

    def test_valid_blacklist_passes(self) -> None:
        word = WordCreate(
            word="测试词",
            list_type="blacklist",
            category="violence",
            risk_level=3,
        )
        self.assertEqual(word.word, "测试词")

    def test_whitelist_does_not_require_extra_fields(self) -> None:
        word = WordCreate(word="测试词", list_type="whitelist")
        self.assertEqual(word.word, "测试词")

    def test_empty_word_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            WordCreate(word="   ", list_type="whitelist")

    def test_word_is_stripped(self) -> None:
        word = WordCreate(word="  测试词  ", list_type="whitelist")
        self.assertEqual(word.word, "测试词")

    def test_too_long_word_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            WordCreate(word="词" * 101, list_type="whitelist")


class TestWordUpdateValidation(unittest.TestCase):
    """更新词条校验（黑名单完整性由接口层按生效值校验）"""

    def test_empty_word_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            WordUpdate(word="")

    def test_whitespace_word_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            WordUpdate(word="   ")

    def test_partial_update_is_allowed(self) -> None:
        update = WordUpdate(category="violence")
        self.assertEqual(update.category, "violence")
        self.assertIsNone(update.word)


if __name__ == "__main__":
    unittest.main()
