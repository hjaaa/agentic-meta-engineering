"""code-review-prepare 路由 CLI 测试（TC-A1 ~ A6 + TC-A7 skip）。

覆盖范围：
  TC-A1  tty + accept → scope.json 写 AI 建议子集，decision=accept，returncode 0
  TC-A2  tty + all    → scope.json 写 8 全集，decision=all，returncode 0
  TC-A3  tty + abort  → scope.json 不存在，returncode 0，stderr 含 'aborted by user'
  TC-A4  tty + 非法   → returncode 1，stderr 含 'invalid token'
  TC-A5  非 tty       → returncode 2，stderr 含 'routing: stdin not a tty'
  TC-A6  非 tty + --all → returncode 2（--all 同样拒绝非 tty）

TC-A7（全空 issues 流水线 → quality-reviewer 出 looks_clean）属于 F-003 范畴，
本期跳过——F-003 实施后启用。

实现说明：
  - TC-A1~A4（tty 交互场景）：函数级单测，用 monkeypatch mock _is_tty 和 stdin，
    直接调脚本内部函数，不通过 subprocess，不依赖任何 env var 旁路。
  - TC-A5/A6（非 tty 端到端拒收）：保留 subprocess，stdin=PIPE 自动为非 tty，
    断言 returncode==2 + stderr 含 'routing: stdin not a tty'。
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# ── 模块导入（scripts/lib 无 __init__.py，用 sys.path.insert 风格）──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _REPO_ROOT / "scripts" / "lib"
_SCRIPT = _SCRIPTS_LIB / "code_review_routing.py"

# 仅在首次插入（避免重复）
if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

import code_review_routing as routing  # noqa: E402

# ALL_CHECKERS 全集（与脚本保持一致）
ALL_CHECKERS = routing.ALL_CHECKERS


# ════════════════════════════════════════════════
# 辅助：mock tty + stdin 的上下文管理器
# ════════════════════════════════════════════════

def _make_fake_stdin(text: str) -> io.StringIO:
    """创建带 isatty=True 的假 stdin。"""
    fake = io.StringIO(text)
    fake.isatty = lambda: True  # type: ignore[attr-defined]
    return fake


# ════════════════════════════════════════════════
# TC-A1: tty + accept → decision=accept，scope.json 存在
# ════════════════════════════════════════════════

def test_tc_a1_accept_writes_scope_with_ai_route(tmp_path, monkeypatch):
    """given_tty_when_accept_then_scope_json_contains_ai_suggested_route_and_returncode_0。"""
    scope_out = str(tmp_path / ".review-scope.json")
    fake_stdin = _make_fake_stdin("accept\n")

    # mock：_is_tty 返回 True，sys.stdin 替换为假 stdin
    monkeypatch.setattr(routing, "_is_tty", lambda: True)
    monkeypatch.setattr(routing.sys, "stdin", fake_stdin)

    # 调用默认模式（diff 从 git 获取，git 在 repo 根可用）
    # diff_stat_stdin=False → 内部会调 git diff，可能失败但不阻塞流程
    routing._run_default_mode(scope_out=scope_out, trivial=False, diff_stat_stdin=False)

    # scope.json 必须存在
    scope_path = Path(scope_out)
    assert scope_path.exists(), "期望 .review-scope.json 被写入，但文件不存在"

    with scope_path.open(encoding="utf-8") as f:
        scope = json.load(f)

    confirmed = scope.get("routing_confirmed_by", {})
    assert confirmed.get("decision") == "accept", (
        f"期望 decision=accept，实际={confirmed.get('decision')}"
    )
    assert confirmed.get("tty_verified") is True, "期望 tty_verified=True"

    route = scope.get("checker_route", [])
    assert isinstance(route, list) and len(route) > 0, (
        f"期望 checker_route 非空列表，实际={route}"
    )
    assert all(c in ALL_CHECKERS for c in route), (
        f"checker_route 含非法 checker：{route}"
    )

    assert scope.get("mode_hint") == "default", (
        f"期望 mode_hint=default，实际={scope.get('mode_hint')}"
    )


# ════════════════════════════════════════════════
# TC-A2: tty + all → decision=all，8 全集
# ════════════════════════════════════════════════

def test_tc_a2_all_writes_8_checker_full_set(tmp_path, monkeypatch):
    """given_tty_when_all_then_scope_json_contains_all_8_checkers_and_returncode_0。"""
    scope_out = str(tmp_path / ".review-scope.json")
    fake_stdin = _make_fake_stdin("all\n")

    monkeypatch.setattr(routing, "_is_tty", lambda: True)
    monkeypatch.setattr(routing.sys, "stdin", fake_stdin)

    routing._run_default_mode(scope_out=scope_out, trivial=False, diff_stat_stdin=False)

    scope_path = Path(scope_out)
    assert scope_path.exists(), ".review-scope.json 不存在"

    with scope_path.open(encoding="utf-8") as f:
        scope = json.load(f)

    route = scope.get("checker_route", [])
    assert sorted(route) == sorted(ALL_CHECKERS), (
        f"期望 8 全集，实际={route}"
    )

    confirmed = scope.get("routing_confirmed_by", {})
    assert confirmed.get("decision") == "all", (
        f"期望 decision=all，实际={confirmed.get('decision')}"
    )
    assert scope.get("mode_hint") == "all", (
        f"期望 mode_hint=all，实际={scope.get('mode_hint')}"
    )


# ════════════════════════════════════════════════
# TC-A3: tty + abort → scope.json 不存在，stderr 含 aborted
# ════════════════════════════════════════════════

def test_tc_a3_abort_does_not_write_scope(tmp_path, monkeypatch, capsys):
    """given_tty_when_abort_then_no_scope_json_and_stderr_contains_aborted。"""
    scope_out = str(tmp_path / ".review-scope.json")
    fake_stdin = _make_fake_stdin("abort\n")

    monkeypatch.setattr(routing, "_is_tty", lambda: True)
    monkeypatch.setattr(routing.sys, "stdin", fake_stdin)

    routing._run_default_mode(scope_out=scope_out, trivial=False, diff_stat_stdin=False)

    scope_path = Path(scope_out)
    assert not scope_path.exists(), "abort 时不应写入 .review-scope.json，但文件存在"

    captured = capsys.readouterr()
    assert "aborted by user" in captured.err, (
        f"期望 stderr 含 'aborted by user'，实际={captured.err!r}"
    )


# ════════════════════════════════════════════════
# TC-A4: tty + 非法输入 → sys.exit(1)，stderr 含 'invalid token'
# ════════════════════════════════════════════════

def test_tc_a4_invalid_token_exits_1(tmp_path, monkeypatch, capsys):
    """given_tty_when_garbage_input_then_sys_exit_1_and_stderr_contains_invalid_token。"""
    scope_out = str(tmp_path / ".review-scope.json")
    fake_stdin = _make_fake_stdin("xxgarbage\n")

    monkeypatch.setattr(routing, "_is_tty", lambda: True)
    monkeypatch.setattr(routing.sys, "stdin", fake_stdin)

    with pytest.raises(SystemExit) as exc_info:
        routing._run_default_mode(scope_out=scope_out, trivial=False, diff_stat_stdin=False)

    assert exc_info.value.code == 1, (
        f"期望 sys.exit(1)，实际={exc_info.value.code}"
    )
    captured = capsys.readouterr()
    assert "invalid token" in captured.err, (
        f"期望 stderr 含 'invalid token'，实际={captured.err!r}"
    )


# ════════════════════════════════════════════════
# TC-A5: 非 tty stdin，无标志 → returncode 2，stderr 含特定文字
# （保留 subprocess——契约是"非 tty 进程的退出码"）
# ════════════════════════════════════════════════

def test_tc_a5_non_tty_default_returns_rc2(tmp_path):
    """given_non_tty_when_no_flags_then_returncode_2_and_stderr_contains_not_a_tty。"""
    scope_out = str(tmp_path / ".review-scope.json")

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--scope-out", scope_out],
        input="",
        capture_output=True,
        text=True,
        # stdin 接 PIPE（subprocess 默认），自动为非 tty
        cwd=str(_REPO_ROOT),
    )

    assert result.returncode == 2, (
        f"期望 returncode=2，实际={result.returncode}\nstderr={result.stderr}"
    )
    assert "routing: stdin not a tty" in result.stderr, (
        f"期望 stderr 含 'routing: stdin not a tty'，实际={result.stderr!r}"
    )


# ════════════════════════════════════════════════
# TC-A6: 非 tty + --all → returncode 2（--all 同样不豁免 tty 校验）
# （保留 subprocess——契约是"非 tty 进程的退出码"）
# ════════════════════════════════════════════════

def test_tc_a6_non_tty_with_all_flag_returns_rc2(tmp_path):
    """given_non_tty_when_all_flag_then_returncode_2_prevents_ai_bypass。"""
    scope_out = str(tmp_path / ".review-scope.json")

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--scope-out", scope_out, "--all"],
        input="",
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )

    assert result.returncode == 2, (
        f"期望 returncode=2，实际={result.returncode}\nstderr={result.stderr}"
    )
    assert "routing: stdin not a tty" in result.stderr, (
        f"期望 stderr 含 'routing: stdin not a tty'，实际={result.stderr!r}"
    )


# ════════════════════════════════════════════════
# TC-A7: 全空 issues 流水线 → quality-reviewer 出 looks_clean
# 属于 F-003 范畴，本期跳过，F-003 实施后启用
# ════════════════════════════════════════════════

@pytest.mark.skip(reason="TODO F-003: code-quality-reviewer 输出 looks_clean 场景，待 F-003 实施后启用")
def test_tc_a7_empty_issues_pipeline_produces_looks_clean():
    """given_all_checkers_return_empty_issues_when_pipeline_runs_then_conclusion_is_looks_clean。

    TODO：F-003 实施完成后，本用例需：
      1. Mock 8 个 checker 返回空 issues
      2. 验证 quality-reviewer 输出 conclusion=looks_clean
      3. 验证报告中裁决明细段保留（不为空）
    """
    pass
