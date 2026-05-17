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
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

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

    subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    # 不因 bypass 提前 exit——契约靠"audit 无 BYPASS 行"来证明（returncode 受
    # 项目 registry 实际状态影响，不是 bypass 路径的可靠代理；REQ-2026-006/F-005
    # 之后 sourcing 跳过 completed 需求，CI 模拟可能返回 0）
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
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

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
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

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
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

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
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

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


# ====================== F-004 carryover-1 + carryover-2 新增用例 ======================


def test_run_py_bypass_reason_with_newline_escaped(tmp_path):
    """F-004 carryover-2：reason 含换行符时 audit log 仍为单行（\n 已转义为空格）。

    given_reason_with_newline_when_run_py_bypass_then_audit_single_line.
    """
    env = os.environ.copy()
    # 换行前后分别是合法字符；转义后仍 >= 8 字符
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "fix\nFAKE_ENTRY"
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}.\nstderr: {result.stderr}"

    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    assert audit_log.exists()

    log_content = audit_log.read_text()
    # 每行都不应包含 \n（audit log 行格式单行）
    for line in log_content.splitlines():
        assert "FAKE_ENTRY" not in line or "entry=runner" in line, (
            "换行注入不应拆出额外 entry 行"
        )
    # 确认 \n 被转义为空格，原始换行字符不出现在 log 行中
    runner_lines = [l for l in log_content.splitlines() if "entry=runner" in l]
    assert len(runner_lines) == 1, f"应有且仅有 1 行 runner 记录，得 {runner_lines}"
    assert "\n" not in runner_lines[0]


def test_run_py_bypass_whitespace_only_reason_rejected(tmp_path):
    """F-004 carryover-2：reason 为纯空白时 bypass 不触发，继续走正常 gate 流程。

    given_whitespace_only_reason_when_run_py_then_bypass_not_triggered.
    """
    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "   "  # 纯空白，strip 后 < 8
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

    subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    # bypass 不触发 → audit log 不应含 BYPASS 行（returncode 不可靠，见上）
    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    if audit_log.exists():
        assert "BYPASS used:" not in audit_log.read_text()


def test_run_py_bypass_short_reason_rejected(tmp_path):
    """F-004 carryover-2：reason 长度 < 8 字符时 bypass 不触发，继续走正常 gate 流程。

    given_short_reason_when_run_py_then_bypass_not_triggered.
    """
    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "abc"  # 3 字符 < 8
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

    subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    if audit_log.exists():
        assert "BYPASS used:" not in audit_log.read_text()


def test_run_py_bypass_oversized_reason_safe(tmp_path):
    """F-004 carryover-2：超长 reason（5000 字符）时 audit log 写入正常不截断不 crash。

    given_oversized_reason_when_run_py_then_audit_written_without_crash.
    """
    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "x" * 5000  # 超长，但合法（>= 8 字符）
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(tmp_path)

    result = subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"超长 reason 仍合法，应 exit 0，got {result.returncode}"

    today = dt.now().strftime("%Y-%m-%d")
    audit_log = tmp_path / "audit" / ".queue" / f"{today}.log"
    assert audit_log.exists()

    log_content = audit_log.read_text()
    # 含 BYPASS 行且 reason 完整（未截断）
    assert "BYPASS used:" in log_content
    assert "x" * 100 in log_content  # 5000 个 x 的前 100 个仍在


# ====================== test_audit_root_is_repo_anchored_not_cwd ======================


def test_run_py_audit_anchors_to_audit_root_not_cwd(tmp_path):
    """given_cwd_neq_audit_root_when_run_py_then_audit_lands_in_audit_root.

    Codex P1 回归：早期 producer 用 cwd-relative `audit/.queue/...`，consumer
    audit_flush.py 锚到 repo 根，cwd≠repo 时记录被丢。修复后所有 producer 必须
    锚到同一 root（默认 repo 根，env=CLAUDE_GATES_AUDIT_ROOT 测试时覆盖）。
    """
    cwd_dir = tmp_path / "elsewhere"
    cwd_dir.mkdir()
    audit_root = tmp_path / "fake-repo"
    audit_root.mkdir()

    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "anchor-regression"
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(audit_root)

    result = subprocess.run(
        [sys.executable, str(_GATES_DIR / "run.py"), "--trigger=ci"],
        cwd=str(cwd_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    today = dt.now().strftime("%Y-%m-%d")
    # 必须落在 audit_root（env override），不是 cwd
    expected = audit_root / "audit" / ".queue" / f"{today}.log"
    cwd_relative = cwd_dir / "audit" / ".queue" / f"{today}.log"
    assert expected.exists(), f"Expected audit at {expected}"
    assert not cwd_relative.exists(), (
        f"Regression: audit fell back to cwd-relative path {cwd_relative}"
    )


def test_guard_sh_audit_anchors_to_audit_root_not_cwd(tmp_path):
    """given_cwd_neq_audit_root_when_guard_sh_bypass_then_audit_lands_in_audit_root."""
    guard_sh = _REPO_ROOT / ".claude" / "hooks" / "pre-tool-use-guard.sh"
    if not guard_sh.exists():
        pytest.skip(f"{guard_sh} not found")

    cwd_dir = tmp_path / "elsewhere"
    cwd_dir.mkdir()
    audit_root = tmp_path / "fake-repo"
    audit_root.mkdir()

    env = os.environ.copy()
    env["CLAUDE_GATES_GLOBAL_BYPASS"] = "anchor-regression-guard"
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(audit_root)

    result = subprocess.run(
        ["bash", str(guard_sh)],
        cwd=str(cwd_dir),
        env=env,
        input='{"tool_name":"Edit","tool_input":{"file_path":"a.txt"}}',
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    today = dt.now().strftime("%Y-%m-%d")
    expected = audit_root / "audit" / ".queue" / f"{today}.log"
    cwd_relative = cwd_dir / "audit" / ".queue" / f"{today}.log"
    assert expected.exists(), f"Expected audit at {expected}"
    assert not cwd_relative.exists(), (
        f"Regression: audit fell back to cwd-relative path {cwd_relative}"
    )


def test_audit_flush_hook_runs_from_arbitrary_cwd(tmp_path):
    """given_cwd_neq_repo_when_audit_flush_hook_invoked_then_flushes_queue_correctly.

    Codex P1 round-2 回归：audit-flush.sh 早期写 'python3 scripts/lib/audit_flush.py'
    （cwd-relative），SessionEnd 在 cwd≠repo 时 file-not-found 被 stderr 重定向 +
    || true 静默吞掉，audit/.queue/*.log 永远不被 flush。修复后必须用脚本相对
    repo 根的绝对路径调 audit_flush.py。
    """
    flush_hook = _REPO_ROOT / ".claude" / "hooks" / "audit-flush.sh"
    if not flush_hook.exists():
        pytest.skip(f"{flush_hook} not found")

    audit_root = tmp_path / "fake-repo"
    queue_dir = audit_root / "audit" / ".queue"
    queue_dir.mkdir(parents=True)

    today = dt.now().strftime("%Y-%m-%d")
    log_file = queue_dir / f"{today}.log"
    # 投一条合法 record（行格式：<ts> <cwd> <event> @ entry=<name>）
    log_file.write_text(
        f"{dt.now().isoformat()} /tmp test-event @ entry=runner\n",
        encoding="utf-8",
    )

    cwd_dir = tmp_path / "elsewhere"
    cwd_dir.mkdir()

    env = os.environ.copy()
    env["CLAUDE_GATES_AUDIT_ROOT"] = str(audit_root)

    result = subprocess.run(
        ["bash", str(flush_hook)],
        cwd=str(cwd_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    # hook 是 best-effort，永远不该非零退出
    assert result.returncode == 0, f"flush hook returned {result.returncode}: {result.stderr}"

    # 期望：record 被聚合到 audit/<YYYY-MM>/<entry>-<YYYY-MM-DD>.json，原 .log 被归档
    yyyy_mm = dt.now().strftime("%Y-%m")
    bucket = audit_root / "audit" / yyyy_mm / f"runner-{today}.json"
    assert bucket.exists(), (
        f"Regression: flush hook 没生成桶 {bucket}（cwd-relative path 可能没找到 audit_flush.py）"
    )
    archived = audit_root / "audit" / ".queue.done" / today
    assert archived.exists(), f"Expected .log 被归档到 {archived}"
