"""F-006 · workflow-launcher keyword_matcher 单测。

覆盖范围（6 个 TC）：
  TC-F6-1  test_each_category_happy：6 类关键词各正例命中，command 正确
  TC-F6-2  test_longest_match_wins：长短关键词共存，最长胜出
  TC-F6-3  test_state_tiebreaker：approval_pending 时优先 approve/reject
  TC-F6-4  test_equal_length_conflict_ask：等长冲突触发 ask（conflict 非空）
  TC-F6-5  test_ascii_word_boundary：假阳性防护（approved/releases 不命中）
  TC-F6-6  test_no_match_passthrough：无命中返回三 None，launcher 不接管

外部依赖：无（keyword_matcher 纯函数，无 IO）。
active_runs mock：使用 types.SimpleNamespace(state="approval_pending") 简单对象。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL_DIR = _REPO_ROOT / ".claude" / "skills" / "workflow-launcher"
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

# ---------- 被测模块 ----------

from keyword_matcher import ConflictReason, MatchResult, match_keyword  # noqa: E402

# ---------- Fixture 加载 ----------

_FIXTURES_PATH = (
    _REPO_ROOT / "tests" / "skills" / "fixtures" / "keyword_matching.yaml"
)


def _load_fixture(group_key: str) -> list[dict[str, Any]]:
    """从 yaml fixture 文件中加载指定分组的用例列表。"""
    with open(_FIXTURES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    cases = data.get(group_key)
    if cases is None:
        raise KeyError(f"fixture 分组不存在：{group_key!r}")
    return cases


def _make_runs(states: list[str]) -> list[Any]:
    """将 state 字符串列表转换为带 .state 属性的简单对象（duck typing mock）。"""
    return [types.SimpleNamespace(state=s) for s in states]


def _run_case(case: dict[str, Any]) -> MatchResult:
    """根据 fixture 用例调用 match_keyword，返回 (command, args, conflict)。"""
    active_runs = _make_runs(case.get("active_run_states") or [])
    return match_keyword(case["input"], active_runs)


# ============================================================
# TC-F6-1：各类关键词 happy path
# ============================================================

_TC1_CASES = _load_fixture("tc_f6_1_each_category_happy")


@pytest.mark.parametrize("case", _TC1_CASES, ids=[c["name"] for c in _TC1_CASES])
def test_each_category_happy(case: dict[str, Any]) -> None:
    """TC-F6-1：6 类关键词各正例必须命中，command 与 fixture 期望一致。"""
    command, args, conflict = _run_case(case)
    expected = case["expected"]

    assert command == expected["command"], (
        f"[{case['name']}] command 不匹配：期望 {expected['command']!r}，实际 {command!r}"
    )
    assert args == expected.get("args"), (
        f"[{case['name']}] args 不匹配：期望 {expected.get('args')!r}，实际 {args!r}"
    )
    assert (conflict is not None) == bool(expected.get("conflict", False)), (
        f"[{case['name']}] conflict 状态不匹配：期望 {'有' if expected.get('conflict') else '无'} 冲突"
    )


# ============================================================
# TC-F6-2：最长匹配优先
# ============================================================

_TC2_CASES = _load_fixture("tc_f6_2_longest_match_wins")


@pytest.mark.parametrize("case", _TC2_CASES, ids=[c["name"] for c in _TC2_CASES])
def test_longest_match_wins(case: dict[str, Any]) -> None:
    """TC-F6-2：含多个关键词时，最长者胜出，不应返回短关键词命令。"""
    command, args, conflict = _run_case(case)
    expected = case["expected"]

    assert conflict is None, (
        f"[{case['name']}] 不应触发等长冲突，实际 conflict={conflict}"
    )
    assert command == expected["command"], (
        f"[{case['name']}] 最长匹配失败：期望 {expected['command']!r}，实际 {command!r}"
    )


# ============================================================
# TC-F6-3：state tiebreaker
# ============================================================

_TC3_CASES = _load_fixture("tc_f6_3_state_tiebreaker")


@pytest.mark.parametrize("case", _TC3_CASES, ids=[c["name"] for c in _TC3_CASES])
def test_state_tiebreaker(case: dict[str, Any]) -> None:
    """TC-F6-3：approval_pending 时优先命中 approve/reject，不进 Step2。"""
    command, args, conflict = _run_case(case)
    expected = case["expected"]

    assert command == expected["command"], (
        f"[{case['name']}] state tiebreaker 失败：期望 {expected['command']!r}，实际 {command!r}"
    )
    assert (conflict is not None) == bool(expected.get("conflict", False)), (
        f"[{case['name']}] conflict 状态不匹配"
    )


# ============================================================
# TC-F6-4：等长冲突 ask 兜底
# ============================================================

_TC4_CASES = _load_fixture("tc_f6_4_equal_length_conflict_ask")


@pytest.mark.parametrize("case", _TC4_CASES, ids=[c["name"] for c in _TC4_CASES])
def test_equal_length_conflict_ask(case: dict[str, Any]) -> None:
    """TC-F6-4：等长冲突时必须返回 ConflictReason，command/args 均为 None。"""
    command, args, conflict = _run_case(case)
    expected = case["expected"]

    if expected.get("conflict", False):
        assert command is None, (
            f"[{case['name']}] 等长冲突时 command 应为 None，实际 {command!r}"
        )
        assert args is None, (
            f"[{case['name']}] 等长冲突时 args 应为 None，实际 {args!r}"
        )
        assert isinstance(conflict, ConflictReason), (
            f"[{case['name']}] 期望 ConflictReason，实际 {type(conflict)}"
        )
        assert conflict.reason == "equal_length", (
            f"[{case['name']}] reason 不匹配：{conflict.reason!r}"
        )
        assert len(conflict.candidates) >= 2, (
            f"[{case['name']}] candidates 应 ≥2 个，实际 {len(conflict.candidates)}"
        )
        # 所有候选长度应相等
        lengths = {c.length for c in conflict.candidates}
        assert len(lengths) == 1, (
            f"[{case['name']}] candidates 长度不统一：{lengths}"
        )
    else:
        # 不期望冲突
        assert conflict is None, (
            f"[{case['name']}] 不应触发冲突，实际 {conflict}"
        )
        assert command == expected["command"], (
            f"[{case['name']}] command 不匹配"
        )


# ============================================================
# TC-F6-5：ASCII 词边界（假阳性防护）
# ============================================================

_TC5_CASES = _load_fixture("tc_f6_5_ascii_word_boundary")


@pytest.mark.parametrize("case", _TC5_CASES, ids=[c["name"] for c in _TC5_CASES])
def test_ascii_word_boundary(case: dict[str, Any]) -> None:
    """TC-F6-5：approved/releases/rejected 等词形变体不应命中对应关键词。"""
    command, args, conflict = _run_case(case)
    expected = case["expected"]

    assert command == expected["command"], (
        f"[{case['name']}] 词边界检测失败：期望 {expected['command']!r}，实际 {command!r}"
    )
    assert (conflict is not None) == bool(expected.get("conflict", False)), (
        f"[{case['name']}] conflict 状态不匹配"
    )


# ============================================================
# TC-F6-6：无命中透传
# ============================================================

_TC6_CASES = _load_fixture("tc_f6_6_no_match_passthrough")


@pytest.mark.parametrize("case", _TC6_CASES, ids=[c["name"] for c in _TC6_CASES])
def test_no_match_passthrough(case: dict[str, Any]) -> None:
    """TC-F6-6：无关输入应返回三 None，launcher 不接管。"""
    command, args, conflict = _run_case(case)

    assert command is None, (
        f"[{case['name']}] 无命中时 command 应为 None，实际 {command!r}"
    )
    assert args is None, (
        f"[{case['name']}] 无命中时 args 应为 None，实际 {args!r}"
    )
    assert conflict is None, (
        f"[{case['name']}] 无命中时 conflict 应为 None，实际 {conflict}"
    )
