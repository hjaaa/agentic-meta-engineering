"""F-014 · workflow_outcome_router.py 修复回归测试。

覆盖范围：
  TC-F14-1  P1: outcome=awaiting_claude_action → state 置 awaiting_claude_action 且 break；
             杜绝旧路径"落到 unknown 兜底写 workflow_failed"。
  TC-F14-2  P2: depends_on_explicit=True 时 _handle_skip 走 _select_next_dispatch_target
             推进；杜绝旧路径"DAG yaml 节点无 next → 推进为 None 即停"。

来自 codex round-1 反馈（PR #72，commit 85c4d91）：
  P1: scripts/lib/workflow_outcome_router.py:296 缺 awaiting_claude_action 分支。
  P2: scripts/lib/workflow_outcome_router.py:118 _handle_skip 写死 _next_node。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, append_event, read_events  # noqa: E402
from workflow_continue import _main_loop  # noqa: E402
from workflow_outcome_router import _handle_skip  # noqa: E402


@pytest.fixture()
def jsonl_path(tmp_path: Path) -> Path:
    return tmp_path / "run-state.jsonl"


# ============================================================================
# TC-F14-1 · P1：awaiting_claude_action outcome 不应落入 unknown 兜底
# ============================================================================


def test_main_loop_awaiting_claude_action_breaks_with_state(jsonl_path, tmp_path):
    """dispatcher 返回 awaiting_claude_action → state=awaiting_claude_action 且 break。

    回归 codex round-1 P1：旧实现没有 awaiting_claude_action 分支，
    落到 unknown 兜底 → 错误写 workflow_failed + state=failed。
    新实现应让 main loop 直接退出，不写 workflow_failed。
    """
    from workflow_dispatcher import DispatchResult

    workflow = {
        "id": "test-wf",
        "name": "test-workflow",
        "version": "1.0",
        "category": "requirement",
        "nodes": [
            {
                "id": "agent-node",
                "agent": {"name": "test-agent", "prompt": "hi"},
            },
        ],
    }
    run_state = RunState(
        run_id="REQ-2099-001", current_node="agent-node", state="running"
    )

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        mock_dispatch.return_value = DispatchResult(outcome="awaiting_claude_action")
        _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

    assert run_state.state == "awaiting_claude_action"
    assert run_state.current_node == "agent-node"

    # 不应写 workflow_failed（旧实现兜底走 unknown 分支会写）
    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert failed_events == [], (
        f"awaiting_claude_action 不应触发 workflow_failed，实际写入: {failed_events}"
    )


# ============================================================================
# TC-F14-2 · P2：DAG 路径 skip 应走 scheduler 取下个 ready
# ============================================================================


def test_handle_skip_dag_advances_via_scheduler(jsonl_path):
    """depends_on_explicit=True 时 _handle_skip 应走 _select_next_dispatch_target。

    回归 codex round-1 P2：旧实现写死 _next_node(node, None)，
    DAG yaml 节点没有 next 字段时返 None → run_state.current_node = None → main loop 停。
    新实现应让 DAG 路径走 scheduler，找到 ready=node-b 推进。
    """
    workflow = {
        "id": "test-wf",
        "depends_on_explicit": True,
        "nodes": [
            {"id": "node-a", "bash": "echo 'a'", "on_failure": "skip"},
            {"id": "node-b", "bash": "echo 'b'", "depends_on": ["node-a"]},
        ],
    }
    node_map = {n["id"]: n for n in workflow["nodes"]}
    run_state = RunState(
        run_id="REQ-2099-002", current_node="node-a", state="running"
    )
    # 预写 node_started 让 scheduler 看到合法历史；skip 后 node-a 进 SUCCESS_TERMINAL（含 skipped）
    append_event(jsonl_path, {"type": "node_started", "node_id": "node-a"})

    result = _handle_skip(
        run_state,
        node_map["node-a"],
        jsonl_path,
        "explicit skip",
        workflow=workflow,
        node_map=node_map,
    )

    assert result is True  # main loop 应继续
    # 关键回归断言：DAG 路径下应推进到 node-b（旧实现会推进为 None）
    assert run_state.current_node == "node-b", (
        f"DAG skip 路径未推进到 node-b，实际 current_node={run_state.current_node!r}"
    )


def test_handle_skip_single_chain_preserves_next_semantics(jsonl_path):
    """depends_on_explicit=False 时 _handle_skip 保持原 _next_node 语义不退化。

    保护旧行为：单链退化路径必须沿用 node.next 字段；F-014 修复不能引入回归。
    """
    workflow = {"id": "test-wf"}  # 无 depends_on_explicit
    node = {"id": "node-a", "bash": "echo 'a'", "next": "node-b", "on_failure": "skip"}
    run_state = RunState(
        run_id="REQ-2099-003", current_node="node-a", state="running"
    )

    result = _handle_skip(
        run_state, node, jsonl_path, "single chain skip",
        workflow=workflow, node_map={},
    )

    assert result is True
    assert run_state.current_node == "node-b"
