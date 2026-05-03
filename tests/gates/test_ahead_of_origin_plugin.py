"""plugins/ahead_of_origin.py 单测（F-004 / TC-FG4-1 / TC-FG4-4）。

覆盖：
  - PASS：origin/<base>..HEAD 有新 commit（rev-list 输出 ≥ 1）
  - FAIL：rev-list 输出 0（R-NOTHING-TO-PUSH）
  - FAIL：base 不存在 / git 失败 / 超时 / 输出非整数
  - base 解析顺序：cli_flags.target → meta.base_branch → develop fallback
  - SKIP：非 submit trigger
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from plugins.base import Decision, GateContext
from plugins import ahead_of_origin as plugin_mod


def _make_ctx(*, base_branch=None, target=None, trigger="submit"):
    meta = {"base_branch": base_branch} if base_branch else {}
    cli_flags = {"target": target} if target else {}
    return GateContext(trigger=trigger, meta=meta, cli_flags=cli_flags)


# ====================== precheck SKIP ======================


def test_ahead_of_origin_skipped_for_non_submit_trigger():
    gate = plugin_mod.AheadOfOriginGate()
    skip = gate.precheck(_make_ctx(trigger="ci"))
    assert skip is not None
    assert "非 submit" in skip.reason


# ====================== base 解析顺序 ======================


def test_resolve_base_prefers_cli_target():
    """TC-FG4-4：cli_flags.target=main → 用 main 而非 meta.base_branch=develop。"""
    ctx = _make_ctx(base_branch="develop", target="main")
    assert plugin_mod._resolve_base(ctx) == "main"


def test_resolve_base_falls_back_to_meta():
    ctx = _make_ctx(base_branch="develop", target=None)
    assert plugin_mod._resolve_base(ctx) == "develop"


def test_resolve_base_uses_default_when_both_missing():
    ctx = _make_ctx(base_branch=None, target=None)
    assert plugin_mod._resolve_base(ctx) == "develop"


# ====================== PASS / FAIL ======================


def test_ahead_of_origin_passes_when_ahead():
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(base_branch="develop")
    with patch("plugins.ahead_of_origin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="3\n", stderr="")
        report = gate.run(ctx)
    assert report.decision == Decision.PASS


def test_ahead_of_origin_fails_when_zero_ahead():
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(base_branch="develop")
    with patch("plugins.ahead_of_origin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="0\n", stderr="")
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-NOTHING-TO-PUSH"
    assert "develop" in report.message


def test_ahead_of_origin_fails_when_target_branch_missing_remotely():
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(target="missing-branch")
    with patch("plugins.ahead_of_origin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=128, stdout="",
            stderr="fatal: bad revision 'origin/missing-branch..HEAD'",
        )
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-NOTHING-TO-PUSH"
    assert "missing-branch" in report.message


def test_ahead_of_origin_fails_on_timeout():
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(base_branch="develop")
    with patch(
        "plugins.ahead_of_origin.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
    ):
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert "超时" in report.message


def test_ahead_of_origin_fails_when_git_output_not_integer():
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(base_branch="develop")
    with patch("plugins.ahead_of_origin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="not-a-number\n", stderr="")
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert "非整数" in report.message
