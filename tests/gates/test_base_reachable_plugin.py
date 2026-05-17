"""F-004 C 块 · GATE-BASE-REACHABLE plugin 单测。

覆盖：pass / fail(分支不可达) / TimeoutExpired / FileNotFoundError / OSError。
外部依赖（git CLI）通过 monkeypatch subprocess.run 隔离。
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace


from plugins.base import Decision, GateContext
from plugins.base_reachable import BaseReachableGate, _check_branch_reachable, _resolve_base_branch


def _make_ctx(trigger: str = "submit", base_branch: str | None = None) -> GateContext:
    meta = {}
    if base_branch is not None:
        meta["base_branch"] = base_branch
    return GateContext(trigger=trigger, requirement_id="REQ-2026-002", meta=meta)


def _stub_run(returncode: int = 0, stderr: str = ""):
    """构造 subprocess.run 桩，返回与 CompletedProcess 兼容的对象。"""
    def _impl(*args, **kwargs):
        return SimpleNamespace(stdout="", stderr=stderr, returncode=returncode)
    return _impl


# ====================== precheck skip ======================


def test_should_skip_when_trigger_is_not_submit():
    """非 submit trigger 应直接跳过。"""
    gate = BaseReachableGate()
    skip = gate.precheck(_make_ctx(trigger="ci"))
    assert skip is not None
    assert "submit" in skip.reason


def test_should_not_skip_when_trigger_is_submit():
    """submit trigger 应返回 None（继续跑 run）。"""
    gate = BaseReachableGate()
    skip = gate.precheck(_make_ctx(trigger="submit"))
    assert skip is None


# ====================== base_branch 解析 ======================


def test_resolve_base_branch_uses_meta_value():
    """meta.base_branch 存在时优先使用。"""
    ctx = _make_ctx(base_branch="my-base")
    assert _resolve_base_branch(ctx) == "my-base"


def test_resolve_base_branch_fallback_to_develop():
    """meta.base_branch 缺失时 fallback develop。"""
    ctx = _make_ctx()  # 无 base_branch
    assert _resolve_base_branch(ctx) == "develop"


# ====================== pass ======================


def test_should_pass_when_fetch_succeeds(monkeypatch):
    """git fetch 退出码 0 → PASS，vars 含 base_branch。"""
    monkeypatch.setattr(subprocess, "run", _stub_run(returncode=0))
    report = _check_branch_reachable("develop")
    assert report.decision == Decision.PASS
    assert report.vars.get("base_branch") == "develop"


# ====================== fail ======================


def test_should_fail_when_fetch_fails(monkeypatch):
    """git fetch 退出码非 0 → FAIL BASE-NOT-REACHABLE，含修复建议。"""
    monkeypatch.setattr(subprocess, "run", _stub_run(returncode=128, stderr="not found"))
    report = _check_branch_reachable("develop")
    assert report.decision == Decision.FAIL
    assert report.code == "BASE-NOT-REACHABLE"
    assert "develop" in report.fix_hint


# ====================== 异常路径 ======================


def test_should_fail_on_timeout(monkeypatch):
    """subprocess.run TimeoutExpired → FAIL BASE-FETCH-TIMEOUT。"""
    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=10)

    monkeypatch.setattr(subprocess, "run", _timeout)
    report = _check_branch_reachable("develop")
    assert report.decision == Decision.FAIL
    assert report.code == "BASE-FETCH-TIMEOUT"


def test_should_fail_when_git_not_found(monkeypatch):
    """FileNotFoundError（git 未安装）→ FAIL GIT-NOT-FOUND。"""
    def _not_found(*args, **kwargs):
        raise FileNotFoundError("No such file: git")

    monkeypatch.setattr(subprocess, "run", _not_found)
    report = _check_branch_reachable("develop")
    assert report.decision == Decision.FAIL
    assert report.code == "GIT-NOT-FOUND"


def test_should_fail_on_os_error(monkeypatch):
    """OSError → FAIL GIT-OS-ERROR。"""
    def _os_err(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(subprocess, "run", _os_err)
    report = _check_branch_reachable("develop")
    assert report.decision == Decision.FAIL
    assert report.code == "GIT-OS-ERROR"
