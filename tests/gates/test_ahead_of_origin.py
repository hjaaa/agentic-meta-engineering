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
    # follow-up：Skip reason 必须带 PR number 利于事后审计
    assert "#99" in result.reason


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


# ====================== F-11 (codex round-5 P2)：head 限定 owner ======================


def test_pr_lookup_uses_owner_scoped_head():
    """codex F-11 (P2) 回归：gh pr list --head 必须用 OWNER:BRANCH 形式查，
    避免跨 fork / 跨 repo 同名分支假命中 skip。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    captured_cmds: list[list[str]] = []

    def _mock_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=0, stdout="hjaaa\n", stderr="")
        if cmd[:3] == ["gh", "pr", "list"]:
            return MagicMock(returncode=0, stdout='[{"number": 99}]', stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    # 应命中 skip（合法的同 owner open PR）
    assert isinstance(result, Skip), f"应 skip，实际 {result!r}"

    # 关键断言：传给 gh pr list 的 --head 参数必须是 OWNER:BRANCH 格式
    pr_list_cmd = next(c for c in captured_cmds if c[:3] == ["gh", "pr", "list"])
    head_idx = pr_list_cmd.index("--head") + 1
    assert pr_list_cmd[head_idx] == "hjaaa:feat/test-branch", (
        f"--head 应为 'hjaaa:feat/test-branch'（含 owner），实际 {pr_list_cmd[head_idx]!r}"
    )


def test_pr_lookup_falls_back_to_branch_only_when_owner_unknown():
    """codex F-11 兜底路径：gh repo view 失败时（无 owner），退化为按 branch 名查，
    保持旧 fail-closed 行为不变。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    captured_cmds: list[list[str]] = []

    def _mock_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=1, stdout="", stderr="not authenticated")
        if cmd[:3] == ["gh", "pr", "list"]:
            return MagicMock(returncode=0, stdout='[]', stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        gate.precheck(ctx)

    pr_list_cmd = next(c for c in captured_cmds if c[:3] == ["gh", "pr", "list"])
    head_idx = pr_list_cmd.index("--head") + 1
    assert pr_list_cmd[head_idx] == "feat/test-branch", (
        f"owner 缺失时应退化为只用 branch 名，实际 {pr_list_cmd[head_idx]!r}"
    )
