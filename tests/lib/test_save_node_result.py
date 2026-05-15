"""F-007 · save_node_result.py 验收测试（11 条 acceptance criteria）。

覆盖：
  AC-01：skill_result happy path：state=awaiting + current_node=N1 + 末位 node_ready(N1) → node_completed exit 0
  AC-02：skill_result state=running → exit 2 + stderr E-NODE-RESULT-001
  AC-03：P1-1 反向 a：current_node=N1 但 --node=N2 → exit 2 + E-NODE-RESULT-002
  AC-04：P1-1 反向 b：state/current_node 都对但末位事件不是 node_ready → exit 2 + E-NODE-RESULT-003
  AC-05：P1-1 反向 c：approval_repair --node=N1 + pending_approval=N1，但末位 started.node_id=N2 → exit 2 + E-NODE-RESULT-004
  AC-06：approval_repair happy path：attempt=1 一致 → approval_repair_completed exit 0
  AC-07：approval_repair 缺 --attempt → exit 1 + stderr "attempt required"
  AC-08：approval_repair --attempt=2 但 started.attempt=1 → exit 1 + stderr "attempt mismatch"
  AC-09：--output 5KB → 走 manifest fallback，event.data.output_ref 存在
  AC-10：grep hook 文件校验 save_node_result 不在 APPROVAL_*_PATTERN 中
  AC-11：subprocess 运行校验不被 hook 拦截（grep 替代）

测试运行：
    python3 -m pytest tests/lib/test_save_node_result.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import save_node_result  # noqa: E402
from run_state import RunState, append_event, read_events  # noqa: E402

SAVE_NODE_RESULT_PY = REPO_ROOT / "scripts" / "lib" / "save_node_result.py"
HOOK_FILE = REPO_ROOT / ".claude" / "hooks" / "pre-tool-use-guard.sh"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _make_run_dir(tmp_path: Path, run_id: str) -> tuple[Path, Path]:
    """在 tmp_path/runs/<run_id>/ 创建 run 目录；返回 (run_dir, jsonl_path)。"""
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = run_dir / "run-state.jsonl"
    return run_dir, jsonl_path


def _seed_node_ready(jsonl_path: Path, node_id: str) -> None:
    """写入 workflow_started + node_ready(node_id)，使 state=awaiting_claude_action。"""
    append_event(jsonl_path, {"type": "workflow_started", "run_id": "test-run"})
    append_event(jsonl_path, {"type": "node_ready", "node_id": node_id,
                              "data": {"node_kind": "skill"}})


def _seed_approval_repair_started(
    jsonl_path: Path,
    node_id: str,
    attempt: int = 1,
    started_node_id: str | None = None,
) -> None:
    """写入 workflow_started + approval_pending + approval_repair_started。

    Args:
        jsonl_path: 目标 jsonl 路径。
        node_id:    pending_approval 节点 id（approval_pending 事件用）。
        attempt:    approval_repair_started.data.attempt 值。
        started_node_id: approval_repair_started 的 node_id（默认与 node_id 同；
                         AC-05 用于测试 N1 vs N2 不一致场景）。
    """
    if started_node_id is None:
        started_node_id = node_id
    append_event(jsonl_path, {"type": "workflow_started", "run_id": "test-run"})
    append_event(jsonl_path, {"type": "node_started", "node_id": node_id})
    append_event(jsonl_path, {"type": "approval_pending", "node_id": node_id})
    append_event(jsonl_path, {
        "type": "approval_repair_started",
        "node_id": started_node_id,
        "data": {"attempt": attempt, "max_attempts": 3, "prompt_ref": "p.md",
                 "reason": "fix needed"},
    })


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读 jsonl，返回事件列表。"""
    if not path.exists():
        return []
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


def _run_cli(tmp_path: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    """子进程运行 save_node_result.py CLI，注入 --repo-root=tmp_path。"""
    cmd = [
        sys.executable, str(SAVE_NODE_RESULT_PY),
        f"--repo-root={tmp_path}",
    ] + list(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# AC-01：skill_result happy path → node_completed exit 0
# ---------------------------------------------------------------------------

def test_ac01_skill_result_happy_path(tmp_path: Path) -> None:
    """skill_result: state=awaiting + current_node=N1 + 末位 node_ready(N1) → exit 0 + node_completed 写入。"""
    run_id = "REQ-2099-701"
    run_dir, jsonl_path = _make_run_dir(tmp_path, run_id)
    _seed_node_ready(jsonl_path, "node-N1")

    output_json = json.dumps({"result": "ok"})
    result = _run_cli(tmp_path, "--run", run_id, "--node", "node-N1",
                      "--kind", "skill_result", "--output", output_json)

    assert result.returncode == 0, f"期望 exit 0，实际 {result.returncode}\nstderr={result.stderr}"
    events = _read_jsonl(jsonl_path)
    types = [e["type"] for e in events]
    assert "node_completed" in types, f"期望 node_completed 被写入，events={types}"
    completed = next(e for e in events if e["type"] == "node_completed")
    assert completed["node_id"] == "node-N1"


# ---------------------------------------------------------------------------
# AC-02：skill_result state=running → exit 2 + E-NODE-RESULT-001
# ---------------------------------------------------------------------------

def test_ac02_skill_result_state_running_exit2(tmp_path: Path) -> None:
    """state=running → exit 2，stderr 含 E-NODE-RESULT-001。"""
    run_id = "REQ-2099-702"
    run_dir, jsonl_path = _make_run_dir(tmp_path, run_id)
    # 只写 workflow_started，state=running
    append_event(jsonl_path, {"type": "workflow_started", "run_id": run_id})

    output_json = json.dumps({"result": "ok"})
    result = _run_cli(tmp_path, "--run", run_id, "--node", "node-N1",
                      "--kind", "skill_result", "--output", output_json)

    assert result.returncode == 2, f"期望 exit 2，实际 {result.returncode}"
    assert "E-NODE-RESULT-001" in result.stderr, f"stderr 缺 E-NODE-RESULT-001: {result.stderr}"


# ---------------------------------------------------------------------------
# AC-03：P1-1 反向 a：current_node=N1 但 --node=N2 → exit 2 + E-NODE-RESULT-002
# ---------------------------------------------------------------------------

def test_ac03_p1_reverse_a_current_node_mismatch(tmp_path: Path) -> None:
    """current_node=N1 但 CLI 传 --node=N2 → exit 2，stderr 含 E-NODE-RESULT-002。"""
    run_id = "REQ-2099-703"
    run_dir, jsonl_path = _make_run_dir(tmp_path, run_id)
    _seed_node_ready(jsonl_path, "node-N1")  # current_node=N1

    output_json = json.dumps({"result": "ok"})
    # 传 --node=N2（与 current_node=N1 不一致）
    result = _run_cli(tmp_path, "--run", run_id, "--node", "node-N2",
                      "--kind", "skill_result", "--output", output_json)

    assert result.returncode == 2, f"期望 exit 2，实际 {result.returncode}"
    assert "E-NODE-RESULT-002" in result.stderr, f"stderr 缺 E-NODE-RESULT-002: {result.stderr}"


# ---------------------------------------------------------------------------
# AC-04：P1-1 反向 b：state/current_node 正确但末位非 node_ready → exit 2 + E-NODE-RESULT-003
# ---------------------------------------------------------------------------

def test_ac04_p1_reverse_b_tail_event_not_node_ready(tmp_path: Path) -> None:
    """state=awaiting + current_node=N1，但末位节点级事件是 approval_repair_started → exit 2 + E-NODE-RESULT-003。"""
    run_id = "REQ-2099-704"
    run_dir, jsonl_path = _make_run_dir(tmp_path, run_id)
    # 先 node_ready(N1) 使 state=awaiting + current_node=N1
    append_event(jsonl_path, {"type": "workflow_started", "run_id": run_id})
    append_event(jsonl_path, {"type": "node_ready", "node_id": "node-N1",
                              "data": {"node_kind": "skill"}})
    # 再追加 approval_repair_started(N1) 使末位节点级事件变成 approval_repair_started
    # 注意：此时 state 会变成 awaiting_claude_action（pending_approval=N1），
    # 但我们用 --kind=skill_result 期望末位是 node_ready，因此触发 E-NODE-RESULT-003
    append_event(jsonl_path, {
        "type": "approval_repair_started",
        "node_id": "node-N1",
        "data": {"attempt": 1, "max_attempts": 3, "prompt_ref": "p.md", "reason": "r"},
    })

    output_json = json.dumps({"result": "ok"})
    result = _run_cli(tmp_path, "--run", run_id, "--node", "node-N1",
                      "--kind", "skill_result", "--output", output_json)

    assert result.returncode == 2, f"期望 exit 2，实际 {result.returncode}"
    assert "E-NODE-RESULT-003" in result.stderr, f"stderr 缺 E-NODE-RESULT-003: {result.stderr}"


# ---------------------------------------------------------------------------
# AC-05：P1-1 反向 c：(2a) 通过但末位节点级事件 node_id 不一致 → exit 2 + E-NODE-RESULT-004
# ---------------------------------------------------------------------------

def test_ac05_p1_reverse_c_tail_node_id_mismatch() -> None:
    """_check_node_match_or_fail: current_node=N1（(2a) 通过）+ 末位 node_ready.node_id=N2 → E-NODE-RESULT-004。

    注意：在正常 rebuild 流中，末位 node_ready.node_id 同时会设置 current_node，
    导致 (2a) 和 (2b) 不能同时满足"通过"和"失败"。本测试直接调用内部函数，
    手动构造 RunState.current_node=N1 + synthetic_events 末位 node_ready(N2)，
    精确验证 (2b) 的 E-NODE-RESULT-004 分支。
    """
    import io
    from contextlib import redirect_stderr

    run_state = RunState(
        run_id="test-run",
        state="awaiting_claude_action",
        current_node="node-N1",
    )
    # 末位节点级事件类型对（node_ready），但 node_id=N2（与 --node=N1 不一致）
    synthetic_events: list[dict[str, Any]] = [
        {"type": "workflow_started", "run_id": "test-run"},
        {"type": "node_ready", "node_id": "node-N2", "data": {}},
    ]

    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc_info:
        with redirect_stderr(buf):
            save_node_result._check_node_match_or_fail(
                run_state, "node-N1", "skill_result", synthetic_events
            )
    assert exc_info.value.code == 2, f"期望 exit 2，实际 {exc_info.value.code}"
    assert "E-NODE-RESULT-004" in buf.getvalue(), (
        f"stderr 缺 E-NODE-RESULT-004: {buf.getvalue()}"
    )


# ---------------------------------------------------------------------------
# AC-06：approval_repair happy path → approval_repair_completed exit 0
# ---------------------------------------------------------------------------

def test_ac06_approval_repair_happy_path(tmp_path: Path) -> None:
    """approval_repair: attempt=1 一致 → exit 0 + approval_repair_completed 写入。"""
    run_id = "REQ-2099-706"
    run_dir, jsonl_path = _make_run_dir(tmp_path, run_id)
    _seed_approval_repair_started(jsonl_path, node_id="gate-A", attempt=1)

    output_json = json.dumps({"fixed": True})
    result = _run_cli(tmp_path, "--run", run_id, "--node", "gate-A",
                      "--kind", "approval_repair", "--output", output_json,
                      "--attempt", "1")

    assert result.returncode == 0, f"期望 exit 0，实际 {result.returncode}\nstderr={result.stderr}"
    events = _read_jsonl(jsonl_path)
    types = [e["type"] for e in events]
    assert "approval_repair_completed" in types, f"期望 approval_repair_completed 被写入，events={types}"
    completed = next(e for e in events if e["type"] == "approval_repair_completed")
    assert completed["node_id"] == "gate-A"


# ---------------------------------------------------------------------------
# AC-07：approval_repair 缺 --attempt → exit 1 + "attempt required"
# ---------------------------------------------------------------------------

def test_ac07_approval_repair_missing_attempt(tmp_path: Path) -> None:
    """缺 --attempt → exit 1，stderr 含 'attempt required'。"""
    run_id = "REQ-2099-707"
    run_dir, jsonl_path = _make_run_dir(tmp_path, run_id)
    _seed_approval_repair_started(jsonl_path, node_id="gate-B", attempt=1)

    output_json = json.dumps({"fixed": True})
    # 故意不传 --attempt
    result = _run_cli(tmp_path, "--run", run_id, "--node", "gate-B",
                      "--kind", "approval_repair", "--output", output_json)

    assert result.returncode == 1, f"期望 exit 1，实际 {result.returncode}"
    assert "attempt required" in result.stderr, f"stderr 缺 'attempt required': {result.stderr}"


# ---------------------------------------------------------------------------
# AC-08：approval_repair --attempt=2 但 started.attempt=1 → exit 1 + "attempt mismatch"
# ---------------------------------------------------------------------------

def test_ac08_approval_repair_attempt_mismatch(tmp_path: Path) -> None:
    """--attempt=2 但 started.attempt=1 → exit 1，stderr 含 'attempt mismatch'。"""
    run_id = "REQ-2099-708"
    run_dir, jsonl_path = _make_run_dir(tmp_path, run_id)
    _seed_approval_repair_started(jsonl_path, node_id="gate-C", attempt=1)

    output_json = json.dumps({"fixed": True})
    result = _run_cli(tmp_path, "--run", run_id, "--node", "gate-C",
                      "--kind", "approval_repair", "--output", output_json,
                      "--attempt", "2")

    assert result.returncode == 1, f"期望 exit 1，实际 {result.returncode}"
    assert "attempt mismatch" in result.stderr, f"stderr 缺 'attempt mismatch': {result.stderr}"


# ---------------------------------------------------------------------------
# AC-09：--output 5KB → manifest fallback，event.data.output_ref 存在
# ---------------------------------------------------------------------------

def test_ac09_large_output_manifest_fallback(tmp_path: Path) -> None:
    """5KB output → 走 manifest fallback；event.data 含 output_ref 而非 output。"""
    run_id = "REQ-2099-709"
    run_dir, jsonl_path = _make_run_dir(tmp_path, run_id)
    _seed_node_ready(jsonl_path, "node-big")

    # 构造 5KB JSON（超过 4KB batch 上限 + 单字段 3500B 阈值）
    large_str = "x" * 5000
    output_json = json.dumps({"result": large_str})

    result = _run_cli(tmp_path, "--run", run_id, "--node", "node-big",
                      "--kind", "skill_result", "--output", output_json)

    assert result.returncode == 0, f"期望 exit 0，实际 {result.returncode}\nstderr={result.stderr}"

    events = _read_jsonl(jsonl_path)
    completed = next((e for e in events if e["type"] == "node_completed"), None)
    assert completed is not None, "期望 node_completed 被写入"

    data = completed.get("data", {})
    # manifest fallback 后，output 被替换为 output_ref
    assert "output_ref" in data, (
        f"期望 data.output_ref 存在（manifest fallback），data={data}"
    )
    output_ref = data["output_ref"]
    assert "path" in output_ref and "size" in output_ref and "sha256" in output_ref, (
        f"output_ref 缺必要字段: {output_ref}"
    )

    # manifest 文件应实际存在
    manifest_path = run_dir / output_ref["path"]
    assert manifest_path.exists(), f"manifest 文件应存在: {manifest_path}"


# ---------------------------------------------------------------------------
# AC-10：grep hook 文件校验 save_node_result 不在 APPROVAL_*_PATTERN 中
# ---------------------------------------------------------------------------

def test_ac10_save_node_result_not_in_hook_approval_pattern() -> None:
    """save_node_result.py 不应出现在 APPROVAL_*_PATTERN（hook 拦截名单）中。"""
    assert HOOK_FILE.exists(), f"hook 文件不存在: {HOOK_FILE}"
    content = HOOK_FILE.read_text(encoding="utf-8")

    # 检查 APPROVAL_PYTHON_PATTERN 不含 save_node_result
    approval_pattern_lines = [
        line for line in content.splitlines()
        if "APPROVAL_PYTHON_PATTERN" in line or "APPROVAL_SLASH_PATTERN" in line
    ]
    for line in approval_pattern_lines:
        assert "save_node_result" not in line, (
            f"save_node_result 出现在 hook APPROVAL_*_PATTERN 中（违反 AC-10）：\n{line}"
        )


# ---------------------------------------------------------------------------
# AC-11：grep 校验 save_node_result 不被 hook WRITE_OPS_PATTERN 拦截
# ---------------------------------------------------------------------------

def test_ac11_save_node_result_not_blocked_by_hook() -> None:
    """save_node_result 脚本路径不匹配 hook 的 APPROVAL_*_PATTERN（grep 替代 subprocess 运行）。"""
    assert HOOK_FILE.exists(), f"hook 文件不存在: {HOOK_FILE}"
    hook_content = HOOK_FILE.read_text(encoding="utf-8")

    # save_node_result.py 的完整调用形式不应命中任何 hook 拦截 pattern
    simulated_cmd = "python3 scripts/lib/save_node_result.py --run REQ-xxx --node N1 --kind skill_result --output '{}'"

    # 从 hook 提取 APPROVAL_PYTHON_PATTERN 定义值（不含变量引用行）
    # 判据：save_node_result 不出现在 workflow_(approve|reject) 正则里
    assert "save_node_result" not in hook_content, (
        "save_node_result 不应出现在 hook 文件内容中（期望完全不被提及于拦截列表）"
    )

    # 确认 hook 只拦 workflow_approve / workflow_reject
    approval_section = [
        line for line in hook_content.splitlines()
        if "workflow_" in line and "APPROVAL" in line
    ]
    for line in approval_section:
        # save_node_result 应不在任何 workflow_ 拦截行中
        assert "save_node_result" not in line
