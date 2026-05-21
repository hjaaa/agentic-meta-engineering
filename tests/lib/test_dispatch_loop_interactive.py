"""Bug-14 · _dispatch_loop_node interactive 模式单元测试。

背景：
原 _dispatch_loop_node 在 loop.interactive=true + loop.prompt(_file) 配置下：
- 不读 prompt
- 不写 node_ready
- 直接写 loop_iteration_started → loop_iteration_completed → loop_continue
导致 50 次 iteration 全空转，实际 implementer 从未被派发（Bug-14）。

修复后期望行为（interactive=true 时）：
每轮入口写 loop_iteration_started{iter=N} + node_ready{node_kind="loop_iteration",
prompt=<rendered>, loop_iteration=N, external_action_contract=...}，返回
awaiting_claude_action；外部由 save_node_result --kind=loop_iteration --output=
{"outcome":"continue"|"all_done"} 写入 loop_iteration_completed 后推进/终止。

覆盖：
- TC-LI-1：interactive 首轮（无前序事件）写 loop_iteration_started + node_ready
- TC-LI-2：interactive 模式变量替换 $LOOP_ITERATION 生效
- TC-LI-3：上一轮 outcome=all_done → 写 loop_completed + node_completed → loop_done
- TC-LI-4：上一轮 outcome=continue → 写新一轮 loop_iteration_started + node_ready
- TC-LI-5：interactive=true 时 counter≥max_iterations → max_iterations_exceeded + loop_done
- TC-LI-6：未传 interactive → 走既有 5-line 路径（保护回归）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event  # noqa: E402
from workflow_dispatcher import _dispatch_loop_node  # noqa: E402


def _make_run_state(loop_counters: dict[str, int] | None = None) -> RunState:
    rs = RunState(run_id="REQ-2026-009")
    rs.state = "running"
    if loop_counters:
        rs.loop_counters = dict(loop_counters)
    return rs


def _read_events(jsonl_path: Path) -> list[dict]:
    if not jsonl_path.exists():
        return []
    out = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ============================================================================
# TC-LI-1：interactive 首轮 → loop_iteration_started + node_ready + awaiting_claude_action
# ============================================================================

def test_interactive_first_iteration_writes_node_ready(tmp_path: Path) -> None:
    """TC-LI-1：interactive=true + 首轮（loop_counters 缺该 node_id）
    → 写 loop_iteration_started{iter=0} + node_ready{loop_iteration=0, ...}
    → 返回 awaiting_claude_action。
    """
    jsonl = tmp_path / "run-state.jsonl"
    node = {
        "id": "dev-loop",
        "loop": {
            "prompt": "iter $LOOP_ITERATION",
            "interactive": True,
            "max_iterations": 5,
        },
    }
    rs = _make_run_state()

    result = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)

    assert result.outcome == "awaiting_claude_action", (
        f"interactive 首轮应返回 awaiting_claude_action，实际 {result.outcome!r}"
    )

    events = _read_events(jsonl)
    types = [e["type"] for e in events]
    assert "loop_iteration_started" in types, f"应写 loop_iteration_started，实际 {types}"
    assert "node_ready" in types, f"应写 node_ready，实际 {types}"
    assert "loop_iteration_completed" not in types, (
        "interactive 模式 dispatcher 不应写 loop_iteration_completed（由 save_node_result 写）"
    )

    # node_ready 字段校验
    nr = next(e for e in events if e["type"] == "node_ready")
    assert nr["node_id"] == "dev-loop"
    assert nr["data"]["node_kind"] == "loop_iteration"
    assert nr["data"]["loop_iteration"] == 0
    assert "external_action_contract" in nr["data"]


# ============================================================================
# TC-LI-2：变量替换 $LOOP_ITERATION 生效
# ============================================================================

def test_interactive_substitutes_loop_iteration_var(tmp_path: Path) -> None:
    """TC-LI-2：prompt 内 $LOOP_ITERATION → 渲染为当前 iter 字符串。

    loop_counters[node]=2 → 渲染后 prompt 含 "iter 2"。
    """
    jsonl = tmp_path / "run-state.jsonl"
    node = {
        "id": "dev-loop",
        "loop": {
            "prompt": "current iter is $LOOP_ITERATION",
            "interactive": True,
            "max_iterations": 5,
        },
    }
    rs = _make_run_state(loop_counters={"dev-loop": 2})

    _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)

    events = _read_events(jsonl)
    nr = next(e for e in events if e["type"] == "node_ready")
    assert "current iter is 2" in nr["data"]["prompt"], (
        f"$LOOP_ITERATION 未替换为 2，实际 prompt={nr['data']['prompt']!r}"
    )


# ============================================================================
# TC-LI-3：上一轮 outcome=all_done → loop_completed + node_completed → loop_done
# ============================================================================

def test_interactive_all_done_terminates_loop(tmp_path: Path) -> None:
    """TC-LI-3：jsonl 末位 loop_iteration_completed{outcome=all_done}
    → 写 loop_completed + node_completed{loop_done:true} → outcome=loop_done。
    """
    jsonl = tmp_path / "run-state.jsonl"
    # 先注入上一轮的 loop_iteration_completed{outcome=all_done}
    append_event(jsonl, {
        "type": "loop_iteration_started",
        "node_id": "dev-loop",
        "data": {"iteration": 0},
    })
    append_event(jsonl, {
        "type": "loop_iteration_completed",
        "node_id": "dev-loop",
        "data": {"iteration": 0, "outcome": "all_done"},
    })

    node = {
        "id": "dev-loop",
        "loop": {
            "prompt": "p",
            "interactive": True,
            "max_iterations": 5,
        },
    }
    rs = _make_run_state(loop_counters={"dev-loop": 0})

    result = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)

    assert result.outcome == "loop_done", (
        f"outcome=all_done 时应返回 loop_done，实际 {result.outcome!r}"
    )
    events = _read_events(jsonl)
    types = [e["type"] for e in events]
    assert "loop_completed" in types, "all_done 时应写 loop_completed"
    assert "node_completed" in types, "all_done 时应写 node_completed"


# ============================================================================
# TC-LI-4：上一轮 outcome=continue → 新一轮 loop_iteration_started + node_ready
# ============================================================================

def test_interactive_continue_dispatches_next_iteration(tmp_path: Path) -> None:
    """TC-LI-4：jsonl 末位 loop_iteration_completed{outcome=continue} + counter 已 +1
    → 写新一轮 loop_iteration_started{iter=1} + node_ready{loop_iteration=1}
    → outcome=awaiting_claude_action。
    """
    jsonl = tmp_path / "run-state.jsonl"
    append_event(jsonl, {
        "type": "loop_iteration_started",
        "node_id": "dev-loop",
        "data": {"iteration": 0},
    })
    append_event(jsonl, {
        "type": "loop_iteration_completed",
        "node_id": "dev-loop",
        "data": {"iteration": 0, "outcome": "continue"},
    })
    # outcome_router 已写 loop_counter_advanced；模拟 rs.loop_counters[dev-loop]=1
    node = {
        "id": "dev-loop",
        "loop": {
            "prompt": "iter $LOOP_ITERATION",
            "interactive": True,
            "max_iterations": 5,
        },
    }
    rs = _make_run_state(loop_counters={"dev-loop": 1})

    result = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)

    assert result.outcome == "awaiting_claude_action"
    events = _read_events(jsonl)
    # 末尾应当多了一组 loop_iteration_started{iter=1} + node_ready
    tail_types = [e["type"] for e in events[-2:]]
    assert tail_types == ["loop_iteration_started", "node_ready"], (
        f"末尾事件序列应为 [loop_iteration_started, node_ready]，实际 {tail_types}"
    )
    nr = events[-1]
    assert nr["data"]["loop_iteration"] == 1


# ============================================================================
# TC-LI-5：interactive 模式下 counter ≥ max_iterations → max_iterations_exceeded
# ============================================================================

def test_interactive_max_iterations_exceeded(tmp_path: Path) -> None:
    """TC-LI-5：interactive=true + loop_counters[node]=max → 写 max_iterations_exceeded
    + node_completed{loop_done:true, max_iterations_exceeded:true} → outcome=loop_done。
    """
    jsonl = tmp_path / "run-state.jsonl"
    node = {
        "id": "dev-loop",
        "loop": {
            "prompt": "p",
            "interactive": True,
            "max_iterations": 3,
        },
    }
    rs = _make_run_state(loop_counters={"dev-loop": 3})  # 已达 max

    result = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)

    assert result.outcome == "loop_done"
    events = _read_events(jsonl)
    types = [e["type"] for e in events]
    assert "loop_max_iterations_exceeded" in types
    assert "node_completed" in types
    # 不应再写 node_ready（已终止）
    assert "node_ready" not in types


# ============================================================================
# TC-LI-6：未传 interactive → 走既有 5-line 路径（回归保护）
# ============================================================================

def test_non_interactive_falls_through_legacy_path(tmp_path: Path) -> None:
    """TC-LI-6：loop 不带 interactive=true → 既有 max_iterations 计数路径，
    写 loop_iteration_started/completed，不写 node_ready。
    保护 F-011 历史行为不被破坏。
    """
    jsonl = tmp_path / "run-state.jsonl"
    node = {"id": "no-int-loop", "loop": {"max_iterations": 2}}
    rs = _make_run_state()

    result = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)

    assert result.outcome == "loop_continue"
    events = _read_events(jsonl)
    types = [e["type"] for e in events]
    assert "loop_iteration_started" in types
    assert "loop_iteration_completed" in types
    assert "node_ready" not in types
