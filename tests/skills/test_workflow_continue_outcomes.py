"""F-008 · workflow_continue.py outcome 路由单测。

覆盖范围（按 outcome 类型分组）：
  TC-F7-1  approval_pending 场景：节点派发返回 approval_pending，main loop 设状态 + break
  TC-F7-2  完整链路：bash → approval → bash，能续跑到第二个 bash
  TC-F7-6  loop_continue：更新计数器，current_node 保持不变
  TC-F7-7  sub_workflow_pending：state 保持 running，break

从 test_workflow_continue_main_loop.py 拆出（F-NEW-7）：
  原文件超 500 行（520 行），按 outcome 路由维度拆分独立文件，降低单文件认知负担。

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

from run_state import RunState  # noqa: E402
from workflow_continue import _main_loop  # noqa: E402


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
# F-011 rev2 follow-up：loop_continue 写 loop_counter_advanced + crash 后恢复
# ============================================================================


def test_loop_continue_writes_counter_advanced_event(jsonl_path, tmp_path):
    """_route_outcome 收到 loop_continue 后必须写 loop_counter_advanced 事件。

    若只在内存 +1 不写事件，crash 后 rebuild 漏读 → dispatcher 用旧 iteration 重派同轮。
    """
    from run_state import read_events
    from workflow_dispatcher import DispatchResult

    workflow = {
        "nodes": [
            {"id": "node-a", "bash": "loop cmd", "next": "node-b"},
            {"id": "node-b", "bash": "final"},
        ],
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

    events, warnings = read_events(jsonl_path)
    advanced = [e for e in events if e.get("type") == "loop_counter_advanced"]
    assert len(advanced) == 1, [e.get("type") for e in events]
    assert advanced[0].get("node_id") == "node-a"
    assert advanced[0].get("data", {}).get("new_value") == 1


def test_loop_continue_persists_counters_across_crash_recovery(jsonl_path, tmp_path):
    """crash 后 rebuild 必须从 jsonl 还原 loop_counters，dispatcher 不重派同 iteration。

    模拟：run-1 派 node-a 1 次 → loop_continue → 进程结束（不在 main loop 内再次 dispatch）。
    crash 恢复：从 jsonl rebuild RunState → loop_counters[node-a] 应为 1（不是 0）。
    再续跑：dispatch_node 接收的 run_state.loop_counters["node-a"] = 1，dispatcher 据此
    把下一次 loop_iteration_started.iteration 写成 1，证明不重派 iteration=0。
    """
    from run_state import read_events
    from workflow_dispatcher import DispatchResult

    workflow = {
        "nodes": [
            {"id": "node-a", "bash": "loop cmd", "next": "node-b"},
            {"id": "node-b", "bash": "final"},
        ],
    }

    # ---------- run-1：node-a 派一次，loop_continue 后 break（模拟 crash 前停在此处） ----------
    run_state_1 = RunState(run_id="REQ-2026-010", current_node="node-a", state="running")
    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        call_count_1 = {"n": 0}

        def side_effect_1(node, *args, **kwargs):
            call_count_1["n"] += 1
            # 第 1 次 loop_continue 之后立即把 state 设为 paused 让 main loop 退出
            # （模拟用户 Ctrl-C / crash 落点）
            run_state_1.state = "paused"
            return DispatchResult(outcome="loop_continue")

        mock_dispatch.side_effect = side_effect_1
        _main_loop(run_state_1, workflow, tmp_path, tmp_path, jsonl_path)

    # crash 前：内存 loop_counters 已 +1，事件也已写盘
    assert run_state_1.loop_counters["node-a"] == 1

    # ---------- crash 后：从 jsonl rebuild ----------
    events, warnings = read_events(jsonl_path)
    bad = [w for w in warnings if "不在白名单" in w or "解析失败" in w]
    assert not bad, bad
    run_state_2 = RunState.rebuild(events, run_id="REQ-2026-010")

    # 关键断言：rebuild 后 loop_counters 等于 crash 前内存值，没有漏读 +1
    assert run_state_2.loop_counters.get("node-a") == 1, (
        f"crash 恢复后 loop_counters 漏读 +1：{run_state_2.loop_counters}"
    )
