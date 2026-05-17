"""F-004 C 块 · GATE-GH-AUTH plugin 单测。

覆盖：pass / fail(未登录) / TimeoutExpired / FileNotFoundError / OSError。
外部依赖（gh CLI）通过 monkeypatch subprocess.run 隔离。
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace


from plugins.base import Decision, GateContext
from plugins.gh_auth import GhAuthGate, _check_gh_auth


def _make_ctx(trigger: str = "submit") -> GateContext:
    return GateContext(trigger=trigger, requirement_id="REQ-2026-002")


def _stub_run(returncode: int = 0, stderr: str = ""):
    """构造 subprocess.run 桩，返回与 CompletedProcess 兼容的对象。"""
    def _impl(*args, **kwargs):
        return SimpleNamespace(stdout="", stderr=stderr, returncode=returncode)
    return _impl


# ====================== precheck skip ======================


def test_should_skip_when_trigger_is_not_submit():
    """非 submit trigger 应直接跳过，不跑 run。"""
    gate = GhAuthGate()
    skip = gate.precheck(_make_ctx(trigger="ci"))
    assert skip is not None
    assert "submit" in skip.reason


def test_should_not_skip_when_trigger_is_submit():
    """submit trigger 应返回 None（继续跑 run）。"""
    gate = GhAuthGate()
    skip = gate.precheck(_make_ctx(trigger="submit"))
    assert skip is None


# ====================== pass ======================


def test_should_pass_when_gh_auth_status_succeeds(monkeypatch):
    """gh auth status 退出码 0 → PASS。"""
    monkeypatch.setattr(subprocess, "run", _stub_run(returncode=0))
    report = _check_gh_auth()
    assert report.decision == Decision.PASS


# ====================== fail ======================


def test_should_fail_when_gh_auth_status_fails(monkeypatch):
    """gh auth status 退出码非 0 → FAIL GH-NOT-LOGGED-IN，含修复建议。"""
    monkeypatch.setattr(subprocess, "run", _stub_run(returncode=1, stderr="not logged in"))
    report = _check_gh_auth()
    assert report.decision == Decision.FAIL
    assert report.code == "GH-NOT-LOGGED-IN"
    assert "gh auth login" in report.fix_hint


# ====================== 异常路径 ======================


def test_should_fail_on_timeout(monkeypatch):
    """subprocess.run TimeoutExpired → FAIL GH-AUTH-TIMEOUT。"""
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["gh"], timeout=10)

    monkeypatch.setattr(subprocess, "run", _timeout)
    report = _check_gh_auth()
    assert report.decision == Decision.FAIL
    assert report.code == "GH-AUTH-TIMEOUT"


def test_should_fail_when_gh_not_found(monkeypatch):
    """FileNotFoundError（gh 未安装）→ FAIL GH-NOT-FOUND。"""
    def _not_found(*args, **kwargs):
        raise FileNotFoundError("No such file: gh")

    monkeypatch.setattr(subprocess, "run", _not_found)
    report = _check_gh_auth()
    assert report.decision == Decision.FAIL
    assert report.code == "GH-NOT-FOUND"
    assert "gh auth login" in report.fix_hint


def test_should_fail_on_os_error(monkeypatch):
    """OSError（权限问题等）→ FAIL GH-OS-ERROR。"""
    def _os_err(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(subprocess, "run", _os_err)
    report = _check_gh_auth()
    assert report.decision == Decision.FAIL
    assert report.code == "GH-OS-ERROR"
