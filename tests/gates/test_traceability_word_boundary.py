"""F-005 · traceability._feature_mentioned 单词边界正则测试。

覆盖：
  - 正向命中（精确匹配）
  - 负向拒绝（前/后有标识符字符时不应命中）
  - precheck submit 路径新增逻辑
"""
from __future__ import annotations

import pytest

from plugins import traceability as plugin_mod
from plugins.base import GateContext


# ====================== _feature_mentioned 单词边界测试 ======================


@pytest.mark.parametrize(
    "feature_id, text, expected",
    [
        # -------- 正向命中 --------
        ("FG-001", "## FG-001 实现详情\n内容", True),
        ("FG-001", "见 FG-001 章节", True),
        ("FG-001", "FG-001", True),          # 单独出现
        ("FG-001", "\nFG-001\n", True),       # 换行边界
        ("F-001", "status: F-001 done", True),
        # -------- 负向拒绝 --------
        ("FG-001", "FG-0015 相关设计", False),   # 数字后缀
        ("FG-001", "XFG-001Y 扩展版", False),    # 字母前/后缀
        ("FG-001", "XFG-001 前缀扩展", False),   # 字母前缀
        ("FG-001", "FG-0011 类似编号", False),   # 末尾更长
        ("F-001", "FG-001 XF-001Y 扩展", False),  # 前有字母前缀 X，后有字母后缀 Y
    ],
)
def test_feature_mentioned_word_boundary(feature_id: str, text: str, expected: bool):
    """given_text_and_feature_id_when_feature_mentioned_then_match_respects_word_boundary."""
    result = plugin_mod._feature_mentioned(feature_id, text)
    assert result == expected, (
        f"_feature_mentioned({feature_id!r}, {text!r}) 应返回 {expected}，实际 {result}"
    )


# ====================== precheck submit 路径测试 ======================


def test_precheck_allows_submit_with_requirement_id():
    """given_trigger_submit_with_req_id_when_precheck_then_none（F-005 新增路径）。"""
    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(trigger="submit", requirement_id="REQ-2026-005")
    result = gate.precheck(ctx)
    assert result is None, f"precheck 应放行 submit 路径，实际返回 Skip: {result}"


def test_precheck_skips_submit_without_requirement_id():
    """given_trigger_submit_without_req_id_when_precheck_then_skip（无法追溯跳过）。"""
    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(trigger="submit", requirement_id=None)
    result = gate.precheck(ctx)
    assert result is not None, "submit 无 requirement_id 时应 Skip"


def test_precheck_still_allows_phase_transition_to_testing():
    """given_trigger_phase_transition_to_testing_when_precheck_then_none（既有路径保持）。"""
    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-005",
        to_phase="testing",
    )
    result = gate.precheck(ctx)
    assert result is None


def test_precheck_still_skips_phase_transition_to_other_phase():
    """given_trigger_phase_transition_to_development_when_precheck_then_skip（非 testing 跳过）。"""
    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-005",
        to_phase="development",
    )
    result = gate.precheck(ctx)
    assert result is not None
    assert "testing" in result.reason


def test_precheck_skips_phase_transition_to_testing_without_req_id():
    """given_phase_transition_to_testing_no_req_id_when_precheck_then_skip。"""
    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(trigger="phase-transition", to_phase="testing")
    result = gate.precheck(ctx)
    assert result is not None
    assert "requirement_id" in result.reason
