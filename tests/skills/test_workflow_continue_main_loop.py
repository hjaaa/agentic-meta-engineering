"""F-007/F-008 · workflow_continue.py main loop 单测。

覆盖范围：
  TC-F7-1  approval_pending 场景：节点派发返回 approval_pending，main loop 设状态 + break
  TC-F7-2  完整链路：bash → approval → bash，能续跑到第二个 bash
  TC-F7-3  failed outcome：节点派发返回 failed，main loop 设状态 + break（F-007 兜底行为）
  TC-F8-1  _handle_failure retry 未达上限：current_node 保持，state=running，return False
  TC-F8-2  _handle_failure skip：写 node_skipped，推进 current_node，return True
  TC-F8-3  _handle_failure abort：写 workflow_failed，state=failed，return False
  TC-F8-4  _handle_failure retry 超上限：升级 abort，写 workflow_failed，state=failed
  TC-F8-5  main loop 端到端：mock dispatch_node，按 standard-8phase 前 3 节点顺序返 completed × 3

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
from workflow_continue import _handle_failure, _main_loop, _build_node_map, _next_node  # noqa: E402


# ============================================================================
# Fixture
# ============================================================================


@pytest.fixture()
def jsonl_path(tmp_path: Path) -> Path:
    """返回一个临时 jsonl 文件路径（父目录已存在）。"""
    return tmp_path / "run-state.jsonl"


@pytest.fixture()
def base_run_state() -> RunState:
    """最小化 RunState，run_id + current_node。"""
    return RunState(run_id="REQ-2026-010", current_node="node-a")


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


@pytest.fixture()
def mock_workflow_3nodes() -> dict:
    """3 节点 workflow：node-a (bash) → node-b (approval) → node-c (bash)。"""
    return {
        "id": "test-wf",
        "name": "test-workflow",
        "version": "1.0",
        "category": "requirement",
        "nodes": [
            {
                "id": "node-a",
                "bash": "echo 'step-a'",
                "next": "node-b",
            },
            {
                "id": "node-b",
                "approval": {"prompt": "Approve $RUN_ID?"},
                "next": "node-c",
            },
            {
                "id": "node-c",
                "bash": "echo 'step-c'",
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
# TC-F7-1 · approval_pending 场景（break）
# ============================================================================


def test_main_loop_approval_pending_breaks_and_sets_state(
    mock_workflow_2nodes,
    base_run_state,
    jsonl_path,
    tmp_path,
):
    """main loop 派发 approval 节点，返回 approval_pending，设状态 + break。

    场景：node-a (completed) → node-b (approval, outcome=approval_pending)
    期望：state 变为 approval_pending，current_node=node-b，loop break
    """
    from workflow_dispatcher import DispatchResult

    # 使用 side_effect 根据 node_id 返回不同结果
    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:

        def dispatch_side_effect(node, *args, **kwargs):
            node_id = node.get("id")
            if node_id == "node-a":
                return DispatchResult(outcome="completed", output="hello")
            elif node_id == "node-b":
                return DispatchResult(outcome="approval_pending")
            return DispatchResult(outcome="failed", error="unexpected node")

        mock_dispatch.side_effect = dispatch_side_effect

        base_run_state.state = "running"
        base_run_state.current_node = "node-a"
        _main_loop(base_run_state, mock_workflow_2nodes, tmp_path, tmp_path, jsonl_path)

        # 期望：state 变为 approval_pending，current_node 仍为 node-b
        assert base_run_state.state == "approval_pending"
        assert base_run_state.current_node == "node-b"

        # dispatch 应被调用 2 次（node-a + node-b）
        assert mock_dispatch.call_count == 2


# ============================================================================
# TC-F7-2 · 完整链路：bash → approval → bash（续跑场景）
# ============================================================================


def test_main_loop_complete_flow_3nodes_with_approval_and_continue(
    mock_workflow_3nodes,
    jsonl_path,
    tmp_path,
):
    """3 节点 workflow，第二节点（approval）后续跑。

    初始运行（first continuation）：
      node-a → completed
      node-b → approval_pending，state=approval_pending，break

    写 approval_approved 事件后续跑（second continuation）：
      从 node-b 恢复，应完成 node-b（approval）并推进到 node-c

    注：本用例验证的是单次 _main_loop 调用的行为，不跨越多次 continue 命令。
        actual 跨 continue 的完整链路由集成测试验证。
    """
    from workflow_dispatcher import DispatchResult

    # 第一次续跑：node-a completed，node-b approval_pending
    run_state_1 = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:

        def dispatch_side_effect_1(node, *args, **kwargs):
            node_id = node.get("id")
            if node_id == "node-a":
                return DispatchResult(outcome="completed", output="output-a")
            elif node_id == "node-b":
                return DispatchResult(outcome="approval_pending")
            return DispatchResult(outcome="failed")

        mock_dispatch.side_effect = dispatch_side_effect_1
        _main_loop(run_state_1, mock_workflow_3nodes, tmp_path, tmp_path, jsonl_path)

        assert run_state_1.state == "approval_pending"
        assert run_state_1.current_node == "node-b"
        assert "node-a" in run_state_1.node_outputs

    # 第二次续跑：node-b 和 node-c 都应成功（approval 实际上由用户手工 approve）
    # 模拟 approval_approved 后状态回到 running，继续派发
    run_state_2 = RunState(run_id="REQ-2026-010", current_node="node-b", state="approval_pending")
    run_state_2.node_outputs = run_state_1.node_outputs.copy()

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:

        def dispatch_side_effect_2(node, *args, **kwargs):
            node_id = node.get("id")
            if node_id == "node-b":
                # approval 节点实际上仅写事件，不返回 output；但这里我们让它返回 completed 表示审批流程完成
                return DispatchResult(outcome="completed", output=None)
            elif node_id == "node-c":
                return DispatchResult(outcome="completed", output="output-c")
            return DispatchResult(outcome="failed")

        mock_dispatch.side_effect = dispatch_side_effect_2
        run_state_2.state = "running"  # 模拟 approval_approved 后状态恢复
        _main_loop(run_state_2, mock_workflow_3nodes, tmp_path, tmp_path, jsonl_path)

        # 期望：node-c 完成，state 回到 running（因为拓扑末尾，current_node=None 触发 while 退出）
        assert run_state_2.state == "running"
        assert run_state_2.current_node is None
        assert "node-b" in run_state_2.node_outputs
        assert "node-c" in run_state_2.node_outputs


# ============================================================================
# TC-F7-3 · failed outcome
# ============================================================================


def test_main_loop_failed_outcome_sets_state_and_breaks(
    mock_workflow_2nodes,
    jsonl_path,
    tmp_path,
):
    """节点派发返回 failed，main loop 设 state=failed 并 break。"""
    from workflow_dispatcher import DispatchResult

    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        mock_dispatch.return_value = DispatchResult(
            outcome="failed",
            error="node-a execution failed",
        )

        _main_loop(run_state, mock_workflow_2nodes, tmp_path, tmp_path, jsonl_path)

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
# TC-F7-6 · loop_continue outcome（F-008 接入后：更新计数器，current_node 不变，继续循环）
# ============================================================================


def test_main_loop_loop_continue_updates_counter_and_keeps_current_node(
    jsonl_path,
    tmp_path,
):
    """TC-F7-6（更新）：F-008 接入后 loop_continue 正确处理——更新计数器，current_node 保持。

    场景：node-a 第一次返回 loop_continue，第二次返回 completed（退出循环）
    期望：loop_counters[node-a] = 1；最终 current_node 推进（node-b 或 None）
    """
    from workflow_dispatcher import DispatchResult

    workflow = {
        "nodes": [
            {"id": "node-a", "bash": "loop cmd", "next": "node-b"},
            {"id": "node-b", "bash": "final"},
        ]
    }
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    call_count = {"n": 0}

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:

        def side_effect(node, *args, **kwargs):
            call_count["n"] += 1
            if node.get("id") == "node-a":
                if call_count["n"] == 1:
                    return DispatchResult(outcome="loop_continue")
                return DispatchResult(outcome="completed", output="done")
            return DispatchResult(outcome="completed", output="final")

        mock_dispatch.side_effect = side_effect

        _main_loop(run_state, workflow, tmp_path, tmp_path, jsonl_path)

    # loop_counters 应更新（第 1 次 loop_continue 后计数为 1）
    assert run_state.loop_counters.get("node-a", 0) == 1

    # 最终 current_node 应已推进（node-a completed 后 → node-b；node-b completed 后 → None）
    assert run_state.current_node is None
    assert run_state.state == "running"


# ============================================================================
# TC-F7-7 · sub_workflow_pending（F-008 接入后：state 保持 running，break）
# ============================================================================


def test_main_loop_sub_workflow_pending_breaks_without_state_change(
    mock_workflow_2nodes,
    jsonl_path,
    tmp_path,
):
    """sub_workflow_pending：state 保持 running，main loop break，等待回调续跑。"""
    from workflow_dispatcher import DispatchResult

    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        mock_dispatch.return_value = DispatchResult(outcome="sub_workflow_pending")

        _main_loop(run_state, mock_workflow_2nodes, tmp_path, tmp_path, jsonl_path)

        assert run_state.state == "running"
        assert mock_dispatch.call_count == 1


# ============================================================================
# F-008 · _handle_failure 单测
# ============================================================================


@pytest.fixture()
def node_with_retry() -> dict:
    """带 on_failure=retry + max_retries=2 的节点。"""
    return {
        "id": "node-a",
        "bash": "echo 'step'",
        "next": "node-b",
        "on_failure": "retry",
        "max_retries": 2,
    }


@pytest.fixture()
def node_with_skip() -> dict:
    """带 on_failure=skip 的节点。"""
    return {
        "id": "node-a",
        "bash": "echo 'step'",
        "next": "node-b",
        "on_failure": "skip",
    }


@pytest.fixture()
def node_with_abort() -> dict:
    """带 on_failure=abort 的节点。"""
    return {
        "id": "node-a",
        "bash": "echo 'step'",
        "next": "node-b",
        "on_failure": "abort",
    }


# TC-F8-1 · retry 未达上限
def test_handle_failure_retry_below_max_retries_keeps_current_node(
    node_with_retry,
    jsonl_path,
):
    """retry 场景：失败次数 < max_retries，current_node 保持，state=running，返回 False。

    场景：max_retries=2，当前只失败 1 次（写 1 条 node_failed 事件）
    期望：_handle_failure 返回 False（main loop 应 break，等待下次 continue 重派）
          run_state.state 保持 running，current_node 保持 node-a
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    # 预写 1 条 node_failed 事件（模拟已失败 1 次）
    append_event(jsonl_path, {"type": "node_failed", "node_id": "node-a", "data": {"error": "err"}})

    result = _handle_failure(run_state, node_with_retry, "retry", jsonl_path, "some error")

    assert result is False  # main loop 应 break
    assert run_state.state == "running"  # state 保持 running（等下次 continue 重派）
    assert run_state.current_node == "node-a"  # current_node 不变


# TC-F8-2 · skip 场景
def test_handle_failure_skip_writes_node_skipped_and_advances(
    node_with_skip,
    jsonl_path,
):
    """skip 场景：写 node_skipped 事件，推进 current_node 到 node-b，返回 True。

    期望：_handle_failure 返回 True（main loop 继续循环）
          jsonl 中写入 node_skipped 事件
          run_state.current_node 推进为 node-b
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    result = _handle_failure(run_state, node_with_skip, "skip", jsonl_path, "some error")

    assert result is True  # main loop 应继续循环
    assert run_state.current_node == "node-b"  # 推进到 node-b

    # 验证 node_skipped 事件已写入
    events, _ = read_events(jsonl_path)
    skipped_events = [e for e in events if e.get("type") == "node_skipped"]
    assert len(skipped_events) == 1
    assert skipped_events[0]["node_id"] == "node-a"
    assert skipped_events[0]["data"]["reason"] == "on_failure=skip"


# TC-F8-3 · abort 场景
def test_handle_failure_abort_writes_workflow_failed(
    node_with_abort,
    jsonl_path,
):
    """abort 场景：写 workflow_failed 事件，state=failed，返回 False。

    期望：_handle_failure 返回 False（main loop 应 break）
          run_state.state = "failed"
          jsonl 中写入 workflow_failed 事件
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    result = _handle_failure(run_state, node_with_abort, "abort", jsonl_path, "fatal error")

    assert result is False  # main loop 应 break
    assert run_state.state == "failed"

    # 验证 workflow_failed 事件已写入
    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["node_id"] == "node-a"


# TC-F8-4 · retry 超上限升级为 abort
def test_handle_failure_retry_exhausted_upgrades_to_abort(
    node_with_retry,
    jsonl_path,
):
    """retry 超上限场景：已达 max_retries，升级为 abort，写 workflow_failed，state=failed。

    场景：max_retries=2，当前已失败 2 次（写 2 条 node_failed 事件）
    期望：_handle_failure 返回 False
          run_state.state = "failed"
          jsonl 中写入 workflow_failed 事件（reason=retry_exhausted）
    """
    run_state = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")

    # 预写 2 条 node_failed 事件（模拟已达上限）
    append_event(jsonl_path, {"type": "node_failed", "node_id": "node-a", "data": {"error": "err1"}})
    append_event(jsonl_path, {"type": "node_failed", "node_id": "node-a", "data": {"error": "err2"}})

    result = _handle_failure(run_state, node_with_retry, "retry", jsonl_path, "err3")

    assert result is False  # main loop 应 break
    assert run_state.state == "failed"

    # 验证 workflow_failed 事件已写入（reason=retry_exhausted）
    events, _ = read_events(jsonl_path)
    failed_events = [e for e in events if e.get("type") == "workflow_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["data"]["reason"] == "retry_exhausted"


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
