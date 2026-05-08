"""F-001 · run_state 单测。

覆盖：
- TC-F1-3：反扫 jsonl 重建 RunState 一致；最后一行损坏跳过 + warn；node_started 无对应
  node_completed 视为残缺对（spec §13 / 风险 6）
- TC-F1-4：_resolve_run_dir 双路径（D-007）

测试运行：
    python3 -m pytest tests/lib/test_run_state.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import (  # noqa: E402
    RunState,
    WorkflowError,
    _resolve_run_dir,
    append_event,
    read_events,
    rebuild_run_state,
)


def _write_jsonl(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


# ============================================================================
# 反扫 + RunState 重建
# ============================================================================

def test_rebuild_state_from_normal_event_stream(tmp_path):
    """workflow_started + node_started + node_completed 应正确反扫。"""
    jsonl = tmp_path / "run-state.jsonl"
    _write_jsonl(jsonl, [
        {"ts": "2026-05-08T10:00:00Z", "type": "workflow_started",
         "run_id": "REQ-2026-001",
         "data": {"workflow_name": "standard-8phase", "arguments": "测试"}},
        {"ts": "2026-05-08T10:00:01Z", "type": "node_started",
         "node_id": "req-input-normalize"},
        {"ts": "2026-05-08T10:00:15Z", "type": "node_completed",
         "node_id": "req-input-normalize",
         "data": {"output": "normalized"}},
    ])
    state = rebuild_run_state(jsonl, run_id="REQ-2026-001")
    assert state.state == "running"
    assert state.workflow_name == "standard-8phase"
    assert state.arguments == "测试"
    assert state.current_node is None
    assert "req-input-normalize" in state.node_outputs
    assert state.node_outputs["req-input-normalize"]["state"] == "completed"
    assert state.node_outputs["req-input-normalize"]["output"] == "normalized"


def test_rebuild_marks_orphan_node_started_as_warning(tmp_path):
    """node_started 无对应 node_completed → warning + 节点视为 running（不入 node_outputs）。"""
    jsonl = tmp_path / "run-state.jsonl"
    _write_jsonl(jsonl, [
        {"ts": "2026-05-08T10:00:00Z", "type": "workflow_started", "run_id": "R1",
         "data": {"workflow_name": "x"}},
        {"ts": "2026-05-08T10:00:01Z", "type": "node_started", "node_id": "n-stuck"},
    ])
    state = rebuild_run_state(jsonl, run_id="R1")
    assert "n-stuck" not in state.node_outputs
    assert state.current_node == "n-stuck"
    assert any("n-stuck" in w and "残缺对" in w for w in state.warnings), state.warnings


def test_read_events_skips_broken_last_line(tmp_path):
    """spec §13：jsonl 最后一行损坏 → 跳过 + warn。"""
    jsonl = tmp_path / "run-state.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(
            {"ts": "2026-05-08T10:00:00Z", "type": "workflow_started", "run_id": "R1"}
        ) + "\n")
        fh.write('{"ts": "2026-05-08T10:00:01Z", "type": "node_started"   {invalid\n')
    events, warnings = read_events(jsonl)
    assert len(events) == 1
    assert events[0]["type"] == "workflow_started"
    assert any("最后一行" in w for w in warnings), warnings


def test_read_events_skips_broken_middle_line(tmp_path):
    """中间损坏行也要跳过且不影响后续行解析。"""
    jsonl = tmp_path / "run-state.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "1", "type": "workflow_started", "run_id": "R1"}) + "\n")
        fh.write("{not json}\n")
        fh.write(json.dumps({"ts": "2", "type": "node_started", "node_id": "n"}) + "\n")
    events, warnings = read_events(jsonl)
    assert len(events) == 2
    assert events[1]["type"] == "node_started"
    assert any("第 2 行" in w for w in warnings)


def test_read_events_skips_event_without_type(tmp_path):
    jsonl = tmp_path / "run-state.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "1", "run_id": "R1"}) + "\n")
        fh.write(json.dumps({"ts": "2", "type": "node_started", "node_id": "n"}) + "\n")
    events, warnings = read_events(jsonl)
    assert len(events) == 1
    assert any("缺 type" in w for w in warnings)


def test_read_events_returns_empty_for_missing_file(tmp_path):
    """不存在的 jsonl 应回空列表（首次启动场景）。"""
    events, warnings = read_events(tmp_path / "nope.jsonl")
    assert events == []
    assert warnings == []


def test_rebuild_handles_approval_pending_state(tmp_path):
    jsonl = tmp_path / "run-state.jsonl"
    _write_jsonl(jsonl, [
        {"ts": "1", "type": "workflow_started", "run_id": "R1",
         "data": {"workflow_name": "x"}},
        {"ts": "2", "type": "node_started", "node_id": "gate"},
        {"ts": "3", "type": "approval_pending", "node_id": "gate"},
    ])
    state = rebuild_run_state(jsonl, run_id="R1")
    assert state.state == "approval_pending"
    assert state.pending_approval == "gate"


def test_rebuild_clears_approval_after_approved(tmp_path):
    jsonl = tmp_path / "run-state.jsonl"
    _write_jsonl(jsonl, [
        {"ts": "1", "type": "workflow_started", "run_id": "R1",
         "data": {"workflow_name": "x"}},
        {"ts": "2", "type": "node_started", "node_id": "gate"},
        {"ts": "3", "type": "approval_pending", "node_id": "gate"},
        {"ts": "4", "type": "approval_approved", "node_id": "gate"},
        {"ts": "5", "type": "node_completed", "node_id": "gate", "data": {"output": "ok"}},
    ])
    state = rebuild_run_state(jsonl, run_id="R1")
    assert state.state == "running"
    assert state.pending_approval is None
    assert state.node_outputs["gate"]["state"] == "completed"


def test_rebuild_records_terminal_workflow_state(tmp_path):
    jsonl = tmp_path / "run-state.jsonl"
    _write_jsonl(jsonl, [
        {"ts": "1", "type": "workflow_started", "run_id": "R1",
         "data": {"workflow_name": "x"}},
        {"ts": "2", "type": "workflow_completed"},
    ])
    state = rebuild_run_state(jsonl, run_id="R1")
    assert state.state == "completed"


def test_rebuild_records_cancel_requested(tmp_path):
    """D-005：cancel_requested 状态可被 RunState 表征。"""
    jsonl = tmp_path / "run-state.jsonl"
    _write_jsonl(jsonl, [
        {"ts": "1", "type": "workflow_started", "run_id": "R1",
         "data": {"workflow_name": "x"}},
        {"ts": "2", "type": "node_started", "node_id": "n1"},
        {"ts": "3", "type": "cancel_requested"},
    ])
    state = rebuild_run_state(jsonl, run_id="R1")
    assert state.state == "cancel_requested"


# ============================================================================
# append_event 原子追加
# ============================================================================

def test_append_event_fills_ts_when_missing(tmp_path):
    jsonl = tmp_path / "x" / "run-state.jsonl"
    append_event(jsonl, {"type": "workflow_started", "run_id": "R1"})
    text = jsonl.read_text(encoding="utf-8")
    line = json.loads(text.strip())
    assert "ts" in line
    assert line["type"] == "workflow_started"


def test_append_event_rejects_invalid_type(tmp_path):
    with pytest.raises(WorkflowError):
        append_event(tmp_path / "j", {"type": "totally_unknown"})


def test_append_event_rejects_missing_type(tmp_path):
    with pytest.raises(WorkflowError):
        append_event(tmp_path / "j", {"run_id": "R1"})


# ============================================================================
# TC-F1-4：_resolve_run_dir 双路径（D-007）
# ============================================================================

def test_resolve_run_dir(tmp_path):
    """4 场景：requirements 命中 / runs 命中 / 都不存在 / requirements 优先。"""
    req_dir = tmp_path / "requirements" / "REQ-X"
    req_dir.mkdir(parents=True)
    runs_dir = tmp_path / "runs" / "REQ-Y"
    runs_dir.mkdir(parents=True)

    # 1) 兼容路径命中
    assert _resolve_run_dir("REQ-X", repo_root=tmp_path) == req_dir
    # 2) 新路径命中
    assert _resolve_run_dir("REQ-Y", repo_root=tmp_path) == runs_dir
    # 3) 都不存在 → WorkflowError
    with pytest.raises(WorkflowError):
        _resolve_run_dir("REQ-MISSING", repo_root=tmp_path)
    # 4) 优先级：兼容路径优先于新路径
    (tmp_path / "requirements" / "REQ-Z").mkdir(parents=True)
    (tmp_path / "runs" / "REQ-Z").mkdir(parents=True)
    resolved = _resolve_run_dir("REQ-Z", repo_root=tmp_path)
    assert resolved == tmp_path / "requirements" / "REQ-Z"


def test_resolve_run_dir_rejects_invalid_input(tmp_path):
    with pytest.raises(WorkflowError):
        _resolve_run_dir("", repo_root=tmp_path)
    with pytest.raises(WorkflowError):
        _resolve_run_dir(None, repo_root=tmp_path)  # type: ignore[arg-type]


def test_workflow_error_is_shared_class():
    """F-4：WorkflowError 在 common / workflow_loader / run_state 三处必须是同一类对象。

    任一独立 `class WorkflowError(Exception)` 重复定义都会让跨模块 except 失效
    （workflow_loader 抛出，run_state except 接不住）。本测试是回归围栏。
    """
    from common import WorkflowError as W_common
    from run_state import WorkflowError as W_run_state
    from workflow_loader import WorkflowError as W_loader

    assert W_common is W_run_state
    assert W_common is W_loader
    assert W_run_state is W_loader


# ============================================================================
# TC-F2-5：三新事件枚举写入 + 反扫识别（D-005 / D-010 联动）
# ============================================================================

def test_event_enum_extension(tmp_path):
    """F-002 · TC-F2-5：cancel_requested / parent_cancelled / parent_rolled_back
    三新事件能 append_event 写入（不抛 ValueError / WorkflowError），
    read_events 反扫不报损坏行 warn，RunState 重建在 cancel_requested 后
    state == 'cancel_requested'。
    """
    jsonl = tmp_path / "run-state.jsonl"

    # 1) workflow_started 起头
    append_event(jsonl, {
        "ts": "2026-05-08T10:00:00Z",
        "type": "workflow_started",
        "run_id": "REQ-2026-099",
        "data": {"workflow_name": "standard-8phase", "arguments": ""},
    })
    # 2) 三新事件按 D-005 / D-010 语义依次写入
    append_event(jsonl, {
        "ts": "2026-05-08T10:00:01Z",
        "type": "cancel_requested",
        "run_id": "REQ-2026-099",
        "data": {"reason": "user requested"},
    })
    append_event(jsonl, {
        "ts": "2026-05-08T10:00:02Z",
        "type": "parent_cancelled",
        "run_id": "REQ-2026-099-CHILD",
        "data": {"parent_run_id": "REQ-2026-099"},
    })
    append_event(jsonl, {
        "ts": "2026-05-08T10:00:03Z",
        "type": "parent_rolled_back",
        "run_id": "REQ-2026-099-CHILD",
        "data": {"to_node": "phase-1"},
    })

    # 3) 反扫不报损坏行 warn（type 在白名单内）
    events, warnings = read_events(jsonl)
    assert len(events) == 4, [e["type"] for e in events]
    assert {"workflow_started", "cancel_requested", "parent_cancelled",
            "parent_rolled_back"} == {e["type"] for e in events}
    # 不应出现"不在白名单"或"JSON 解析失败"类型的 warn
    bad_warns = [w for w in warnings if "不在白名单" in w or "解析失败" in w]
    assert not bad_warns, bad_warns

    # 4) RunState 重建：cancel_requested 是最后一个 workflow 级事件，state 应锁定 cancel_requested
    state = RunState.rebuild(events, run_id="REQ-2026-099")
    assert state.state == "cancel_requested", state.state


def test_event_enum_three_events_in_valid_set():
    """F-002 · TC-F2-5 围栏：三新事件必须存在于 VALID_EVENT_TYPES。

    若 F-001 后续有人误删事件枚举，本测试会立即红灯（D-005 / D-010 联动失效）。
    """
    from run_state import VALID_EVENT_TYPES

    for event_type in ("cancel_requested", "parent_cancelled", "parent_rolled_back"):
        assert event_type in VALID_EVENT_TYPES, f"事件 {event_type} 缺失于 VALID_EVENT_TYPES"
