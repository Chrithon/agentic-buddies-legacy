"""PII 过滤 — 身份证号 + 银行卡号 + 中国大陆手机号"""

import re
from dataclasses import dataclass, field

# ── 正则模式 ──────────────────────────────────────────────

# 脱敏占位符：不保留类型与序号，避免通过占位符反推 PII 类型/数量
_MASK = "***"

_PATTERNS: dict[str, str] = {
    "ID_CARD": (
        r"(?<!\d)"
        r"[1-9]\d{5}"                          # 地址码
        r"(?:18|19|20)\d{2}"                   # 年份 1800-2099
        r"(?:0[1-9]|1[0-2])"                   # 月份
        r"(?:0[1-9]|[12]\d|3[01])"             # 日期
        r"\d{3}"                                # 顺序码
        r"[\dXx]"                               # 校验位
        r"(?!\d)"
    ),
    "BANK_CARD": (
        r"(?<!\d)"
        r"62\d{2}"                              # 银联 BIN 62xxxx
        r"(?:[-\s]?\d{4}){2}"                   # 两段 4 位
        r"[-\s]?\d{1,7}"                        # 末段 4-7 位 (总长 16-19)
        r"(?!\d)"
    ),
    # 中国大陆手机号：11 位，1 开头，按当前已分配号段收敛（降低误伤）。
    # 覆盖：移动 13x/147/148/150-152/157-159/172/178/182-184/187/188/195/197/198、
    #       联通 130-132/145/146/155/156/166/167/171/175/176/185/186/196、
    #       电信 133/149/153/173/174/177/180/181/189/190/191/193/199、
    #       广电 192、虚拟运营商 162/165/167/170/171、卫星 1749/1349、
    #       广电/卫星保留 1610/1619。
    # 未分配的 154/161/164/179/194 等不匹配；支持 +86/0086/86 前缀与 3-4-4 分隔。
    "PHONE": (
        r"(?<!\d)"
        r"(?:(?:\+|00)?86[ -]?)?"              # 可选国际前缀 +86 / 0086 / 86
        r"(?:"
        r"1(?:3\d|4[5-9]|5[0-35-9]|6[2567]|7[0-8]|8\d|9[0-35-9])"
        r"[ -]?\d{4}[ -]?\d{4}"                # 3-4-4（分隔可选）
        r"|161[09][ -]?\d{3}[ -]?\d{4}"        # 1610（广电）/ 1619（卫星）
        r")"
        r"(?!\d)"
    ),
}


@dataclass
class PIIMatch:
    """单条命中记录"""
    text: str
    label: str
    start: int
    end: int


@dataclass
class Sanitized:
    """脱敏结果"""
    text: str
    matches: list[PIIMatch] = field(default_factory=list)


def sanitize(text: str) -> Sanitized:
    """
    检测并脱敏身份证号、银行卡号及中国大陆手机号

    重叠命中（如以 62 开头的身份证号同时符合银行卡规则）只保留靠前/较长的一条，
    避免同一段文本被重复打标签。

    Args:
        text: 原始用户输入

    Returns:
        Sanitized(text=替换后文本（PII 统一替换为 ***）, matches=实际替换的命中列表)
    """
    matches: list[PIIMatch] = []
    for label, pattern in _PATTERNS.items():
        for m in re.finditer(pattern, text):
            matches.append(PIIMatch(
                text=m.group(),
                label=label,
                start=m.start(),
                end=m.end(),
            ))

    # 起点靠前者优先；起点相同时较长者优先（保证 ID_CARD 胜过长前缀误命中）
    matches.sort(key=lambda x: (x.start, -(x.end - x.start)))

    parts: list[str] = []
    cursor = 0
    tagged: list[PIIMatch] = []
    for m in matches:
        if m.start < cursor:
            continue
        parts.append(text[cursor:m.start])
        parts.append(_MASK)
        tagged.append(m)
        cursor = m.end
    parts.append(text[cursor:])

    return Sanitized(text="".join(parts), matches=tagged)
