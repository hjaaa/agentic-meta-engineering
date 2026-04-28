"""plugins/workspace_clean.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（git 命令）通过 monkeypatch 模拟。
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

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


def test_workspace_clean_precheck_always_returns_none():
    """given_any_trigger_when_precheck_then_no_skip（skip fixture：registry 层过滤，precheck 恒 None）。

    F-031：ci 守卫已从 precheck 中删除（registry triggers 不含 ci，属死代码）。
    skip 路径由 runner 的 filter_gates 在 trigger 不命中时保证，precheck 本身恒返回 None。
    """
    gate = plugin_mod.WorkspaceCleanGate()
    for trigger in ("pre-commit", "phase-transition", "submit", "post-dev", "ci"):
        ctx = GateContext(trigger=trigger)
        assert gate.precheck(ctx) is None, f"precheck should return None for trigger={trigger}"


def test_workspace_clean_does_not_skip_on_post_dev():
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="post-dev")
    assert gate.precheck(ctx) is None


def test_workspace_clean_does_not_skip_on_phase_transition():
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="phase-transition")
    assert gate.precheck(ctx) is None
