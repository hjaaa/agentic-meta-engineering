"""tests for workflow_status._render_status failed/running 分桶（Bug-6）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_status import _render_status  # noqa: E402
from run_state import RunState  # noqa: E402


def _make_state(node_outputs: dict) -> RunState:
    """构造一个最小化 RunState 用于格式化测试。"""
    rs = RunState.__new__(RunState)
    rs.run_id = "test-run"
    rs.state = "running"
    rs.current_node = None
    rs.node_outputs = node_outputs
    rs.pending_approval = None
    rs.warnings = []
    rs.last_event_ts = None
    return rs


def test_failed_node_separate_bucket(tmp_path):
    """node_outputs 含 state=failed → 单独 failed 桶，不混入 completed"""
    state = _make_state({
        "node-a": {"state": "completed"},
        "node-b": {"state": "failed"},
        "node-c": {"state": "completed"},
    })
    out = _render_status(state, tmp_path)
    lines = out.splitlines()
    completed_line = next((l for l in lines if "completed (" in l), None)
    failed_line = next((l for l in lines if "failed (" in l), None)
    assert completed_line is not None
    assert "node-a" in completed_line and "node-c" in completed_line
    assert "node-b" not in completed_line
    assert failed_line is not None
    assert "node-b" in failed_line
    assert "failed (1)" in failed_line


def test_no_failed_no_failed_line(tmp_path):
    """无 failed 节点时不出 failed 行"""
    state = _make_state({"node-a": {"state": "completed"}})
    out = _render_status(state, tmp_path)
    assert "failed (" not in out


def test_running_bucket_present(tmp_path):
    """state 非 completed/skipped/failed → running 桶"""
    state = _make_state({
        "node-a": {"state": "completed"},
        "node-b": {"state": "running"},
    })
    out = _render_status(state, tmp_path)
    assert "running (1)" in out
    assert "node-b" in [
        token for l in out.splitlines() if "running (" in l
        for token in l.split()
    ] or "node-b" in out
