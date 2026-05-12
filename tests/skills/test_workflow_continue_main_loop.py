"""F-007/F-008 · workflow_continue.py main loop 单测（happy path + 辅助函数 + 端到端）。

覆盖范围（_main_loop 主循环 + 辅助函数 + dispatcher 集成 e2e）：
  TC build_node_map  _build_node_map 辅助函数单测（映射构造 + 跳过无 id 节点）
  TC next_node       _next_node 辅助函数单测（hint 优先 / 无 hint 用 next / 无 next 返 None）
  TC-F7-3  failed outcome：节点派发返回 failed，main loop 调 _handle_failure
  TC-F7-4  node_outputs 结构正确：completed 时含 output / state / data 三键
  TC-F7-5  unknown node 容错：写 workflow_failed + state=failed
  TC-F8-5  main loop 端到端：mock dispatch_node，standard-8phase 前 3 节点 completed × 3

outcome 路由（approval_pending / loop_continue / sub_workflow_pending）单测移至：
  test_workflow_continue_outcomes.py（F-NEW-7 拆分，按 outcome 维度独立归档）

_handle_failure 的 retry/skip/abort 单测移至：
  test_workflow_continue_failure_handler.py

外部依赖（jsonl IO）使用 tmp_path；mock workflow doc。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, append_event, read_events  # noqa: E402
from workflow_continue import _main_loop, _build_node_map, _next_node  # noqa: E402


# ============================================================================
# Fixture
# ============================================================================


@pytest.fixture()
def jsonl_path(tmp_path: Path) -> Path:
    """返回一个临时 jsonl 文件路径（父目录已存在）。"""
    return tmp_path / "run-state.jsonl"


@pytest.fixture()
def mock_workflow_2nodes() -> dict:
    """2 节点 workflow：node-a (bash) → node-b (approval)。"""
    return {
        "id": "test-wf",
        "name": "test-workflow",
        "version": "1.0",
        "category": "requirement",
        "nodes": [
            {
                "id": "node-a",
                "bash": "echo 'hello'",
                "next": "node-b",
            },
            {
                "id": "node-b",
                "approval": {"prompt": "Approve?"},
            },
        ],
    }


# ============================================================================
# Helper 函数单测
# ============================================================================


def test_build_node_map_constructs_mapping():
    """_build_node_map 正确构造 id → node dict 映射。"""
    workflow = {
        "nodes": [
            {"id": "a", "bash": "cmd1"},
            {"id": "b", "bash": "cmd2"},
        ]
    }
    node_map = _build_node_map(workflow)
    assert "a" in node_map
    assert "b" in node_map
    assert node_map["a"]["bash"] == "cmd1"


def test_build_node_map_skips_nodes_without_id():
    """_build_node_map 跳过不含 id 字段的节点。"""
    workflow = {
        "nodes": [
            {"id": "a", "bash": "cmd1"},
            {"bash": "cmd2"},  # 无 id
        ]
    }
    node_map = _build_node_map(workflow)
    assert len(node_map) == 1
    assert "a" in node_map


def test_next_node_prioritizes_hint():
    """_next_node：hint 非 None 时优先返回 hint。"""
    node = {"id": "a", "next": "b"}
    result = _next_node(node, "override")
    assert result == "override"


def test_next_node_falls_back_to_next_field():
    """_next_node：hint 为 None 时返回 node.next。"""
    node = {"id": "a", "next": "b"}
    result = _next_node(node, None)
    assert result == "b"


def test_next_node_returns_none_when_no_next():
    """_next_node：无 next 字段且无 hint 时返回 None。"""
    node = {"id": "a"}
    result = _next_node(node, None)
    assert result is None


# ============================================================================
# TC-F7-3 · failed outcome
# ============================================================================


def test_main_loop_failed_outcome_with_abort_sets_state_failed_and_breaks(
    jsonl_path,
    tmp_path,
):
    """节点设 on_failure=abort 时，派发返回 failed → main loop 写 workflow_failed + state=failed + break。

    场景：node-a 带 on_failure=abort，dispatch 返回 failed
    期望：state 变为 failed，loop break，current_node 保持 node-a
    """
    from workflow_dispatcher import DispatchResult

    workflow = {
        "id": "test-wf",
        "name": "test-workflow",
        "version": "1.0",
        "category": "requirement",
        "nodes": [
            {
                "id": "node-a",
                "bash": "echo 'hello'",
                "next": "node-b",
                "on_failure": "abort",  # 显式 abort，保证 state=failed
            },
            {
                "id": "node-b",
                "approval": {"prompt": "Approve?"},
            },
        ],
    }
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        mock_dispatch.return_value = DispatchResult(
            outcome="failed",
            error="node-a execution failed",
        )

        _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

        # 期望：state 变为 failed，loop break，current_node 保持不变
        assert run_state.state == "failed"
        assert run_state.current_node == "node-a"


# ============================================================================
# TC-F7-4 · node_outputs 结构正确
# ============================================================================


def test_main_loop_node_outputs_structure(
    mock_workflow_2nodes,
    jsonl_path,
    tmp_path,
):
    """completed outcome 时，node_outputs 条目含 output / state / data 三键。"""
    from workflow_dispatcher import DispatchResult

    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        mock_dispatch.return_value = DispatchResult(
            outcome="completed",
            output="test-output",
        )

        _main_loop(run_state, mock_workflow_2nodes, tmp_path, tmp_path, jsonl_path)

        assert "node-a" in run_state.node_outputs
        entry = run_state.node_outputs["node-a"]
        assert entry["output"] == "test-output"
        assert entry["state"] == "completed"
        assert entry["data"]["output"] == "test-output"


# ============================================================================
# TC-F7-5 · unknown node 容错
# ============================================================================


def test_main_loop_unknown_node_writes_workflow_failed_event(
    jsonl_path,
    tmp_path,
):
    """current_node 指向不存在的节点，写 workflow_failed 事件并设 state=failed。"""
    workflow = {"nodes": []}  # 空节点列表
    run_state = RunState(run_id="REQ-2026-010", current_node="nonexistent", state="running")

    _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

    # 期望：state=failed，workflow_failed 事件写入
    assert run_state.state == "failed"
    events, _ = read_events(jsonl_path)
    workflow_failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert len(workflow_failed_events) == 1
    assert "未知节点" in workflow_failed_events[0]["data"]["error"]


# ============================================================================
# TC-F8-5 · main loop 端到端：standard-8phase 前 3 节点 completed × 3
# ============================================================================


def test_main_loop_completes_three_nodes_with_mocked_dispatch(tmp_path, jsonl_path):
    """端到端：mock dispatch_node，按 standard-8phase 前 3 节点顺序返 completed × 3。

    场景：3 节点 workflow 全部返回 completed
      bootstrap-validate → req-input-normalize → req-draft
    期望：main loop 正常结束（state=running，current_node=None）
          node_outputs 含全部 3 节点
          dispatch_node 被调用 3 次
    """
    from workflow_dispatcher import DispatchResult

    workflow = {
        "id": "standard-8phase",
        "name": "standard-8phase",
        "version": "1.0",
        "category": "requirement",
        "nodes": [
            {
                "id": "bootstrap-validate",
                "bash": "echo 'bootstrap'",
                "next": "req-input-normalize",
            },
            {
                "id": "req-input-normalize",
                "bash": "echo 'normalize'",
                "next": "req-draft",
            },
            {
                "id": "req-draft",
                "bash": "echo 'draft'",
                # 末尾节点，无 next
            },
        ],
    }

    run_state = RunState(
        run_id="REQ-2026-010",
        current_node="bootstrap-validate",
        state="running",
    )

    node_outputs_map = {
        "bootstrap-validate": "bootstrap output",
        "req-input-normalize": "normalize output",
        "req-draft": "draft output",
    }

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:

        def dispatch_side_effect(node, *args, **kwargs):
            node_id = node.get("id")
            output = node_outputs_map.get(node_id, "")
            return DispatchResult(outcome="completed", output=output)

        mock_dispatch.side_effect = dispatch_side_effect

        _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

    # main loop 应正常结束：state=running（无 workflow_completed 事件），current_node=None
    assert run_state.state == "running"
    assert run_state.current_node is None

    # 全部 3 节点的 node_outputs 已记录
    assert "bootstrap-validate" in run_state.node_outputs
    assert "req-input-normalize" in run_state.node_outputs
    assert "req-draft" in run_state.node_outputs

    assert run_state.node_outputs["bootstrap-validate"]["output"] == "bootstrap output"
    assert run_state.node_outputs["req-draft"]["output"] == "draft output"

    # dispatch 应被调用 3 次
    assert mock_dispatch.call_count == 3
