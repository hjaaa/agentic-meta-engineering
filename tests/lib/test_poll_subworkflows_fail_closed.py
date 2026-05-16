"""F-011 · _poll_sub_workflows fail-closed 回归子测试（AC-9 / AC-10 / AC-11）。

IB-35：从 test_poll_subworkflows.py 抽出，避免主文件越 complexity-checker 阈值 500 行。
本组测试统一覆盖：append_event 失败时，三类 _handle_child_* helper 必须把底层
WorkflowError 用 `raise WorkflowError(...) from exc` 包装向上抛，PEP 3134
chained traceback（`__cause__`）必须非 None，便于排障时定位真实失败源。

测试用例：
- TC-AC9 : _handle_child_completed append_event 失败 → WorkflowError + __cause__ 保留
- TC-AC10: _handle_child_failed_by_policy（skip）append_event 失败 → 同上
- TC-AC11: _handle_child_cancelled append_event 失败 → 同上

运行：
    python3 -m pytest tests/lib/test_poll_subworkflows_fail_closed.py -v

来源：reviews/code-F-011-002.json F2-CR-001 (test 553 行越阈值) + features.json AC-9/10/11。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from common import WorkflowError  # noqa: E402
from run_state import RunState  # noqa: E402
from workflow_continue import _poll_sub_workflows  # noqa: E402


# ============================================================================
# 辅助函数（与 test_poll_subworkflows.py 同源；本文件仅承担 AC-9/10/11 三测试，
# 与主文件解耦后保留必需 helper 副本，避免引入跨文件 fixture 依赖）
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
# AC-9 / AC-10 / AC-11 fail-closed 回归
# ============================================================================

def test_handle_child_completed_propagates_workflow_error_when_append_fails(
    tmp_path: Path,
) -> None:
    """AC-9: _handle_child_completed append_event 失败 → WorkflowError 向上传播（chained traceback 保留）。"""
    node_id = "sub-fc-completed"
    run_dir = tmp_path / "runs" / "PARENT-FC1"
    run_dir.mkdir(parents=True)

    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_completed", "data": {}, "ts": "2026-05-15T00:01:00Z"},
    ])
    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-FC1",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-FC1")
    workflow = _make_workflow([{"id": node_id, "sub_workflow": {"template": "child-wf"}}])

    with patch("workflow_continue.append_event",
               side_effect=WorkflowError("simulated I/O fail")) as _mock:
        with pytest.raises(WorkflowError) as exc_info:
            _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert exc_info.value.__cause__ is not None, "chained traceback (__cause__) 应被保留"


def test_handle_child_failed_by_policy_propagates_workflow_error_when_append_fails(
    tmp_path: Path,
) -> None:
    """AC-10: _handle_child_failed_by_policy（skip）append_event 失败 → WorkflowError 向上传播。"""
    node_id = "sub-fc-failed"
    run_dir = tmp_path / "runs" / "PARENT-FC2"
    run_dir.mkdir(parents=True)

    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_failed", "data": {"error": "oops"}, "ts": "2026-05-15T00:01:00Z"},
    ])
    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-FC2",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-FC2")
    workflow = _make_workflow([{
        "id": node_id, "sub_workflow": {"template": "child-wf"},
        "on_subworkflow_failure": "skip",
    }])

    with patch("workflow_continue.append_event",
               side_effect=WorkflowError("simulated I/O fail")) as _mock:
        with pytest.raises(WorkflowError) as exc_info:
            _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert exc_info.value.__cause__ is not None, "chained traceback (__cause__) 应被保留"


def test_handle_child_cancelled_propagates_workflow_error_when_append_fails(
    tmp_path: Path,
) -> None:
    """AC-11: _handle_child_cancelled append_event 失败 → WorkflowError 向上传播（chained traceback 保留）。"""
    node_id = "sub-fc-cancelled"
    run_dir = tmp_path / "runs" / "PARENT-FC3"
    run_dir.mkdir(parents=True)

    sub_run_dir = run_dir / "sub_runs" / node_id
    _write_sub_jsonl(sub_run_dir, [
        {"type": "workflow_started", "run_id": node_id,
         "data": {"workflow_name": "child-wf"}, "ts": "2026-05-15T00:00:00Z"},
        {"type": "workflow_cancelled", "data": {}, "ts": "2026-05-15T00:01:00Z"},
    ])
    parent_jsonl = _write_parent_jsonl(run_dir, [
        {"type": "workflow_started", "run_id": "PARENT-FC3",
         "data": {"workflow_name": "parent-wf"}, "ts": "2026-05-15T00:00:00Z"},
    ])
    run_state = _make_run_state(run_id="PARENT-FC3")
    workflow = _make_workflow([{"id": node_id, "sub_workflow": {"template": "child-wf"}}])

    with patch("workflow_continue.append_event",
               side_effect=WorkflowError("simulated I/O fail")) as _mock:
        with pytest.raises(WorkflowError) as exc_info:
            _poll_sub_workflows(run_state, workflow, run_dir, parent_jsonl)

    assert exc_info.value.__cause__ is not None, "chained traceback (__cause__) 应被保留"
