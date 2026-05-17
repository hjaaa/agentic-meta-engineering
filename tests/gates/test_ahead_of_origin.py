"""plugins/ahead_of_origin.py 新增测试（F-001 B 案：open PR → Skip）。

与既有 test_ahead_of_origin_plugin.py 并存；不改既有文件，保留其回归基线。

覆盖：
  - test_skip_when_pr_open：gh pr list 返回有效列表 → precheck 返回 Skip
  - test_no_skip_when_pr_closed：gh pr list 返回 [] → precheck 返回 None
  - test_fail_closed_when_gh_missing：gh 不存在 → 不 skip（fail-closed）
  - test_fail_closed_when_gh_unauth：gh returncode=4 → 不 skip（fail-closed）
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


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
    # endpoint 在第 3 个参数；F-14 修复后必须 URL-encode（`:` → %3A，`/` → %2F）
    endpoint = api_cmd[2]
    assert "head=hjaaa%3Afeat%2Ftest-branch" in endpoint, (
        f"endpoint 必须含 URL-encoded owner-scoped head 过滤，实际 {endpoint!r}"
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


def test_pr_lookup_returns_none_when_owner_unknown():
    """codex F-15 (round-8 P2) 修订：owner 读不到时，无法构造合法 GitHub API
    head 值（API 要求 `user:ref-name` 格式），改为 fail-closed 返 None（不 skip）
    让主路径处理。
    """
    gate = plugin_mod.AheadOfOriginGate()
    ctx = _make_ctx(trigger="submit", source_branch="feat/test-branch")

    captured_cmds: list[list[str]] = []

    def _mock_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        if cmd[:3] == ["gh", "repo", "view"]:
            return MagicMock(returncode=1, stdout="", stderr="not authenticated")
        # 不应再调 gh api（owner 缺失时应直接返 None）
        if cmd[:2] == ["gh", "api"]:
            raise AssertionError(f"owner 缺失时不应调 gh api，cmd={cmd}")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("plugins.ahead_of_origin.subprocess.run", side_effect=_mock_run):
        result = gate.precheck(ctx)

    # F-15：owner 缺失 → 不 skip（让 ahead-of-origin 主路径正常跑）
    assert result is None, f"owner 缺失应不 skip，实际 {result!r}"
    # 断言：确实没调 gh api（语义层面避免不可靠 query）
    assert not any(c[:2] == ["gh", "api"] for c in captured_cmds), (
        f"owner 缺失时不应发起 gh api 调用，实际 cmd 列表={captured_cmds}"
    )


def test_pr_lookup_url_encodes_special_chars_in_branch():
    """codex F-14 (round-8 P2) 回归：branch 名含 URL 保留字符（`&`、`#`、`+` 等）
    必须做 percent-encoding，否则 query string 会被 HTTP 层解析错位，影响 head 过滤。
    """
    gate = plugin_mod.AheadOfOriginGate()
    # 故意构造含 `&` 与 `+` 的分支名（git 实际允许，URL 必须编码）
    ctx = _make_ctx(trigger="submit", source_branch="feat/foo&bar+baz")

    captured_cmds: list[list[str]] = []

    def _mock_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
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
        gate.precheck(ctx)

    api_cmd = next(c for c in captured_cmds if c[:2] == ["gh", "api"])
    endpoint = api_cmd[2]
    # 关键断言：endpoint 不含原始 `&` 或 `+`（应被编码为 %26 / %2B）；
    # 即便分支名含 & 也不会破坏 query string 的 state/per_page 等其他参数
    head_segment = endpoint.split("head=")[1].split("&")[0]
    assert "%26" in head_segment or "+" not in head_segment.replace("%2B", ""), (
        f"endpoint head 段必须 URL-encode 特殊字符，实际 {endpoint!r}"
    )
    # 更显式：encoded 形式必须出现
    assert "%26" in endpoint, f"`&` 必须编码为 %26，实际 {endpoint!r}"
    assert "%2B" in endpoint, f"`+` 必须编码为 %2B，实际 {endpoint!r}"
    assert "%3A" in endpoint, f"`:` 必须编码为 %3A（owner:branch 分隔），实际 {endpoint!r}"
