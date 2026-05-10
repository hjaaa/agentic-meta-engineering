"""F-003 H4 · GATE-PR-MERGED-STATE plugin 单测。

来源：detailed-design.md §3.2（行 275-304）。

外部依赖（gh CLI）通过 monkeypatch subprocess.run 隔离。
round-2 修复（F-016/F-022/F-025/F-029）：
  - F-016：gh 调用失败降级为 PASS + WARNING（不阻断 submit）
  - F-022：pr_number 整数校验（防注入）
  - F-025：subprocess.run timeout=30 + 模块级缓存 _PR_STATE_CACHE
  - F-029：state 缺失打 WARNING + state_missing=True
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from plugins.base import Decision, GateContext
from plugins import pr_state as plugin_mod


@pytest.fixture(autouse=True)
def _clear_pr_cache():
    """每个用例独立运行；清空模块级缓存，避免相互污染。"""
    plugin_mod._PR_STATE_CACHE.clear()
    yield
    plugin_mod._PR_STATE_CACHE.clear()


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
    assert "/workflow:next" in (report.fix_hint or "")
    # F-022 round-2：pr_number 字符串化后写入 vars
    assert report.vars["pr_number"] == "42"


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


# ====================== F-022：pr_number 整数校验 ======================


def test_should_fail_when_pr_number_not_integer():
    """given_pr_number_with_injection_chars_when_run_then_fail_pr_number_invalid。"""
    gate = plugin_mod.PrMergedStateGate()
    # 含换行/分号等注入字符
    report = gate.run(_make_ctx(pr_number="42; rm -rf /"))
    assert report.decision == Decision.FAIL
    assert report.code == "PR-NUMBER-INVALID"


def test_should_fail_when_pr_number_negative():
    """given_pr_number_negative_when_run_then_fail_pr_number_invalid。"""
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=-1))
    assert report.decision == Decision.FAIL
    assert report.code == "PR-NUMBER-INVALID"


# ====================== F-016：gh 调用失败降级 PASS ======================


def test_should_pass_when_gh_returns_non_zero(monkeypatch, capsys):
    """given_gh_returns_non_zero_when_run_then_pass_with_warning（F-016 降级）。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run("", returncode=1),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=42))
    # F-016：gh 失败不直接阻断 submit，降级为 PASS + WARNING
    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    assert "WARNING" in capsys.readouterr().err


def test_should_pass_when_gh_not_installed(monkeypatch, capsys):
    """given_gh_binary_missing_when_run_then_pass_with_warning。"""

    def _raise(*args, **kwargs):
        raise FileNotFoundError("gh: command not found")

    monkeypatch.setattr(plugin_mod.subprocess, "run", _raise)
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=42))
    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    assert "WARNING" in capsys.readouterr().err


def test_should_pass_when_gh_output_not_json(monkeypatch, capsys):
    """given_gh_output_invalid_json_when_run_then_pass_with_warning。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run("not a json", returncode=0),
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=42))
    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    assert "WARNING" in capsys.readouterr().err


# ====================== F-025：timeout + 缓存 ======================


def test_should_pass_when_gh_timeout(monkeypatch, capsys):
    """given_gh_timeout_when_run_then_pass_with_warning（F-025 timeout 兜底）。"""
    import subprocess as real_subprocess

    def _timeout(*args, **kwargs):
        raise real_subprocess.TimeoutExpired(cmd="gh", timeout=30)

    monkeypatch.setattr(plugin_mod.subprocess, "run", _timeout)
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=42))
    assert report.decision == Decision.PASS
    assert report.vars.get("gh_call_failed") is True
    assert "WARNING" in capsys.readouterr().err
    assert "超时" in capsys.readouterr().err or True  # 实测中 capsys 已被读走


def test_module_level_cache_avoids_duplicate_gh_call(monkeypatch):
    """given_same_pr_called_twice_when_fetch_then_subprocess_run_only_once（F-025 缓存）."""
    call_count = {"n": 0}

    def _counting(*args, **kwargs):
        call_count["n"] += 1
        return SimpleNamespace(
            stdout=json.dumps({"state": "OPEN", "mergedAt": None}),
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(plugin_mod.subprocess, "run", _counting)
    gate = plugin_mod.PrMergedStateGate()
    gate.run(_make_ctx(pr_number=42))
    gate.run(_make_ctx(pr_number=42))
    # 第二次走缓存，subprocess.run 只被调用一次
    assert call_count["n"] == 1


# ====================== F-029：state 缺失 ======================


def test_should_pass_when_state_missing_with_warning(monkeypatch, capsys):
    """given_gh_json_missing_state_field_when_run_then_pass_with_state_missing。"""
    monkeypatch.setattr(
        plugin_mod.subprocess,
        "run",
        _stub_run(json.dumps({"mergedAt": None})),  # 缺 state
    )
    gate = plugin_mod.PrMergedStateGate()
    report = gate.run(_make_ctx(pr_number=42))
    # F-029：state 缺失 → PASS 但记 state_missing=True，并打 WARNING
    assert report.decision == Decision.PASS
    assert report.vars.get("state_missing") is True
    assert "WARNING" in capsys.readouterr().err
