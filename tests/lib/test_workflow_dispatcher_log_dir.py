"""tests for workflow_dispatcher._build_env LOG_DIR 注入（Bug-12）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_dispatcher import _build_env  # noqa: E402
from run_state import RunState  # noqa: E402


def _make_state() -> RunState:
    rs = RunState.__new__(RunState)
    rs.run_id = "REQ-2099-LD"
    rs.state = "running"
    rs.current_node = None
    rs.node_outputs = {}
    rs.pending_approval = None
    rs.warnings = []
    rs.last_event_ts = None
    rs.arguments = ""
    return rs


def test_log_dir_injected_and_created(tmp_path: Path):
    run_dir = tmp_path / "REQ-2099-LD"
    run_dir.mkdir()
    env = _build_env(_make_state(), run_dir, REPO_ROOT)
    assert "LOG_DIR" in env
    log_dir = Path(env["LOG_DIR"])
    assert log_dir == (run_dir / "logs").resolve() or log_dir.name == "logs"
    assert log_dir.exists() and log_dir.is_dir()


def test_log_dir_idempotent(tmp_path: Path):
    """第二次调用不应抛"""
    run_dir = tmp_path / "REQ-2099-LD"
    run_dir.mkdir()
    _build_env(_make_state(), run_dir, REPO_ROOT)
    _build_env(_make_state(), run_dir, REPO_ROOT)  # 不抛即通过
