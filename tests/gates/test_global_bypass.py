"""tests/gates/test_global_bypass.py：CLAUDE_GATES_GLOBAL_BYPASS 全局逃生通道测试。

测试覆盖三个入口：
  1. run.py 顶部 bypass 检查（entry=runner）
  2. submit.py 顶部留痕块（entry=trigger:submit）
  3. guard.sh 顶部 bypass 检查（entry=pre-tool-use-guard）

用例设计：
  - 设环境变量 → run.py exit(0)；audit 留痕
  - 设环境变量 → submit.py 留痕 + run.py 顶部 exit(0)；audit 至少 2 行
  - 不设环境变量 → 行为不变（baseline）
  - 异常兜底：bypass 块自身故障不会 crash（except Exception: pass）

隔离策略：使用 tmp_path fixture + 改 cwd + 清理 audit/.queue，避免污染仓库根。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime as dt

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATES_DIR = _REPO_ROOT / "scripts" / "gates"


# ====================== test_run_py_bypass_exits_zero ======================


def test_run_py_bypass_exits_zero(tmp_path):
    """given_CLAUDE_GATES_GLOBAL_BYPASS_set_when_run_py_then_exit_0_and_audit_log.

    操作：tmp_path 作 cwd，运行 run.py --trigger=ci 并设环境变量。
    期望：exit 0；audit/.queue/<日期>.log 含 'BYPASS used: fix-test @ entry=runner' 行。
    """
    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "fix-test"

    result = subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}.\nstderr: {result.stderr}"

    # 检查 audit/.queue 日志
    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    assert audit_log.exists(), f"Expected audit log at {audit_log}"

    log_content = audit_log.read_text()
    assert "BYPASS used: fix-test @ entry=runner" in log_content


# ====================== test_run_py_no_bypass_normal ======================


def test_run_py_no_bypass_normal(tmp_path):
    """given_no_CLAUDE_GATES_GLOBAL_BYPASS_when_run_py_then_normal_behavior.

    操作：不设环境变量，运行 run.py --trigger=ci。
    期望：行为不变；audit 无任何行或无 BYPASS 行。
    （由于缺 registry.yaml，实际会报 ERROR，但不因 bypass 提前 exit）
    """
    env = os.environ.copy()
    env.pop("CLAUDE_GATES_GLOBAL_BYPASS", None)

    result = subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    # 不因 bypass 提前 exit；可能因缺 registry 报错，但返回码不是 0
    assert result.returncode != 0, f"Expected non-zero exit (normal flow), got {result.returncode}"

    # audit 目录可能不存在或无 BYPASS 行
    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    if audit_log.exists():
        log_content = audit_log.read_text()
        assert "BYPASS used:" not in log_content


# ====================== test_submit_py_bypass_logs_and_exits ======================


def test_submit_py_bypass_logs_and_exits(tmp_path):
    """given_CLAUDE_GATES_GLOBAL_BYPASS_set_when_submit_py_then_exit_0_with_two_audit_lines.

    操作：tmp_path 作 cwd，运行 submit.py --req=REQ-TEST 并设环境变量。
    期望：
      - exit 0（由 run.py 顶部 bypass 兜底）
      - audit/.queue/<日期>.log 至少 2 行：
        * entry=trigger:submit
        * entry=runner
    """
    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "fix-test-submit"

    result = subprocess.run(
        [sys.executable, str(_GATES_DIR / "triggers" / "submit.py"), "--req=REQ-TEST"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}.\nstderr: {result.stderr}"

    # 检查 audit/.queue 日志——应有至少 2 行
    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    assert audit_log.exists(), f"Expected audit log at {audit_log}"

    log_content = audit_log.read_text()
    lines = log_content.strip().split("\n")
    assert len(lines) >= 2, f"Expected at least 2 audit lines, got {len(lines)}: {log_content}"

    # 检查两个 entry 都存在
    assert any("entry=trigger:submit" in line for line in lines), "Missing entry=trigger:submit"
    assert any("entry=runner" in line for line in lines), "Missing entry=runner"


# ====================== test_submit_py_no_bypass_normal ======================


def test_submit_py_no_bypass_normal(tmp_path):
    """given_no_CLAUDE_GATES_GLOBAL_BYPASS_when_submit_py_then_normal_behavior."""
    env = os.environ.copy()
    env.pop("CLAUDE_GATES_GLOBAL_BYPASS", None)

    result = subprocess.run(
        [sys.executable, str(_GATES_DIR / "triggers" / "submit.py"), "--req=REQ-TEST"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    # 不因 bypass 提前 exit；可能因缺 registry/meta 报错
    assert result.returncode != 0

    # audit 无 BYPASS 行
    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    if audit_log.exists():
        log_content = audit_log.read_text()
        assert "BYPASS used:" not in log_content


# ====================== test_guard_sh_bypass_exits_zero ======================


def test_guard_sh_bypass_exits_zero(tmp_path):
    """given_CLAUDE_GATES_GLOBAL_BYPASS_set_when_guard_sh_then_exit_0_and_audit_log.

    操作：调用 .claude/hooks/pre-tool-use-guard.sh 并设环境变量。
    期望：exit 0；audit/.queue/<日期>.log 含 'BYPASS used: ... @ entry=pre-tool-use-guard' 行。

    注：guard.sh 由 hook 系统调用，通过 subprocess 模拟；输入为 jq JSON（tool_name 等）。
    """
    guard_sh = _REPO_ROOT / ".claude" / "hooks" / "pre-tool-use-guard.sh"
    if not guard_sh.exists():
        pytest.skip(f"{guard_sh} not found")

    env = os.environ.copy()
    # guard.sh 要求 reason >= 8 字符
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "emergency-fix"

    # 构造合法的 jq 输入（但 guard.sh 会在 bypass 检查就 exit，不会真正解析 jq）
    input_json = '{"tool_name": "Edit", "tool_input": {"file_path": "test.py"}}'

    result = subprocess.run(
        ["bash", str(guard_sh)],
        cwd=str(tmp_path),
        env=env,
        input=input_json,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}.\nstderr: {result.stderr}"

    # 检查 audit/.queue 日志
    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    assert audit_log.exists(), f"Expected audit log at {audit_log}"

    log_content = audit_log.read_text()
    assert "BYPASS used: emergency-fix @ entry=pre-tool-use-guard" in log_content


# ====================== test_guard_sh_bypass_too_short_reason ======================


def test_guard_sh_bypass_too_short_reason(tmp_path):
    """given_CLAUDE_GATES_GLOBAL_BYPASS_too_short_when_guard_sh_then_exit_2_blocked.

    guard.sh 对 reason 长度有要求 >= 8 字符；太短会被拒。
    """
    guard_sh = _REPO_ROOT / ".claude" / "hooks" / "pre-tool-use-guard.sh"
    if not guard_sh.exists():
        pytest.skip(f"{guard_sh} not found")

    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "short"  # < 8 chars

    input_json = '{"tool_name": "Edit", "tool_input": {"file_path": "test.py"}}'

    result = subprocess.run(
        ["bash", str(guard_sh)],
        cwd=str(tmp_path),
        env=env,
        input=input_json,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, f"Expected exit 2 (BLOCKED), got {result.returncode}"
    assert "太短" in result.stderr or "too short" in result.stderr or "BLOCKED" in result.stderr


# ====================== test_audit_line_format ======================


def test_audit_line_format(tmp_path):
    """given_bypass_triggered_when_audit_then_format_is_iso_ts_cwd_entry_reason.

    验证 audit 行格式严格符合规范：<ISO时间戳> <cwd> BYPASS used: <reason> @ entry=<entry>\n
    """
    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "format-test-12345"

    result = subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    assert audit_log.exists()

    log_content = audit_log.read_text().strip()
    lines = log_content.split("\n")

    # 最后一行应该是 run.py 的 entry=runner 行
    runner_line = [l for l in lines if "entry=runner" in l]
    assert len(runner_line) > 0, "No runner entry found"

    last_runner_line = runner_line[-1]
    # 格式：<ISO ts> <cwd> BYPASS used: <reason> @ entry=runner
    parts = last_runner_line.split(" ", 2)
    assert len(parts) >= 3, f"Audit line has fewer than 3 space-separated parts: {last_runner_line}"

    # 第一部分：ISO 时间戳（包含 T 和冒号）
    iso_ts = parts[0]
    assert "T" in iso_ts, f"ISO timestamp missing 'T': {iso_ts}"

    # 第二部分：cwd
    cwd_part = parts[1]
    assert str(tmp_path) in cwd_part, f"CWD not in audit line: {cwd_part}"

    # 第三部分及之后：BYPASS used: <reason> @ entry=runner
    reason_and_entry = " ".join(parts[2:])
    assert "BYPASS used:" in reason_and_entry
    assert "format-test-12345" in reason_and_entry
    assert "@ entry=runner" in reason_and_entry
