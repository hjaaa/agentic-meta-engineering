"""plugins/workspace_clean.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（git 命令）通过 monkeypatch 模拟。
"""
from __future__ import annotations

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


# ====================== F-004 round-4：stash 残留过滤 ======================


def test_workspace_clean_passes_when_only_stash_residue():
    """given_only_stash_bak_when_run_then_pass：单独的 meta.yaml.bak 不应阻断 phase-transition。"""
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="phase-transition")

    stash_only = "?? requirements/REQ-2026-002/meta.yaml.bak"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=stash_only, returncode=0)
        report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-WORKSPACE-CLEAN"


def test_workspace_clean_fails_when_real_dirty_with_stash_residue():
    """given_real_dirty_plus_stash_when_run_then_fail：真实改动仍要 fail，且 message 不含 .bak 行。"""
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="phase-transition")

    mixed = (
        "?? requirements/REQ-2026-002/meta.yaml.bak\n"
        " M scripts/foo.py\n"
        "?? other_file.txt"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=mixed, returncode=0)
        report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "WORKSPACE-DIRTY"
    assert "2" in (report.message or "")  # 仅 2 处真实改动（.bak 已过滤）
    assert "meta.yaml.bak" not in (report.message or "")
    assert "scripts/foo.py" in (report.message or "")
    assert report.vars["dirty_files"] == [" M scripts/foo.py", "?? other_file.txt"]


def test_workspace_clean_does_not_filter_unrelated_bak():
    """given_unrelated_bak_when_run_then_fail：非 stash 残留的 .bak（路径不同）仍要报 dirty。"""
    gate = plugin_mod.WorkspaceCleanGate()
    ctx = GateContext(trigger="phase-transition")

    # 不是 requirements/REQ-XXX/meta.yaml.bak 模式 → 不过滤
    other_bak = "?? scripts/foo.yaml.bak"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=other_bak, returncode=0)
        report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert "scripts/foo.yaml.bak" in (report.message or "")
