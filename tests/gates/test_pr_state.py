"""F-003 H4 · GATE-PR-MERGED-STATE plugin 单测。

来源：detailed-design.md §3.2（行 275-304）。

外部依赖（gh CLI）通过 monkeypatch subprocess.run 隔离。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from plugins.base import Decision, GateContext
from plugins import pr_state as plugin_mod


def _make_ctx(pr_number: object | None = 42, trigger: str = "submit") -> GateContext:
    meta = {}
    if pr_number is not None:
        meta["pr_number"] = pr_number
    return GateContext(trigger=trigger, requirement_id="REQ-2026-002", meta=meta)


def _stub_run(stdout: str, returncode: int = 0):
    """构造 subprocess.run 的桩；返回与 CompletedProcess 兼容的对象。"""

    def _impl(*args, **kwargs):
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)

    return _impl


# ====================== fail：MERGED ======================


def test_should_fail_when_pr_state_is_merged(monkeypatch):
    """given_pr_state_merged_when_run_then_fail_with_code_pr_merged。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run(json.dumps({"state": "MERGED", "mergedAt": "2026-04-28T00:00:00Z"})),
    )
    gate = plugin_mod.PrMergedStateGate()
    ctx = _make_ctx(pr_number=42)
    report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "PR-MERGED"
    assert "#42" in (report.message or "")
    assert "/requirement:next" in (report.fix_hint or "")
    assert report.vars["pr_number"] == 42


# ====================== pass：OPEN ======================


def test_should_pass_when_pr_state_is_open(monkeypatch):
    """given_pr_state_open_when_run_then_pass。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run(json.dumps({"state": "OPEN", "mergedAt": None})),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=44))
    assert report.decision == Decision.PASS
    assert report.vars["state"] == "OPEN"


def test_should_pass_when_pr_state_is_closed(monkeypatch):
    """given_pr_state_closed_when_run_then_pass（CLOSED 不阻断；用户自决重开）。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run(json.dumps({"state": "CLOSED", "mergedAt": None})),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=45))
    assert report.decision == Decision.PASS


# ====================== skip：缺 pr_number ======================


def test_should_skip_when_pr_number_missing():
    """given_no_pr_number_when_precheck_then_skip。"""
    gate = plugin_mod.PrMergedStateGate()
    ctx = _make_ctx(pr_number=None)
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "pr_number" in skip.reason


def test_should_skip_when_trigger_not_submit():
    """given_trigger_phase_transition_when_precheck_then_skip（防御 registry 漂移）。"""
    gate = plugin_mod.PrMergedStateGate()
    ctx = _make_ctx(pr_number=42, trigger="phase-transition")
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "submit" in skip.reason


# ====================== gh 调用失败 ======================


def test_should_fail_when_gh_returns_non_zero(monkeypatch, capsys):
    """given_gh_returns_non_zero_when_run_then_fail_with_gh_call_failed。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run("", returncode=1),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=42))
    assert report.decision == Decision.FAIL
    assert report.code == "GH-CALL-FAILED"
    assert "WARNING" in capsys.readouterr().err


def test_should_fail_when_gh_not_installed(monkeypatch, capsys):
    """given_gh_binary_missing_when_run_then_fail_with_gh_call_failed。"""

    def _raise(*args, **kwargs):
        raise FileNotFoundError("gh: command not found")

    monkeypatch.setattr(plugin_mod.subprocess, "run", _raise)
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=42))
    assert report.decision == Decision.FAIL
    assert report.code == "GH-CALL-FAILED"
    assert "WARNING" in capsys.readouterr().err


def test_should_fail_when_gh_output_not_json(monkeypatch, capsys):
    """given_gh_output_invalid_json_when_run_then_fail_with_gh_call_failed。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run("not a json", returncode=0),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=42))
    assert report.decision == Decision.FAIL
    assert report.code == "GH-CALL-FAILED"
    assert "WARNING" in capsys.readouterr().err
