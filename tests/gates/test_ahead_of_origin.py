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
    gh api pulls?head=... 返回 JSONL 含 number → precheck 返回 Skip。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit")

    def _mock_run(cmd, **kwargs):
        if "symbolic-ref" in cmd:
            return MagicMock(returncode=0, stdout="feat/test-branch\n", stderr="")
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=0, stdout="hjaaa\n", stderr="")
        if cmd[:2] == ["gh", "api"]:
            return MagicMock(
                returncode=0,
                stdout='{"number": 99, "head_login": "hjaaa"}\n',
                stderr="",
            )
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

    gh api pulls?head=... 返回空 JSONL → _pr_open_for_branch 返回 None → precheck 返回 None。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit")

    def _mock_run(cmd, **kwargs):
        if "symbolic-ref" in cmd:
            return MagicMock(returncode=0, stdout="feat/test-branch\n", stderr="")
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=0, stdout="hjaaa\n", stderr="")
        if cmd[:2] == ["gh", "api"]:
            return MagicMock(returncode=0, stdout="", stderr="")
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


# ====================== F-11/F-12/F-13 演化路径回归 ======================


def test_pr_lookup_uses_gh_api_with_owner_scoped_head():
    """codex F-11 (P2) → F-12 (P1) → F-13 (P2) 终态：

    - F-11：跨 fork 同名分支不能假命中 skip
    - F-12：gh pr list --head 不支持 OWNER:BRANCH 语法
    - F-13：gh pr list --limit 30 cap 让本 owner PR 可能落在结果之外
    终态：直查 GitHub REST API（原生支持 head=user:branch），用 --paginate 兜全所有页。

    本测试断言：
      1. 调的是 gh api（不是 gh pr list）
      2. endpoint 含 head=hjaaa:feat/test-branch
      3. 含 --paginate 不被 limit cap 偏移
      4. 命中本 owner PR 触发 skip
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    captured_cmds: list[list[str]] = []

    def _mock_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=0, stdout="hjaaa\n", stderr="")
        if cmd[:2] == ["gh", "api"]:
            # 返回 JSONL（一行一个 JSON 对象，模拟 -q '.[] | {...}'）
            return MagicMock(
                returncode=0,
                stdout='{"number": 99, "head_login": "hjaaa"}\n',
                stderr="",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    assert isinstance(result, Skip), f"应 skip，实际 {result!r}"
    assert "#99" in (result.reason or ""), f"Skip reason 应含 #99，实际 {result!r}"

    api_cmd = next(c for c in captured_cmds if c[:2] == ["gh", "api"])
    # endpoint 在第 3 个参数
    endpoint = api_cmd[2]
    assert "head=hjaaa:feat/test-branch" in endpoint, (
        f"endpoint 必须含 owner-scoped head 过滤，实际 {endpoint!r}"
    )
    # 必须 --paginate 兜全所有页（防 F-13 limit cap）
    assert "--paginate" in api_cmd, f"必须 --paginate 防 cap 偏移，实际 cmd={api_cmd}"
    # 不应再调 gh pr list（已切到 gh api）
    assert not any(c[:3] == ["gh", "pr", "list"] for c in captured_cmds), (
        f"不应再调 gh pr list（已迁到 gh api），实际 cmd 列表={captured_cmds}"
    )


def test_pr_lookup_no_skip_when_owner_filter_returns_empty():
    """codex F-11 反向回归：API head=owner:branch 返回空 → 不 skip。"""
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    def _mock_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=0, stdout="hjaaa\n", stderr="")
        if cmd[:2] == ["gh", "api"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    assert result is None, f"无匹配 PR 应不 skip，实际 {result!r}"


def test_pr_lookup_falls_back_to_branch_only_when_owner_unknown():
    """codex F-11 兜底：gh repo view 失败 → endpoint 退化为 head=branch（无 owner）。"""
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    captured_cmds: list[list[str]] = []

    def _mock_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=1, stdout="", stderr="not authenticated")
        if cmd[:2] == ["gh", "api"]:
            return MagicMock(
                returncode=0,
                stdout='{"number": 77, "head_login": "anyone"}\n',
                stderr="",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    # owner 缺失时退化为按 branch 名查，仍触发 skip（fail-closed 由上层兜）
    assert isinstance(result, Skip), f"owner 缺失应保旧行为 skip，实际 {result!r}"
    api_cmd = next(c for c in captured_cmds if c[:2] == ["gh", "api"])
    endpoint = api_cmd[2]
    assert "head=feat/test-branch" in endpoint and ":" not in endpoint.split("head=")[1].split("&")[0], (
        f"owner 缺失时 endpoint head 不应含冒号，实际 {endpoint!r}"
    )
