"""F-010 · _dispatch_loop_node until_bash + max_iterations 单元测试。

覆盖（AC-07 4 TC）：
- TC-F10-U1：until_bash='true' → 首轮 exit=0 → loop_completed + outcome=loop_done
- TC-F10-U2：until_bash 按 $iter 判定 → 跑 3 轮后退出（iter>=3 时 exit=0）
- TC-F10-U3：until_bash 不传 → 既有 max_iterations 计数路径（不破坏 F-011 历史行为）
- TC-F10-U4：until_bash subprocess timeout → error 写 "timeout: <cmd>"，按 max_iterations 兜底

测试运行：
    python3 -m pytest tests/lib/test_dispatch_loop_until.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from run_state import RunState  # noqa: E402
from workflow_dispatcher import _dispatch_loop_node  # noqa: E402


# ============================================================================
# 公共辅助
# ============================================================================

def _make_run_state(loop_counters: dict[str, int] | None = None) -> RunState:
    """构造含指定 loop_counters 的 RunState。"""
    rs = RunState(run_id="REQ-2026-010")
    if loop_counters:
        rs.loop_counters = dict(loop_counters)
    return rs


def _read_events(jsonl_path: Path) -> list[dict]:
    """从 jsonl 文件读取所有事件行。"""
    if not jsonl_path.exists():
        return []
    events = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


# ============================================================================
# TC-F10-U1：until_bash='true' → 首轮 exit=0 → loop_completed + outcome=loop_done
# ============================================================================

def test_until_bash_true_exits_on_first_iteration(tmp_path: Path) -> None:
    """TC-F10-U1：until_bash='true' → exit=0 → loop_completed + outcome=loop_done。

    until_bash 条件在首轮即满足，应直接写 loop_completed 并返回 loop_done，
    不写 loop_iteration_started / loop_iteration_completed。
    """
    jsonl = tmp_path / "run-state.jsonl"
    node = {"id": "check-loop", "loop": {"until_bash": "true", "max_iterations": 5}}
    run_state = _make_run_state()

    result = _dispatch_loop_node(node, {}, run_state, jsonl, root=tmp_path)

    assert result.outcome == "loop_done", (
        f"until_bash='true' exit=0 时应 loop_done，实际 {result.outcome!r}"
    )

    events = _read_events(jsonl)
    types = [e["type"] for e in events]

    assert "loop_completed" in types, (
        f"应写 loop_completed 事件，实际事件类型：{types}"
    )
    assert "loop_iteration_started" not in types, (
        "until_bash exit=0 时不应写 loop_iteration_started"
    )
    assert "loop_max_iterations_exceeded" not in types, (
        "until_bash exit=0 时不应写 loop_max_iterations_exceeded"
    )


# ============================================================================
# TC-F10-U2：until_bash 按 $iter 判定 → 跑 3 轮后退出
# ============================================================================

def test_until_bash_with_iter_variable_exits_after_n_iterations(tmp_path: Path) -> None:
    """TC-F10-U2：until_bash 'test "$iter" -ge 3' + max_iterations=5 → 跑 3 轮后退出。

    iter=0,1,2 时 exit≠0（条件不满足），写 loop_iteration_started/completed；
    iter=3 时 exit=0（条件满足），写 loop_completed + outcome=loop_done。
    """
    jsonl = tmp_path / "run-state.jsonl"
    node = {
        "id": "iter-loop",
        "loop": {"until_bash": 'test "$iter" -ge 3', "max_iterations": 5},
    }
    outcomes: list[str] = []

    run_state = _make_run_state()
    for _ in range(4):  # 最多 4 次（第 4 次 iter=3 应退出）
        result = _dispatch_loop_node(node, {}, run_state, jsonl, root=tmp_path)
        outcomes.append(result.outcome)
        if result.outcome == "loop_done":
            break
        # 模拟 workflow_continue 递增 loop_counters
        nid = "iter-loop"
        run_state.loop_counters[nid] = run_state.loop_counters.get(nid, 0) + 1

    assert outcomes == ["loop_continue", "loop_continue", "loop_continue", "loop_done"], (
        f"期望前 3 轮 loop_continue、第 4 轮 loop_done，实际序列：{outcomes}"
    )

    events = _read_events(jsonl)
    types = [e["type"] for e in events]

    # 3 轮迭代 + 1 轮 loop_completed
    iter_started = [e for e in events if e["type"] == "loop_iteration_started"]
    assert len(iter_started) == 3, (
        f"应有 3 条 loop_iteration_started，实际 {len(iter_started)}"
    )
    assert "loop_completed" in types, "第 4 轮应写 loop_completed"
    assert "loop_max_iterations_exceeded" not in types, (
        "自然退出（until_bash 满足）不应写 loop_max_iterations_exceeded"
    )


# ============================================================================
# TC-F10-U3：until_bash 不传 → 既有 max_iterations 计数路径（不破坏 F-011 历史行为）
# ============================================================================

def test_no_until_bash_uses_max_iterations_path(tmp_path: Path) -> None:
    """TC-F10-U3：until_bash 不传 → 走既有路径，max_iterations 触顶时 loop_max_iterations_exceeded。

    - 验证不传 until_bash 时不影响原有行为
    - 验证 loop_iteration_started / loop_iteration_completed 按旧规则写入
    - 验证触顶时 outcome=loop_done + 写 loop_max_iterations_exceeded
    """
    jsonl = tmp_path / "run-state.jsonl"
    node = {"id": "no-until-loop", "loop": {"max_iterations": 2}}

    # 第 1 轮（iteration=0）：应 loop_continue
    rs = _make_run_state()
    result1 = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)
    assert result1.outcome == "loop_continue", (
        f"第 1 轮（iteration=0，max=2）应 loop_continue，实际 {result1.outcome!r}"
    )

    # 第 2 轮（iteration=1）：应 loop_done + loop_max_iterations_exceeded
    rs.loop_counters["no-until-loop"] = 1
    result2 = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)
    assert result2.outcome == "loop_done", (
        f"第 2 轮（iteration=1，max=2）应 loop_done，实际 {result2.outcome!r}"
    )

    events = _read_events(jsonl)
    types = [e["type"] for e in events]
    assert "loop_max_iterations_exceeded" in types, (
        f"触顶时应写 loop_max_iterations_exceeded，实际事件类型：{types}"
    )
    assert "loop_completed" not in types, (
        "max_iterations 触顶不应写 loop_completed（只有 until_bash exit=0 时写）"
    )


# ============================================================================
# TC-F10-U4：until_bash subprocess timeout → error 写 "timeout: <cmd>"，按 max_iterations 兜底
# ============================================================================

def test_until_bash_timeout_writes_error_and_continues(tmp_path: Path) -> None:
    """TC-F10-U4：until_bash timeout → loop_iteration_completed.data.error 含 'timeout:'，
    继续走 max_iterations 计数路径（不视为 loop_done）。
    """
    jsonl = tmp_path / "run-state.jsonl"
    until_cmd = "sleep 999"
    node = {
        "id": "timeout-loop",
        "loop": {"until_bash": until_cmd, "max_iterations": 5},
    }
    run_state = _make_run_state()

    with patch("workflow_dispatcher.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=until_cmd, timeout=30.0)
        result = _dispatch_loop_node(node, {}, run_state, jsonl, root=tmp_path)

    # timeout 不视为 loop_done，继续计数路径（iteration=0，max=5，应 loop_continue）
    assert result.outcome == "loop_continue", (
        f"timeout 后 iteration=0 < max_iterations=5，应 loop_continue，实际 {result.outcome!r}"
    )

    events = _read_events(jsonl)
    completed_events = [e for e in events if e["type"] == "loop_iteration_completed"]
    assert len(completed_events) == 1, (
        f"应有 1 条 loop_iteration_completed，实际 {len(completed_events)}"
    )
    error_val = (completed_events[0].get("data") or {}).get("error", "")
    assert error_val.startswith("timeout:"), (
        f"error 字段应以 'timeout:' 开头，实际：{error_val!r}"
    )
    assert until_cmd in error_val, (
        f"error 字段应含超时命令 {until_cmd!r}，实际：{error_val!r}"
    )

    # 不应写 loop_completed（timeout 不是正常结束）
    assert "loop_completed" not in [e["type"] for e in events], (
        "timeout 路径不应写 loop_completed"
    )


# ============================================================================
# TC-F10-U5：until_bash OSError → error 写 "oserror: <msg>"，按 max_iterations 兜底
# ============================================================================

def test_until_bash_oserror_writes_error_and_continues(tmp_path: Path) -> None:
    """TC-F10-U5：until_bash 抛 OSError → loop_iteration_completed.data.error 含 'oserror:'，
    继续走 max_iterations 计数路径（不视为 loop_done，对齐 _dispatch_bash_node 双捕基线）。
    """
    jsonl = tmp_path / "run-state.jsonl"
    node = {
        "id": "oserror-loop",
        "loop": {"until_bash": "check_condition.sh", "max_iterations": 5},
    }
    run_state = _make_run_state()

    with patch("workflow_dispatcher.subprocess.run") as mock_run:
        mock_run.side_effect = OSError("bash not found")
        result = _dispatch_loop_node(node, {}, run_state, jsonl, root=tmp_path)

    # OSError 不视为 loop_done，继续计数路径（iteration=0，max=5，应 loop_continue）
    assert result.outcome == "loop_continue", (
        f"OSError 后 iteration=0 < max_iterations=5，应 loop_continue，实际 {result.outcome!r}"
    )

    events = _read_events(jsonl)
    completed_events = [e for e in events if e["type"] == "loop_iteration_completed"]
    assert len(completed_events) == 1, (
        f"应有 1 条 loop_iteration_completed，实际 {len(completed_events)}"
    )
    error_val = (completed_events[0].get("data") or {}).get("error", "")
    assert error_val.startswith("oserror:"), (
        f"error 字段应以 'oserror:' 开头，实际：{error_val!r}"
    )
    assert "bash not found" in error_val, (
        f"error 字段应含 OSError 消息，实际：{error_val!r}"
    )

    # 不应写 loop_completed（OSError 不是正常结束）
    assert "loop_completed" not in [e["type"] for e in events], (
        "OSError 路径不应写 loop_completed"
    )
