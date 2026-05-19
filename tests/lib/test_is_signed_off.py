"""is_signed_off helper 单测（已退化）。

F-002（remove human sign-off）：is_signed_off helper 与 SIGNOFF_PASS 已从
check_reviews.py 中删除；本测试文件整体不再适用，pytest.skip 整体跳过
collection，配合 F-003 收尾时随 signoff 子系统一起删除。
"""
from __future__ import annotations

import pytest

pytest.skip(
    "F-002 已删除 is_signed_off helper；本测试文件随 F-003 收尾删除",
    allow_module_level=True,
)

import sys
from pathlib import Path

# 注入 scripts/lib 到 path
_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from check_reviews import is_signed_off  # noqa: E402


@pytest.mark.parametrize("verdict, expected", [
    # TC-B8: approved → True
    ({"human_signoff": {"decision": "approved"}}, True),
    # TC-B9: approved-trivial → True
    ({"human_signoff": {"decision": "approved-trivial"}}, True),
    # TC-B10: rejected → False
    ({"human_signoff": {"decision": "rejected"}}, False),
    # TC-B11: 缺 human_signoff 字段 → False
    ({}, False),
])
def test_is_signed_off(verdict: dict, expected: bool) -> None:
    """验证 is_signed_off 的 4 个等价类。"""
    result = is_signed_off(verdict)
    assert result == expected, (
        f"is_signed_off({verdict!r}) 期望 {expected}，实际 {result}"
    )


def test_is_signed_off_none_human_signoff() -> None:
    """human_signoff=None 时（JSON null）等价于无此字段，返回 False。"""
    verdict = {"human_signoff": None}
    assert is_signed_off(verdict) is False


def test_is_signed_off_empty_decision() -> None:
    """decision 为空字符串 → False（不在 SIGNOFF_PASS 中）。"""
    verdict = {"human_signoff": {"decision": ""}}
    assert is_signed_off(verdict) is False
