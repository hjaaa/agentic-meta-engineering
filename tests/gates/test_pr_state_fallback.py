"""F-005 · pr_state CLOSED INFO 化 + gh 失败兜底测试。

覆盖：
  - CLOSED 状态返回 PASS + pr_state_closed=True + severity_hint="info"
  - gh 失败时 vars 含 gh_call_failed=True（既有逻辑，在此复验）
"""
from __future__ import annotations

import json
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
    def _impl(*args, **kwargs):
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)
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
    """given_gh_returns_non_zero_when_run_then_pass_gh_call_failed_true（gh 失败降级保持）。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run("", returncode=1),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))

    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    # CLOSED 特有标记不应在 gh 完全失败时出现（两条路径互不干扰）
    assert "pr_state_closed" not in report.vars
    assert "WARNING" in capsys.readouterr().err


def test_gh_file_not_found_fallback(monkeypatch, capsys):
    """given_gh_binary_missing_when_run_then_pass_not_closed_variant。"""

    def _raise(*args, **kwargs):
        raise FileNotFoundError("gh: command not found")

    monkeypatch.setattr(plugin_mod.subprocess, "run", _raise)
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=99))

    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    assert "pr_state_closed" not in report.vars
