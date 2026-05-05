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


# ====================== F-11 (round-5 P2) + F-12 (round-6 P1)：head 查询 + owner 过滤 ======================


def test_pr_lookup_uses_branch_only_head_and_filters_by_owner():
    """codex F-11 (P2) + F-12 (P1) 回归：

    F-11 想做的事：跨 fork 同名分支不能假命中 skip。
    F-12 暴露的问题：gh pr list --head 不支持 OWNER:BRANCH 语法（这是 gh pr create 的语法），
    传过去会让 gh 把 `:` 当成分支名一部分，永远命中空 → precheck 错误地不 skip
    → 同分支已有 open PR 的 submit 重跑被错误拦下 R-NOTHING-TO-PUSH。

    正确做法：--head 仍传分支名（gh-supported 语法）；结果用 headRepositoryOwner 后过滤。
    本测试断言：
      1. --head 参数是 branch 名（不含冒号）
      2. --json 字段含 headRepositoryOwner（用于过滤）
      3. 同 owner 的 PR 命中 skip；跨 fork 同名分支被过滤掉
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    captured_cmds: list[list[str]] = []

    def _mock_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=0, stdout="hjaaa\n", stderr="")
        if cmd[:3] == ["gh", "pr", "list"]:
            # 模拟 gh 返回一个 fork 同名分支 + 一个本 owner 的 PR
            payload = (
                '[{"number": 88, "headRepositoryOwner": {"login": "fork-user"}},'
                ' {"number": 99, "headRepositoryOwner": {"login": "hjaaa"}}]'
            )
            return MagicMock(returncode=0, stdout=payload, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    # F-11：fork 同名分支不应让我们 skip 错误（应只命中 hjaaa 的 PR）
    # 但本测试中 hjaaa 也有一个 PR，所以应该 skip
    assert isinstance(result, Skip), f"同 owner 有 open PR 应 skip，实际 {result!r}"
    # Skip reason 应包含 PR 号 99（本 owner），不是 88（fork）
    assert "99" in (result.reason or "") or "99" in (result.message or ""), (
        f"Skip reason 应引用本 owner 的 PR (#99)，实际 {result!r}"
    )

    # F-12：--head 参数必须是分支名，不含冒号
    pr_list_cmd = next(c for c in captured_cmds if c[:3] == ["gh", "pr", "list"])
    head_idx = pr_list_cmd.index("--head") + 1
    assert pr_list_cmd[head_idx] == "feat/test-branch", (
        f"--head 必须是 branch 名（gh pr list 不支持 OWNER:BRANCH 语法），实际 {pr_list_cmd[head_idx]!r}"
    )
    # F-11：--json 必须包含 headRepositoryOwner 用于后过滤
    json_idx = pr_list_cmd.index("--json") + 1
    assert "headRepositoryOwner" in pr_list_cmd[json_idx], (
        f"--json 字段必须含 headRepositoryOwner 用于过滤，实际 {pr_list_cmd[json_idx]!r}"
    )


def test_pr_lookup_no_skip_when_only_fork_has_open_pr():
    """F-11 反向：只有 fork 同名分支有 PR，本 owner 没有 → 不应 skip。"""
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    def _mock_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=0, stdout="hjaaa\n", stderr="")
        if cmd[:3] == ["gh", "pr", "list"]:
            payload = '[{"number": 88, "headRepositoryOwner": {"login": "fork-user"}}]'
            return MagicMock(returncode=0, stdout=payload, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    # 跨 fork 同名分支不应触发 skip
    assert not isinstance(result, Skip), f"只 fork 有 PR 不应 skip，实际 {result!r}"


def test_pr_lookup_falls_back_to_no_filter_when_owner_unknown():
    """F-11 兜底路径：gh repo view 失败时（owner 读不到），不做 owner 过滤，
    保留 round-5 之前的旧行为（任何同名分支 PR 都触发 skip，由上层 fail-closed 兜底）。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    def _mock_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=1, stdout="", stderr="not authenticated")
        if cmd[:3] == ["gh", "pr", "list"]:
            payload = '[{"number": 77, "headRepositoryOwner": {"login": "anyone"}}]'
            return MagicMock(returncode=0, stdout=payload, stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    # owner 缺失时不过滤，保持旧 skip 行为
    assert isinstance(result, Skip), f"owner 缺失应保旧行为 skip，实际 {result!r}"
