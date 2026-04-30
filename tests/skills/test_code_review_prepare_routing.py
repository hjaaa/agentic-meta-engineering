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
  - tty 模拟：通过环境变量 CODE_REVIEW_ROUTING_FAKE_TTY=1 + subprocess 传入
  - 非 tty：不设该变量，stdin 接管为 PIPE（subprocess 默认非 tty）
  - 工作目录设为仓库根，确保 git config / .review-scope.json 路径正确
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# 脚本路径
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "lib" / "code_review_routing.py"

# ALL_CHECKERS 全集（与脚本保持一致）
ALL_CHECKERS = [
    "complexity-checker",
    "security-checker",
    "concurrency-checker",
    "performance-checker",
    "error-handling-checker",
    "design-consistency-checker",
    "history-context-checker",
    "auxiliary-spec-checker",
]


def _run_routing(
    args: list[str],
    stdin_text: str = "",
    fake_tty: bool = True,
    scope_out: str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """封装调用 code_review_routing.py 的通用 helper。

    参数：
      args        — 传给脚本的额外 CLI 参数
      stdin_text  — 写入 stdin 的文本（模拟用户输入）
      fake_tty    — True 则设置 CODE_REVIEW_ROUTING_FAKE_TTY=1，模拟 tty 场景
      scope_out   — --scope-out 参数；默认传 tmpdir 下的临时路径
      cwd         — 工作目录；默认使用仓库根

    返回 CompletedProcess（capture_output=True）。
    """
    env = os.environ.copy()
    if fake_tty:
        env["CODE_REVIEW_ROUTING_FAKE_TTY"] = "1"
    else:
        env.pop("CODE_REVIEW_ROUTING_FAKE_TTY", None)

    cmd = [sys.executable, str(_SCRIPT)]
    if scope_out:
        cmd += ["--scope-out", scope_out]
    cmd += args

    return subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd or _REPO_ROOT),
    )


# ──────────────────────────────────────────────
# TC-A1: tty + accept → decision=accept，scope.json 存在
# ──────────────────────────────────────────────
def test_tc_a1_accept_writes_scope_with_ai_route(tmp_path):
    """given_tty_when_accept_then_scope_json_contains_ai_suggested_route_and_returncode_0。"""
    scope_out = str(tmp_path / ".review-scope.json")

    result = _run_routing(
        args=[],
        stdin_text="accept\n",
        fake_tty=True,
        scope_out=scope_out,
    )

    assert result.returncode == 0, f"期望 returncode=0，实际={result.returncode}\nstderr={result.stderr}"

    # scope.json 必须存在
    scope_path = Path(scope_out)
    assert scope_path.exists(), "期望 .review-scope.json 被写入，但文件不存在"

    with scope_path.open(encoding="utf-8") as f:
        scope = json.load(f)

    # decision 必须为 accept
    confirmed = scope.get("routing_confirmed_by", {})
    assert confirmed.get("decision") == "accept", (
        f"期望 decision=accept，实际={confirmed.get('decision')}"
    )
    assert confirmed.get("tty_verified") is True, "期望 tty_verified=True"

    # checker_route 必须是 ALL_CHECKERS 的非空子集
    route = scope.get("checker_route", [])
    assert isinstance(route, list) and len(route) > 0, (
        f"期望 checker_route 非空列表，实际={route}"
    )
    assert all(c in ALL_CHECKERS for c in route), (
        f"checker_route 含非法 checker：{route}"
    )

    # mode_hint 必须为 default（非 --all / --trivial）
    assert scope.get("mode_hint") == "default", (
        f"期望 mode_hint=default，实际={scope.get('mode_hint')}"
    )


# ──────────────────────────────────────────────
# TC-A2: tty + all → decision=all，8 全集
# ──────────────────────────────────────────────
def test_tc_a2_all_writes_8_checker_full_set(tmp_path):
    """given_tty_when_all_then_scope_json_contains_all_8_checkers_and_returncode_0。"""
    scope_out = str(tmp_path / ".review-scope.json")

    result = _run_routing(
        args=[],
        stdin_text="all\n",
        fake_tty=True,
        scope_out=scope_out,
    )

    assert result.returncode == 0, f"returncode={result.returncode}\nstderr={result.stderr}"

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


# ──────────────────────────────────────────────
# TC-A3: tty + abort → scope.json 不存在，returncode 0，stderr 含 aborted
# ──────────────────────────────────────────────
def test_tc_a3_abort_does_not_write_scope(tmp_path):
    """given_tty_when_abort_then_no_scope_json_and_returncode_0_and_stderr_contains_aborted。"""
    scope_out = str(tmp_path / ".review-scope.json")

    result = _run_routing(
        args=[],
        stdin_text="abort\n",
        fake_tty=True,
        scope_out=scope_out,
    )

    assert result.returncode == 0, f"returncode={result.returncode}\nstderr={result.stderr}"

    scope_path = Path(scope_out)
    assert not scope_path.exists(), "abort 时不应写入 .review-scope.json，但文件存在"

    assert "aborted by user" in result.stderr, (
        f"期望 stderr 含 'aborted by user'，实际 stderr={result.stderr!r}"
    )


# ──────────────────────────────────────────────
# TC-A4: tty + 非法输入 → returncode 1，stderr 含 'invalid token'
# ──────────────────────────────────────────────
def test_tc_a4_invalid_token_returns_rc1(tmp_path):
    """given_tty_when_garbage_input_then_returncode_1_and_stderr_contains_invalid_token。"""
    scope_out = str(tmp_path / ".review-scope.json")

    result = _run_routing(
        args=[],
        stdin_text="xxgarbage\n",
        fake_tty=True,
        scope_out=scope_out,
    )

    assert result.returncode == 1, f"期望 returncode=1，实际={result.returncode}\nstderr={result.stderr}"
    assert "invalid token" in result.stderr, (
        f"期望 stderr 含 'invalid token'，实际={result.stderr!r}"
    )


# ──────────────────────────────────────────────
# TC-A5: 非 tty stdin，无标志 → returncode 2，stderr 含特定文字
# ──────────────────────────────────────────────
def test_tc_a5_non_tty_default_returns_rc2(tmp_path):
    """given_non_tty_when_no_flags_then_returncode_2_and_stderr_contains_not_a_tty。"""
    scope_out = str(tmp_path / ".review-scope.json")

    result = _run_routing(
        args=[],
        stdin_text="",
        fake_tty=False,  # 不设 FAKE_TTY，stdin=PIPE 即为非 tty
        scope_out=scope_out,
    )

    assert result.returncode == 2, f"期望 returncode=2，实际={result.returncode}\nstderr={result.stderr}"
    assert "routing: stdin not a tty" in result.stderr, (
        f"期望 stderr 含 'routing: stdin not a tty'，实际={result.stderr!r}"
    )


# ──────────────────────────────────────────────
# TC-A6: 非 tty + --all → returncode 2（--all 同样不豁免 tty 校验）
# ──────────────────────────────────────────────
def test_tc_a6_non_tty_with_all_flag_returns_rc2(tmp_path):
    """given_non_tty_when_all_flag_then_returncode_2_prevents_ai_bypass。"""
    scope_out = str(tmp_path / ".review-scope.json")

    result = _run_routing(
        args=["--all"],
        stdin_text="",
        fake_tty=False,
        scope_out=scope_out,
    )

    assert result.returncode == 2, f"期望 returncode=2，实际={result.returncode}\nstderr={result.stderr}"
    assert "routing: stdin not a tty" in result.stderr, (
        f"期望 stderr 含 'routing: stdin not a tty'，实际={result.stderr!r}"
    )


# ──────────────────────────────────────────────
# TC-A7: 全空 issues 流水线 → quality-reviewer 出 looks_clean
# 属于 F-003 范畴，本期跳过，F-003 实施后启用
# ──────────────────────────────────────────────
@pytest.mark.skip(reason="TODO F-003: code-quality-reviewer 输出 looks_clean 场景，待 F-003 实施后启用")
def test_tc_a7_empty_issues_pipeline_produces_looks_clean():
    """given_all_checkers_return_empty_issues_when_pipeline_runs_then_conclusion_is_looks_clean。

    TODO：F-003 实施完成后，本用例需：
      1. Mock 8 个 checker 返回空 issues
      2. 验证 quality-reviewer 输出 conclusion=looks_clean
      3. 验证报告中裁决明细段保留（不为空）
    """
    pass
