"""F-005 · pr_state CLOSED INFO 化 + gh 失败兜底 + ls-remote fallback 测试（F-10）。

覆盖：
  - CLOSED 状态返回 PASS + pr_state_closed=True + severity_hint="info"
  - gh 失败时 vars 含 gh_call_failed=True（既有逻辑，在此复验）
  - F-10：gh 失败 + ls-remote 成功 → PASS + gh_call_failed=True + ls_remote_ok=True
  - F-10：gh 失败 + ls-remote 失败 → PASS + gh_call_failed=True（无 ls_remote_ok）
  - F-10：gh 返回非零 + ls-remote 成功 → 进入 fallback 路径
"""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from plugins.base import Decision, GateContext
from plugins import pr_state as plugin_mod


@pytest.fixture(autouse=True)
def _clear_pr_cache():
    """每个用例独立运行，清空模块级缓存。"""
    plugin_mod._PR_STATE_CACHE.clear()
    yield
    plugin_mod._PR_STATE_CACHE.clear()


def _make_ctx(pr_number: object | None = 99, trigger: str = "submit") -> GateContext:
    meta = {}
    if pr_number is not None:
        meta["pr_number"] = pr_number
    return GateContext(trigger=trigger, requirement_id="REQ-2026-005", meta=meta)


def _stub_run(stdout: str, returncode: int = 0):
    """返回固定结果的 subprocess.run stub（适用于 gh 调用正常场景）。"""
    def _impl(*args, **kwargs):
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)
    return _impl


def _make_gh_fail_ls_remote_ok_stub(gh_exc: Exception):
    """gh 抛异常、ls-remote 返回 returncode=0 的 subprocess.run stub（F-10 测试用）。

    根据命令行第一个参数区分 gh 调用和 git ls-remote 调用。
    """
    def _impl(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if cmd and cmd[0] == "gh":
            raise gh_exc
        # git ls-remote：模拟成功（returncode=0，check=True 不抛异常）
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    return _impl


def _make_gh_fail_ls_remote_fail_stub(gh_exc: Exception, ls_remote_exc: Exception):
    """gh 和 ls-remote 都抛异常的 subprocess.run stub（F-10 测试用）。"""
    def _impl(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if cmd and cmd[0] == "gh":
            raise gh_exc
        # git ls-remote：模拟失败（抛异常）
        raise ls_remote_exc
    return _impl


def _make_gh_nonzero_ls_remote_ok_stub(gh_returncode: int = 1):
    """gh 返回非零 returncode、ls-remote 返回 returncode=0 的 stub（F-10 测试用）。

    gh 调用通过 check=False 运行，返回 returncode!=0 的 SimpleNamespace；
    ls-remote 通过 check=True 运行，returncode=0 表示成功。
    """
    def _impl(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if cmd and cmd[0] == "gh":
            return SimpleNamespace(stdout="", stderr="permission denied", returncode=gh_returncode)
        # git ls-remote：模拟成功
        return SimpleNamespace(stdout="", stderr="", returncode=0)
    return _impl


# ====================== CLOSED INFO 化 ======================


def test_should_pass_with_closed_info_markers_when_pr_closed(monkeypatch):
    """given_pr_state_closed_when_run_then_pass_with_pr_state_closed_and_severity_info（F-005）。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run(json.dumps({"state": "CLOSED", "mergedAt": None})),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))

    assert report.decision == Decision.PASS, "CLOSED 不应阻断 submit"
    assert report.vars.get("pr_state_closed") is True, "应设置 pr_state_closed=True"
    assert report.vars.get("severity_hint") == "info", "应设置 severity_hint=info"
    assert report.vars.get("state") == "CLOSED", "vars 中应保留 state=CLOSED"
    assert report.vars.get("pr_number") == "99", "vars 中应保留 pr_number 字符串化"


def test_closed_message_contains_reopen_hint(monkeypatch):
    """given_pr_closed_when_run_then_message_hints_reopen。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run(json.dumps({"state": "CLOSED", "mergedAt": None})),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))
    assert "CLOSED" in (report.message or ""), "message 应包含 CLOSED 提示"


# ====================== gh 失败兜底（复验 F-016，并验证 F-005 不破坏） ======================


def test_gh_fail_still_returns_pass_with_gh_call_failed(monkeypatch, capsys):
    """given_gh_returns_non_zero_and_ls_remote_fails_when_run_then_pass_gh_call_failed_true。

    F-016 降级路径复验（gh 返回非零 + ls-remote 也失败 → 走原始降级）。
    """
    # gh 非零，ls-remote 也非零（check=True 会抛 CalledProcessError）
    def _stub(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if cmd and cmd[0] == "gh":
            return SimpleNamespace(stdout="", stderr="", returncode=1)
        # git ls-remote 失败
        raise subprocess.CalledProcessError(128, cmd)
    monkeypatch.setattr(plugin_mod.subprocess, "run", _stub)
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))

    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    # ls_remote_ok 不应出现（ls-remote 也失败）
    assert report.vars.get("ls_remote_ok") is not True
    # CLOSED 特有标记不应出现
    assert "pr_state_closed" not in report.vars
    assert "WARNING" in capsys.readouterr().err


def test_gh_file_not_found_fallback(monkeypatch, capsys):
    """given_gh_binary_missing_and_ls_remote_fails_when_run_then_pass_gh_call_failed_true。"""

    def _stub(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if cmd and cmd[0] == "gh":
            raise FileNotFoundError("gh: command not found")
        # git ls-remote 也失败
        raise FileNotFoundError("git: command not found")

    monkeypatch.setattr(plugin_mod.subprocess, "run", _stub)
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))

    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    assert report.vars.get("ls_remote_ok") is not True
    assert "pr_state_closed" not in report.vars


# ====================== F-10：ls-remote fallback 新增用例 ======================


def test_fetch_pr_state_gh_fail_ls_remote_ok_returns_dict_with_unavailable_flag(
    monkeypatch, capsys
):
    """given_gh_file_not_found_and_ls_remote_ok_when_run_then_pass_with_ls_remote_ok_true（F-10）。

    验证：gh 抛 FileNotFoundError → ls-remote 成功 → _fetch_pr_state 返回含
    _gh_unavailable=True / _ls_remote_ok=True 的 dict；run() 最终返回
    PASS + vars gh_call_failed=True + ls_remote_ok=True。
    """
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _make_gh_fail_ls_remote_ok_stub(FileNotFoundError("gh not found")),
    )
    # 直接验证 _fetch_pr_state 的返回
    result = plugin_mod._fetch_pr_state("99")
    assert result is not None, "_fetch_pr_state 应返回非 None（ls-remote 成功）"
    assert result.get("_gh_unavailable") is True, "应含 _gh_unavailable=True"
    assert result.get("_ls_remote_ok") is True, "应含 _ls_remote_ok=True"

    # 清缓存，再通过 run() 验证端到端
    plugin_mod._PR_STATE_CACHE.clear()
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))
    assert report.decision == Decision.PASS, "ls-remote ok 路径应 PASS"
    assert report.vars.get("gh_call_failed") is True, "应含 gh_call_failed=True"
    assert report.vars.get("ls_remote_ok") is True, "应含 ls_remote_ok=True"
    assert "WARNING" in capsys.readouterr().err


def test_fetch_pr_state_gh_fail_ls_remote_fail_returns_none(monkeypatch, capsys):
    """given_gh_oserror_and_ls_remote_oserror_when_run_then_none_and_pass_no_ls_remote_ok（F-10）。

    验证：gh 抛 OSError → ls-remote 也抛 OSError → _fetch_pr_state 返回 None；
    run() 走原降级路径（PASS + gh_call_failed=True，无 ls_remote_ok）。
    """
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _make_gh_fail_ls_remote_fail_stub(
            OSError("gh network error"),
            OSError("git network error"),
        ),
    )
    result = plugin_mod._fetch_pr_state("99")
    assert result is None, "_fetch_pr_state 应返回 None（gh + ls-remote 均失败）"

    # 清缓存，再通过 run() 验证
    plugin_mod._PR_STATE_CACHE.clear()
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))
    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    assert report.vars.get("ls_remote_ok") is not True
    assert "WARNING" in capsys.readouterr().err


def test_fetch_pr_state_gh_returncode_nonzero_triggers_ls_remote(monkeypatch, capsys):
    """given_gh_returncode_1_and_ls_remote_ok_when_run_then_pass_with_ls_remote_ok（F-10）。

    验证：gh 安装但返回 returncode=1（权限不足等）→ 触发 ls-remote fallback；
    ls-remote 成功 → run() 返回 PASS + gh_call_failed=True + ls_remote_ok=True。
    """
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _make_gh_nonzero_ls_remote_ok_stub(gh_returncode=1),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))

    assert report.decision == Decision.PASS, "gh 非零+ls-remote ok 路径应 PASS"
    assert report.vars.get("gh_call_failed") is True, "应含 gh_call_failed=True"
    assert report.vars.get("ls_remote_ok") is True, "应含 ls_remote_ok=True"
    assert "WARNING" in capsys.readouterr().err
