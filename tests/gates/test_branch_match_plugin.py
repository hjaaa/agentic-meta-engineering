"""plugins/branch_match.py 单测（F-004 / TC-FG4-1）。

覆盖：
  - PASS：当前分支 == meta.branch
  - FAIL：当前分支 != meta.branch（R-BRANCH-MISMATCH + git switch 修复建议）
  - FAIL：meta.branch 缺失（R-BRANCH-MISMATCH + 提示补 meta）
  - FAIL：git CLI 失败 / 超时 / 不存在
  - SKIP：非 submit trigger 走 precheck 跳过
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from plugins.base import Decision, GateContext
from plugins import branch_match as plugin_mod


def _make_ctx(meta_branch="feat/req-2026-005", trigger="submit"):
    return GateContext(trigger=trigger, meta={"branch": meta_branch})


# ====================== precheck SKIP ======================


def test_branch_match_skipped_for_non_submit_trigger():
    gate = plugin_mod.BranchMatchGate()
    ctx = _make_ctx(trigger="ci")
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "非 submit" in skip.reason


def test_branch_match_precheck_passes_for_submit():
    gate = plugin_mod.BranchMatchGate()
    ctx = _make_ctx(trigger="submit")
    assert gate.precheck(ctx) is None


# ====================== PASS ======================


def test_branch_match_passes_when_match():
    gate = plugin_mod.BranchMatchGate()
    ctx = _make_ctx(meta_branch="feat/req-2026-005")
    with patch("plugins.branch_match.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="feat/req-2026-005\n", stderr="")
        report = gate.run(ctx)
    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-BRANCH-MATCH"


# ====================== FAIL ======================


def test_branch_match_fails_when_mismatch():
    gate = plugin_mod.BranchMatchGate()
    ctx = _make_ctx(meta_branch="feat/req-2026-005")
    with patch("plugins.branch_match.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="develop\n", stderr="")
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-BRANCH-MISMATCH"
    assert "develop" in report.message
    assert "feat/req-2026-005" in report.message
    assert report.fix_hint == "git switch feat/req-2026-005"


def test_branch_match_fails_when_meta_branch_missing():
    gate = plugin_mod.BranchMatchGate()
    ctx = GateContext(trigger="submit", meta={})  # 无 branch 字段
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-BRANCH-MISMATCH"
    assert "缺失" in report.message


def test_branch_match_fails_when_git_returns_nonzero():
    gate = plugin_mod.BranchMatchGate()
    ctx = _make_ctx()
    with patch("plugins.branch_match.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal: not a git repository")
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-BRANCH-MISMATCH"
    assert "退出非零" in report.message


def test_branch_match_fails_on_timeout():
    gate = plugin_mod.BranchMatchGate()
    ctx = _make_ctx()
    with patch("plugins.branch_match.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5)):
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert "超时" in report.message


def test_branch_match_fails_when_git_not_found():
    gate = plugin_mod.BranchMatchGate()
    ctx = _make_ctx()
    with patch("plugins.branch_match.subprocess.run", side_effect=FileNotFoundError):
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert "git CLI 未找到" in report.message
