"""plugins/ahead_of_origin.py 新增测试（F-001 B 案：open PR → Skip）。

与既有 test_ahead_of_origin_plugin.py 并存；不改既有文件，保留其回归基线。

覆盖：
  - test_skip_when_pr_open：gh pr list 返回有效列表 → precheck 返回 Skip
  - test_no_skip_when_pr_closed：gh pr list 返回 [] → precheck 返回 None
  - test_fail_closed_when_gh_missing：gh 不存在 → 不 skip（fail-closed）
  - test_fail_closed_when_gh_unauth：gh returncode=4 → 不 skip（fail-closed）
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from plugins.base import GateContext, Skip
from plugins import ahead_of_origin as plugin_mod


def _make_ctx(*, trigger: str = "submit", source_branch: str | None = None) -> GateContext:
    """构造最小 GateContext，source_branch 可选。"""
    cli_flags: dict = {}
    if source_branch is not None:
        cli_flags["source_branch"] = source_branch
    return GateContext(trigger=trigger, meta={}, cli_flags=cli_flags)


# ====================== precheck：open PR → Skip ======================


def test_skip_when_pr_open():
    """given_open_pr_for_branch_when_precheck_submit_then_skip。

    mock subprocess.run 让 git symbolic-ref 返回分支名，
    gh pr list 返回 [{number: 99}] → precheck 返回 Skip。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit")

    def _mock_run(cmd, **kwargs):
        if "symbolic-ref" in cmd:
            return MagicMock(returncode=0, stdout="feat/test-branch\n", stderr="")
        if "pr" in cmd and "list" in cmd:
            return MagicMock(returncode=0, stdout='[{"number": 99}]', stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    assert result is not None
    assert isinstance(result, Skip)
    assert "open PR" in result.reason


def test_no_skip_when_pr_closed():
    """given_no_open_pr_when_precheck_submit_then_no_skip（返回 None 走主路径）。

    gh pr list 返回 [] → _pr_open_for_branch 返回 False → precheck 返回 None。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit")

    def _mock_run(cmd, **kwargs):
        if "symbolic-ref" in cmd:
            return MagicMock(returncode=0, stdout="feat/test-branch\n", stderr="")
        if "pr" in cmd and "list" in cmd:
            return MagicMock(returncode=0, stdout="[]", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    assert result is None


# ====================== fail-closed 场景 ======================


def test_fail_closed_when_gh_missing():
    """given_gh_not_installed_when_pr_check_then_not_skip（fail-closed）。

    FileNotFoundError → _pr_open_for_branch 返回 False → precheck 不 skip。
    mock git symbolic-ref 成功，确保进到 _pr_open_for_branch 调用路径。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    # source_branch 显式给定，跳过 symbolic-ref；gh pr list 抛 FileNotFoundError
    with patch(
        "plugins.ahead_of_origin.subprocess.run",
        side_effect=FileNotFoundError("gh not found"),
    ):
        result = gate.precheck(ctx)

    assert result is None


def test_fail_closed_when_gh_unauth():
    """given_gh_returncode_4_when_pr_check_then_not_skip（fail-closed）。

    gh 已安装但未鉴权（returncode=4）→ _pr_open_for_branch 返回 False → precheck 不 skip。
    """
    gate = plugin_mod.AheadOfOriginGate()
    # 显式传 source_branch，避免触发 git symbolic-ref subprocess 调用
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    with patch("plugins.ahead_of_origin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=4, stdout="", stderr="gh auth error")
        result = gate.precheck(ctx)

    assert result is None
