"""plugins/workspace_clean.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（git 命令）通过 monkeypatch 模拟。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plugins.base import Decision, GateContext
from plugins import workspace_clean as plugin_mod


# ====================== pass 用例 ======================


def test_workspace_clean_passes_when_clean():
    """given_clean_workspace_when_run_then_pass（pass fixture）."""
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="post-dev")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-WORKSPACE-CLEAN"


# ====================== fail 用例 ======================


def test_workspace_clean_fails_when_dirty():
    """given_dirty_workspace_when_run_then_fail（fail fixture）."""
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="post-dev")

    dirty_output = " M scripts/foo.py\n?? new_file.txt"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=dirty_output, returncode=0)
        report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "WORKSPACE-DIRTY"
    assert "2" in (report.message or "")  # 2 处改动
    assert "dirty_files" in report.vars


def test_workspace_clean_fails_when_git_not_found():
    """given_git_missing_when_run_then_fail（git 不可用）."""
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="post-dev")

    with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "WORKSPACE-GIT-MISSING"


# ====================== skip 用例 ======================


def test_workspace_clean_skips_on_ci_trigger():
    """given_ci_trigger_when_precheck_then_skip（skip fixture）."""
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="ci")
    skip = gate.precheck(ctx)

    assert skip is not None
    assert "ci" in skip.reason.lower()


def test_workspace_clean_does_not_skip_on_post_dev():
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="post-dev")
    assert gate.precheck(ctx) is None


def test_workspace_clean_does_not_skip_on_phase_transition():
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="phase-transition")
    assert gate.precheck(ctx) is None
