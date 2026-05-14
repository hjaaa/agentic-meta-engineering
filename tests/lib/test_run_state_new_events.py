"""F-002 · VALID_EVENT_TYPES 扩展 + DispatchOutcome 第 8 类 · 验收测试。

覆盖 7 条 acceptance criteria：
- AC-1：VALID_EVENT_TYPES 含 3 个新事件；append_event 写入不抛白名单错
- AC-2：node_ready → state == awaiting_claude_action + current_node == node_id
- AC-3：approval_repair_started → state == awaiting_claude_action + pending_approval == node_id
- AC-4：approval_repair_completed → state == approval_pending；pending_approval 保留
- AC-5：node_completed 紧跟 node_ready → state == running ∧ current_node is None
- AC-6：DispatchOutcome 含 awaiting_claude_action
- AC-7（P1-1 反向回归）：WORKFLOW_EVENT_TO_STATE 仍是 6 项，3 个新事件不在其中

测试运行：
    python3 -m pytest tests/lib/test_run_state_new_events.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import (  # noqa: E402
    VALID_EVENT_TYPES,
    WORKFLOW_EVENT_TO_STATE,
    RunState,
    append_event,
)
from workflow_dispatcher import DispatchOutcome  # noqa: E402


# ============================================================================
# AC-1：VALID_EVENT_TYPES 含 3 个新事件；append_event 写入不抛白名单错
# ============================================================================

def test_VALID_EVENT_TYPES_含三新事件():
    """AC-1a：3 个新事件必须存在于白名单集合。"""
    assert "node_ready" in VALID_EVENT_TYPES
    assert "approval_repair_started" in VALID_EVENT_TYPES
    assert "approval_repair_completed" in VALID_EVENT_TYPES


def test_append_event_三新事件不抛白名单错(tmp_path):
    """AC-1b：append_event 写入 3 个新事件不应抛 WorkflowError（白名单拒绝）。"""
    jsonl = tmp_path / "run-state.jsonl"

    # 先写 workflow_started 作为上下文（append_event 不关心顺序，但显式测 3 类）
    append_event(jsonl, {"type": "workflow_started", "run_id": "R-AC1"})

    # node_ready
    append_event(jsonl, {
        "type": "node_ready",
        "node_id": "phase-design",
        "data": {
            "node_kind": "skill",
            "external_action_contract": {
                "skill": "code-review",
                "args": {},
                "timeout_ms": 60000,
                "on_success": "node_completed",
                "on_failure": "node_failed",
                "idempotency_key": "phase-design-001",
                "max_retries": 1,
            },
        },
    })

    # approval_repair_started
    append_event(jsonl, {
        "type": "approval_repair_started",
        "node_id": "gate-1",
        "data": {
            "attempt": 1,
            "max_attempts": 3,
            "prompt_ref": "prompts/repair.md",
            "reason": "reviewer requested changes",
        },
    })

    # approval_repair_completed
    append_event(jsonl, {
        "type": "approval_repair_completed",
        "node_id": "gate-1",
        "data": {"attempt": 1},
    })

    # 全部写入后反扫应有 4 条事件（无白名单 warn）
    from run_state import read_events
    events, warnings = read_events(jsonl)
    bad = [w for w in warnings if "不在白名单" in w or "解析失败" in w]
    assert not bad, f"不期望出现白名单或解析错误 warn：{bad}"
    assert len(events) == 4


# ============================================================================
# AC-2：node_ready → state == awaiting_claude_action + current_node == node_id
# ============================================================================

def test_rebuild_node_ready_设置awaiting_claude_action():
    """AC-2：单条 node_ready 事件使 state=awaiting_claude_action + current_node=node_id。"""
    events = [
        {"type": "workflow_started", "run_id": "R1", "data": {"workflow_name": "x"}},
        {"type": "node_ready", "node_id": "design-node",
         "data": {"node_kind": "prompt", "external_action_contract": {}}},
    ]
    state = RunState.rebuild(events, run_id="R1")
    assert state.state == "awaiting_claude_action", f"期望 awaiting_claude_action，实际 {state.state}"
    assert state.current_node == "design-node", f"期望 current_node=design-node，实际 {state.current_node}"


# ============================================================================
# AC-3：approval_repair_started → state == awaiting_claude_action + pending_approval == node_id
# ============================================================================

def test_rebuild_approval_repair_started_设置pending_approval():
    """AC-3：approval_repair_started 使 state=awaiting_claude_action + pending_approval=node_id。"""
    events = [
        {"type": "workflow_started", "run_id": "R2", "data": {"workflow_name": "x"}},
        {"type": "node_started", "node_id": "gate-a"},
        {"type": "approval_pending", "node_id": "gate-a"},
        {"type": "approval_repair_started", "node_id": "gate-a",
         "data": {"attempt": 1, "max_attempts": 3, "prompt_ref": "p.md",
                  "reason": "needs fix"}},
    ]
    state = RunState.rebuild(events, run_id="R2")
    assert state.state == "awaiting_claude_action", f"期望 awaiting_claude_action，实际 {state.state}"
    assert state.pending_approval == "gate-a", f"期望 pending_approval=gate-a，实际 {state.pending_approval}"


# ============================================================================
# AC-4：approval_repair_completed → state == approval_pending；pending_approval 保留
# ============================================================================

def test_rebuild_approval_repair_completed_保留pending_approval():
    """AC-4：approval_repair_completed 把 state 回到 approval_pending；pending_approval 不清空。"""
    events = [
        {"type": "workflow_started", "run_id": "R3", "data": {"workflow_name": "x"}},
        {"type": "node_started", "node_id": "gate-b"},
        {"type": "approval_pending", "node_id": "gate-b"},
        {"type": "approval_repair_started", "node_id": "gate-b",
         "data": {"attempt": 1, "max_attempts": 3, "prompt_ref": "p.md",
                  "reason": "fix me"}},
        {"type": "approval_repair_completed", "node_id": "gate-b",
         "data": {"attempt": 1}},
    ]
    state = RunState.rebuild(events, run_id="R3")
    assert state.state == "approval_pending", f"期望 approval_pending，实际 {state.state}"
    # pending_approval 必须保留（仍在等下一次 approve/reject）
    assert state.pending_approval == "gate-b", (
        f"pending_approval 不应被 approval_repair_completed 清空，实际 {state.pending_approval}"
    )


# ============================================================================
# AC-5：node_completed 紧跟 node_ready → state == running ∧ current_node is None
# ============================================================================

def test_rebuild_node_completed_后恢复running():
    """AC-5：node_ready → node_completed 序列后 state 回 running，current_node 清空。"""
    events = [
        {"type": "workflow_started", "run_id": "R4", "data": {"workflow_name": "x"}},
        {"type": "node_started", "node_id": "skill-node"},
        {"type": "node_ready", "node_id": "skill-node",
         "data": {"node_kind": "skill", "external_action_contract": {}}},
        {"type": "node_completed", "node_id": "skill-node",
         "data": {"output": "done"}},
    ]
    state = RunState.rebuild(events, run_id="R4")
    assert state.state == "running", f"期望 running，实际 {state.state}"
    assert state.current_node is None, f"期望 current_node=None，实际 {state.current_node}"


# ============================================================================
# AC-6：DispatchOutcome Literal 含 awaiting_claude_action
# ============================================================================

def test_DispatchOutcome_含awaiting_claude_action():
    """AC-6：DispatchOutcome Literal 必须包含第 8 项 awaiting_claude_action。"""
    outcomes = get_args(DispatchOutcome)
    assert "awaiting_claude_action" in outcomes, (
        f"DispatchOutcome 缺少 awaiting_claude_action；当前 {outcomes}"
    )


# ============================================================================
# AC-7（P1-1 反向回归）：WORKFLOW_EVENT_TO_STATE 仍是 6 项，3 个新事件不在其中
# ============================================================================

def test_WORKFLOW_EVENT_TO_STATE_仍是6项():
    """AC-7a（P1-1）：WORKFLOW_EVENT_TO_STATE 必须严格保持 6 项不变。"""
    expected = {
        "workflow_started",
        "workflow_paused",
        "workflow_completed",
        "workflow_failed",
        "workflow_cancelled",
        "cancel_requested",
    }
    actual = set(WORKFLOW_EVENT_TO_STATE.keys())
    assert actual == expected, (
        f"WORKFLOW_EVENT_TO_STATE 被意外修改。\n期望：{expected}\n实际：{actual}"
    )


def test_新事件不在WORKFLOW_EVENT_TO_STATE():
    """AC-7b（P1-1）：3 个新事件绝不能进入 WORKFLOW_EVENT_TO_STATE（扁平映射会吃掉副作用）。"""
    new_events = ("node_ready", "approval_repair_started", "approval_repair_completed")
    for ev in new_events:
        assert ev not in WORKFLOW_EVENT_TO_STATE, (
            f"事件 {ev!r} 不应出现在 WORKFLOW_EVENT_TO_STATE（P1-1 教训：扁平映射无法表达字段副作用）"
        )


# ============================================================================
# rev2 · F-005 守卫：approval_repair_completed 无 node_id 不改变 state
# ============================================================================

def test_rebuild_approval_repair_completed_无node_id_不改变state():
    """F-005：approval_repair_completed 缺 node_id 时不应把 state 覆盖为 approval_pending。"""
    events = [
        {"type": "workflow_started", "run_id": "R-F005", "data": {"workflow_name": "x"}},
        {"type": "approval_repair_completed", "ts": "2026-05-14T10:00:00Z",
         "node_id": None, "data": {"attempt": 1}},
    ]
    state = RunState.rebuild(events, run_id="R-F005")
    assert state.state == "running", (
        f"approval_repair_completed 无 node_id 不应改变 state，实际 {state.state}"
    )


# ============================================================================
# rev2 · F-007 终态守卫：node_ready / approval_repair_started 在终态后不覆盖 state
# ============================================================================

def test_rebuild_node_ready_在终态后不覆盖state():
    """F-007：workflow_failed 后出现 node_ready（损坏 jsonl）不应把 state 覆盖回 awaiting_claude_action。"""
    events = [
        {"type": "workflow_started", "run_id": "R-F007a", "data": {"workflow_name": "x"}},
        {"type": "workflow_failed", "data": {"reason": "internal error"}},
        {"type": "node_ready", "node_id": "N1",
         "data": {"node_kind": "skill", "external_action_contract": {}}},
    ]
    state = RunState.rebuild(events, run_id="R-F007a")
    assert state.state == "failed", (
        f"终态 failed 后 node_ready 不应覆盖 state，实际 {state.state}"
    )
    assert state.current_node is None, (
        f"终态后 current_node 不应被 node_ready 覆盖，实际 {state.current_node}"
    )


def test_rebuild_approval_repair_started_在终态后不覆盖state():
    """F-007：workflow_completed 后出现 approval_repair_started（损坏 jsonl）不应覆盖 state。"""
    events = [
        {"type": "workflow_started", "run_id": "R-F007b", "data": {"workflow_name": "x"}},
        {"type": "workflow_completed", "data": {}},
        {"type": "approval_repair_started", "node_id": "N1",
         "data": {"attempt": 1, "max_attempts": 3, "prompt_ref": "p.md", "reason": "fix"}},
    ]
    state = RunState.rebuild(events, run_id="R-F007b")
    assert state.state == "completed", (
        f"终态 completed 后 approval_repair_started 不应覆盖 state，实际 {state.state}"
    )
