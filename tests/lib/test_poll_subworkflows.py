"""F-011 · _poll_sub_workflows 单元测试。

覆盖 AC-1~AC-5 + 补充 AC-7（continue 分支）+ AC-8（多 sub_workflow 并存）。

测试用例：
- TC-AC1 : 子末位 workflow_completed → 父追加 child_graceful_exited + node_completed
- TC-AC2 : 子末位 workflow_failed + on_subworkflow_failure=skip → 父追加 child_failed + node_skipped
- TC-AC3 : 子末位 workflow_failed + on_subworkflow_failure=fail → 父追加 child_failed + node_failed + workflow_failed；state=failed
- TC-AC4 : 子末位 workflow_cancelled → 父追加 child_force_killed + node_failed
- TC-AC5 : 幂等 — 父节点已 completed 时不重复写 child_*
- TC-AC7 : 子末位 workflow_failed + on_subworkflow_failure=continue → 父追加 child_failed + node_completed
- TC-AC8 : 多 sub_workflow 节点：1 completed + 1 failed-skip → 两个父节点都被回填

运行：
    python3 -m pytest tests/lib/test_poll_subworkflows.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event, read_events  # noqa: E402
from workflow_continue import _poll_sub_workflows  # noqa: E402


# ============================================================================
# 辅助函数
# ============================================================================

def _write_sub_jsonl(sub_run_dir: Path, events: list[dict]) -> Path:
    """在 sub_run_dir/run-state.jsonl 写入指定事件，返回 jsonl 路径。"""
    jsonl = sub_run_dir / "run-state.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    with jsonl.open("w", encoding="utf-8") as fh:
        for evt in events:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
    return jsonl


def _write_parent_jsonl(run_dir: Path, events: list[dict]) -> Path:
    """在 run_dir/run-state.jsonl 写入父事件，返回 jsonl 路径。"""
    jsonl = run_dir / "run-state.jsonl"
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    with jsonl.open("w", encoding="utf-8") as fh:
        for evt in events:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
    return jsonl


def _read_events_raw(jsonl_path: Path) -> list[dict]:
    """直接读 jsonl 所有行（含非白名单类型，用于断言原始写入）。"""
    if not jsonl_path.exists():
        return []
    events = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _make_run_state(
    run_id: str = "PARENT-001",
    node_outputs: dict | None = None,
) -> RunState:
    """构造 RunState（state=running）。"""
    rs = RunState(run_id=run_id)
    if node_outputs:
        rs.node_outputs = node_outputs
    return rs


def _make_workflow(nodes: list[dict]) -> dict:
    """构造最小 workflow dict。"""
    return {"nodes": nodes}


# ============================================================================
# TC-AC1: 子 workflow_completed → child_graceful_exited + node_completed
# ============================================================================

def test_child_completed_writes_graceful_exited_and_node_completed(tmp_path: Path) -> None:
    """AC-1: 子末位 workflow_completed → 父追加 child_graceful_exited + node_completed。"""
    node_id = "sub-node"
    run_dir = tmp_path / "runs" / "PARENT-001"
    run_dir.mkdir(parents=True)

    # 子 run 末位事件 = workflow_completed
    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_completed", "data": {}, "ts": "2026-05-15T00:01:00Z"},
    ])

    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-001",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state()
    workflow = _make_workflow([{"id": node_id, "sub_workflow": {"template": "child-wf"}}])

    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert advanced is True
    events, _ = read_events(parent_jsonl)
    types = [e.get("type") for e in events]
    assert "child_graceful_exited" in types, f"应含 child_graceful_exited，实际 {types}"
    assert "node_completed" in types, f"应含 node_completed，实际 {types}"

    # child_graceful_exited 事件 data 字段
    cge = next(e for e in events if e.get("type") == "child_graceful_exited")
    assert cge["node_id"] == node_id
    assert cge["data"]["sub_run_id"] == node_id
    assert cge["data"]["sub_terminal_event"] == "workflow_completed"

    # 父 RunState 已更新
    assert node_id in run_state.node_outputs
    assert run_state.node_outputs[node_id]["state"] == "completed"


# ============================================================================
# TC-AC2: workflow_failed + skip → child_failed + node_skipped
# ============================================================================

def test_child_failed_skip_writes_child_failed_and_node_skipped(tmp_path: Path) -> None:
    """AC-2: 子末位 workflow_failed + on_subworkflow_failure=skip → child_failed + node_skipped。"""
    node_id = "sub-skip"
    run_dir = tmp_path / "runs" / "PARENT-002"
    run_dir.mkdir(parents=True)

    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_failed", "data": {"error": "oops"}, "ts": "2026-05-15T00:01:00Z"},
    ])

    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-002",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-002")
    workflow = _make_workflow([{
        "id": node_id, "sub_workflow": {"template": "child-wf"},
        "on_subworkflow_failure": "skip",
    }])

    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert advanced is True
    events, _ = read_events(parent_jsonl)
    types = [e.get("type") for e in events]
    assert "child_failed" in types, f"应含 child_failed，实际 {types}"
    assert "node_skipped" in types, f"应含 node_skipped，实际 {types}"
    assert "workflow_failed" not in types, f"skip 策略不应写 workflow_failed，实际 {types}"

    cf = next(e for e in events if e.get("type") == "child_failed")
    assert cf["data"]["on_subworkflow_failure"] == "skip"
    assert run_state.node_outputs[node_id]["state"] == "skipped"


# ============================================================================
# TC-AC3: workflow_failed + fail → child_failed + node_failed + workflow_failed
# ============================================================================

def test_child_failed_fail_writes_workflow_failed(tmp_path: Path) -> None:
    """AC-3: 子末位 workflow_failed + on_subworkflow_failure=fail → child_failed + node_failed + workflow_failed；state=failed。"""
    node_id = "sub-fail"
    run_dir = tmp_path / "runs" / "PARENT-003"
    run_dir.mkdir(parents=True)

    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_failed", "data": {"error": "fail"}, "ts": "2026-05-15T00:01:00Z"},
    ])

    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-003",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-003")
    workflow = _make_workflow([{
        "id": node_id, "sub_workflow": {"template": "child-wf"},
        "on_subworkflow_failure": "fail",
    }])

    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert advanced is True
    events, _ = read_events(parent_jsonl)
    types = [e.get("type") for e in events]
    assert "child_failed" in types, f"应含 child_failed，实际 {types}"
    assert "node_failed" in types, f"应含 node_failed，实际 {types}"
    assert "workflow_failed" in types, f"应含 workflow_failed，实际 {types}"
    assert run_state.state == "failed", f"父 state 应 failed，实际 {run_state.state}"
    assert run_state.node_outputs[node_id]["state"] == "failed"


# ============================================================================
# TC-AC4: workflow_cancelled → child_force_killed + node_failed
# ============================================================================

def test_child_cancelled_writes_force_killed_and_node_failed(tmp_path: Path) -> None:
    """AC-4: 子末位 workflow_cancelled → child_force_killed + node_failed。"""
    node_id = "sub-cancel"
    run_dir = tmp_path / "runs" / "PARENT-004"
    run_dir.mkdir(parents=True)

    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_cancelled", "data": {}, "ts": "2026-05-15T00:01:00Z"},
    ])

    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-004",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-004")
    workflow = _make_workflow([{"id": node_id, "sub_workflow": {"template": "child-wf"}}])

    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert advanced is True
    events, _ = read_events(parent_jsonl)
    types = [e.get("type") for e in events]
    assert "child_force_killed" in types, f"应含 child_force_killed，实际 {types}"
    assert "node_failed" in types, f"应含 node_failed，实际 {types}"

    cfk = next(e for e in events if e.get("type") == "child_force_killed")
    assert cfk["data"]["sub_terminal_event"] == "workflow_cancelled"
    assert run_state.node_outputs[node_id]["state"] == "failed"


# ============================================================================
# TC-AC5: 幂等 — 父节点已 completed 时不重复写 child_*
# ============================================================================

def test_poll_idempotent_when_parent_node_already_completed(tmp_path: Path) -> None:
    """AC-5: node_id in run_state.node_outputs → 不重复写 child_* 事件。"""
    node_id = "sub-idem"
    run_dir = tmp_path / "runs" / "PARENT-005"
    run_dir.mkdir(parents=True)

    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_completed", "data": {}, "ts": "2026-05-15T00:01:00Z"},
    ])

    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-005",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    # 父节点已关闭（幂等守卫应触发）
    run_state = _make_run_state(
        run_id="PARENT-005",
        node_outputs={node_id: {"output": "", "state": "completed", "data": {}}},
    )
    workflow = _make_workflow([{"id": node_id, "sub_workflow": {"template": "child-wf"}}])

    parent_events_before, _ = read_events(parent_jsonl)
    count_before = len(parent_events_before)

    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert advanced is False, "幂等：已 completed 父节点不应推进"
    parent_events_after, _ = read_events(parent_jsonl)
    assert len(parent_events_after) == count_before, (
        f"幂等：不应追加任何事件，before={count_before}，after={len(parent_events_after)}"
    )


# ============================================================================
# TC-AC7: workflow_failed + continue → child_failed + node_completed
# ============================================================================

def test_child_failed_continue_writes_child_failed_and_node_completed(tmp_path: Path) -> None:
    """AC-7 (补充): on_subworkflow_failure=continue → child_failed + node_completed（父继续下游）。"""
    node_id = "sub-continue"
    run_dir = tmp_path / "runs" / "PARENT-007"
    run_dir.mkdir(parents=True)

    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_failed", "data": {"error": "continue"}, "ts": "2026-05-15T00:01:00Z"},
    ])

    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-007",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-007")
    workflow = _make_workflow([{
        "id": node_id, "sub_workflow": {"template": "child-wf"},
        "on_subworkflow_failure": "continue",
    }])

    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert advanced is True
    events, _ = read_events(parent_jsonl)
    types = [e.get("type") for e in events]
    assert "child_failed" in types, f"应含 child_failed，实际 {types}"
    assert "node_completed" in types, f"应含 node_completed（continue 策略），实际 {types}"
    assert "workflow_failed" not in types, f"continue 策略不应写 workflow_failed，实际 {types}"
    assert run_state.node_outputs[node_id]["state"] == "completed"
    assert run_state.state != "failed"


# ============================================================================
# TC-AC8: 多 sub_workflow 节点并存回填
# ============================================================================

def test_multiple_sub_workflows_both_backfilled(tmp_path: Path) -> None:
    """AC-8 (补充): 多个 sub_workflow：1 completed + 1 failed-skip → 两个父节点都被回填。"""
    run_dir = tmp_path / "runs" / "PARENT-008"
    run_dir.mkdir(parents=True)

    node_a = "sub-a"
    node_b = "sub-b"

    # sub-a: completed
    _write_sub_jsonl(run_dir / "sub_runs" / node_a, [
        {"type": "workflow_started", "run_id": node_a,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_completed", "data": {}, "ts": "2026-05-15T00:01:00Z"},
    ])
    # sub-b: failed + skip
    _write_sub_jsonl(run_dir / "sub_runs" / node_b, [
        {"type": "workflow_started", "run_id": node_b,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_failed", "data": {"error": "err"}, "ts": "2026-05-15T00:01:00Z"},
    ])

    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-008",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-008")
    workflow = _make_workflow([
        {"id": node_a, "sub_workflow": {"template": "child-wf"}},
        {"id": node_b, "sub_workflow": {"template": "child-wf"},
         "on_subworkflow_failure": "skip"},
    ])

    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert advanced is True
    events, _ = read_events(parent_jsonl)
    types = [e.get("type") for e in events]
    assert "child_graceful_exited" in types, f"应含 child_graceful_exited，实际 {types}"
    assert "child_failed" in types, f"应含 child_failed，实际 {types}"
    assert "node_skipped" in types, f"应含 node_skipped（sub-b skip），实际 {types}"

    assert node_a in run_state.node_outputs, "sub-a 应被回填到 node_outputs"
    assert node_b in run_state.node_outputs, "sub-b 应被回填到 node_outputs"
    assert run_state.node_outputs[node_a]["state"] == "completed"
    assert run_state.node_outputs[node_b]["state"] == "skipped"


# ============================================================================
# 边界：子 sub_runs 目录不存在 → 返回 False
# ============================================================================

def test_poll_returns_false_when_no_sub_runs_dir(tmp_path: Path) -> None:
    """sub_runs 目录不存在时直接返回 False，不报错。"""
    run_dir = tmp_path / "runs" / "PARENT-NONE"
    run_dir.mkdir(parents=True)
    parent_jsonl = run_dir / "run-state.jsonl"
    run_state = _make_run_state(run_id="PARENT-NONE")
    workflow = _make_workflow([])

    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)
    assert advanced is False


# ============================================================================
# 边界：子 jsonl 不在终态 → 跳过，不回填
# ============================================================================

def test_poll_skips_non_terminal_child(tmp_path: Path) -> None:
    """子 run 尚未到终态（只有 workflow_started）→ 跳过，父 jsonl 无新事件。"""
    node_id = "sub-running"
    run_dir = tmp_path / "runs" / "PARENT-RUN"
    run_dir.mkdir(parents=True)

    _write_sub_jsonl(run_dir / "sub_runs" / node_id, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-RUN",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-RUN")
    workflow = _make_workflow([{"id": node_id, "sub_workflow": {"template": "child-wf"}}])

    events_before, _ = read_events(parent_jsonl)
    advanced = _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)
    events_after, _ = read_events(parent_jsonl)

    assert advanced is False
    assert len(events_after) == len(events_before), "非终态子 run 不应追加事件"


# ============================================================================
# 边界：on_subworkflow_failure=fail 时写 workflow_failed 幂等（state 已 failed 不重复写）
# ============================================================================

def test_fail_policy_no_duplicate_workflow_failed(tmp_path: Path) -> None:
    """fail 策略：run_state.state 已 failed 时不重复写 workflow_failed。"""
    node_id = "sub-dup-fail"
    run_dir = tmp_path / "runs" / "PARENT-DUP"
    run_dir.mkdir(parents=True)

    _write_sub_jsonl(run_dir / "sub_runs" / node_id, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_failed", "data": {"error": "err"}, "ts": "2026-05-15T00:01:00Z"},
    ])
    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-DUP",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    # 父已 failed（前一轮已写过 workflow_failed）
    run_state = _make_run_state(run_id="PARENT-DUP")
    run_state.state = "failed"
    workflow = _make_workflow([{
        "id": node_id, "sub_workflow": {"template": "child-wf"},
        "on_subworkflow_failure": "fail",
    }])

    _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    events, _ = read_events(parent_jsonl)
    wf_failed_count = sum(1 for e in events if e.get("type") == "workflow_failed")
    assert wf_failed_count == 0, (
        f"state 已 failed 时不应再写 workflow_failed，实际写了 {wf_failed_count} 条"
    )
