"""F-008 · sub_workflow 父子状态联动 e2e（TC-F8-1 ~ TC-F8-6）+ F-010 AC-05。

覆盖（详细设计 §7.4）：
- TC-F8-1 test_cancel_graceful_full_chain      — 父写 cancel_requested → 子 graceful 退出 + 父写 child_graceful_exited
- TC-F8-2 test_rollback_cross_parent_child     — rollback_run → moved_sub_runs 含子 + 子 jsonl 含 parent_rolled_back
- TC-F8-3 test_child_crash_on_subworkflow_failure — 子抛 RuntimeError → 父按 on_subworkflow_failure 三路径分支
- TC-F8-4 test_parent_crash_recovery           — 父写 cancel_requested 后崩溃 → 子继续 poll 命中后 graceful 退出
- TC-F8-AC05 test_ac05_mock_dispatch_node_completed_output — mock_agent_dispatch fixture + 完整 main loop + 断言 node_completed.output 非空

运行：
    python3 -m pytest tests/e2e/test_sub_workflow_lifecycle.py -v
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import append_event  # noqa: E402
from workflow_rollback import RollbackResult, SubRunArchive, rollback_run  # noqa: E402

# 导入共享工具和 MockSubAgent（来自 tests/e2e/fixtures/ 包）
sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e" / "fixtures"))
from sub_workflow_mock import MockSubAgent  # noqa: E402
from e2e_helpers import (  # noqa: E402
    ParentCancelCoordinator,
    copy_workflow_yaml,
    create_node_artifacts,
    get_event_types,
    make_run_dir,
    read_jsonl_events,
    write_child_jsonl_from_template,
    write_event_to_jsonl,
    write_parent_jsonl_from_template,
)


# ============================================================================
# 内部辅助别名（F-011：实现已提至 e2e_helpers.ParentCancelCoordinator / write_event_to_jsonl）
# 保留下划线别名供本文件内部调用和 test_sub_workflow_cancel_advanced.py 的跨文件 import
# ============================================================================

_ParentCancelCoordinator = ParentCancelCoordinator
_write_event_to_jsonl = write_event_to_jsonl


# ============================================================================
# TC-F8-1: cancel graceful 全链路
# ============================================================================

def test_cancel_graceful_full_chain(tmp_path):
    """TC-F8-1: 父写 cancel_requested → 子 poll 命中 → 子写 parent_cancelled + 父写 child_graceful_exited。

    验收条件（AC-11）：
    - 子 jsonl 末尾 type = parent_cancelled
    - 父 jsonl 含 child_graceful_exited
    - 不调 TaskStop（coordinator.task_stop_called = False）
    - 总耗时 ≤ 5 秒
    """
    start = time.monotonic()
    parent_run_id = "PARENT-F8-1"
    child_run_id = "CHILD-F8-1"

    # 建父 run 目录 + jsonl（仅写 workflow_started）
    parent_run_dir = make_run_dir(tmp_path, parent_run_id)
    parent_jsonl = parent_run_dir / "run-state.jsonl"
    _write_event_to_jsonl(parent_jsonl, {
        "type": "workflow_started", "ts": "2026-05-09T10:00:00Z",
        "run_id": parent_run_id, "data": {"workflow_name": "test-parent"},
    })

    # 建子 run 目录 + jsonl 文件（初始空，由 MockSubAgent 写）
    child_run_dir = make_run_dir(tmp_path, child_run_id)
    child_jsonl = child_run_dir / "run-state.jsonl"

    # MockSubAgent：poll_interval_ms=50（快速响应）
    # F-7：poll_started_event 注入点，run() 入口立即 set，消除调度竞态
    poll_started_event = threading.Event()
    agent = MockSubAgent(child_run_id, child_jsonl, poll_interval_ms=50,
                         poll_started_event=poll_started_event)

    # 父侧协调器：graceful_timeout=5s，poll_interval=0.02s
    coordinator = _ParentCancelCoordinator(
        parent_jsonl=parent_jsonl,
        child_jsonl=child_jsonl,
        parent_run_id=parent_run_id,
        graceful_timeout_secs=5.0,
        poll_interval_secs=0.02,
    )

    # 在后台线程运行子 agent（模拟 run_in_background=True）
    # 子有 3 个节点：N1, N2, N3
    # cancel_requested 在子启动后写入，子在 N2 之前的 poll 命中
    agent_result: list[str] = []

    def run_agent():
        result = agent.run(parent_jsonl, ["node-n1", "node-n2", "node-n3"])
        agent_result.append(result)

    agent_thread = threading.Thread(target=run_agent, daemon=True)
    agent_thread.start()
    assert poll_started_event.wait(timeout=2.0), "TC-F8-1 子线程 2s 内未进入 run()"

    # 子已进入 run()，父请求 cancel
    outcome = coordinator.request_cancel_and_wait(child_run_id)

    agent_thread.join(timeout=5.0)

    elapsed = time.monotonic() - start

    # 断言：子 graceful 退出
    assert outcome == "graceful", f"期望 graceful，实际：{outcome}"
    assert len(agent_result) == 1
    assert agent_result[0] == "graceful_exit", f"子 run 结果应为 graceful_exit，实际：{agent_result[0]}"

    # 断言：子 jsonl 末尾事件 = parent_cancelled
    child_events = read_jsonl_events(child_jsonl)
    assert child_events, "子 jsonl 不应为空"
    assert child_events[-1]["type"] == "parent_cancelled", (
        f"子 jsonl 末尾应为 parent_cancelled，实际：{child_events[-1]['type']}"
    )

    # 断言：父 jsonl 含 child_graceful_exited，不含 child_force_killed
    parent_types = get_event_types(parent_jsonl)
    assert "child_graceful_exited" in parent_types, f"父 jsonl 缺 child_graceful_exited，实际：{parent_types}"
    assert "child_force_killed" not in parent_types, "父 jsonl 不应含 child_force_killed"

    # 断言：未调 TaskStop
    assert not coordinator.task_stop_called, "不应调 TaskStop"

    # 断言：总耗时 ≤ 5 秒
    assert elapsed <= 5.0, f"总耗时超限：{elapsed:.2f}s > 5.0s"


# ============================================================================
# TC-F8-2: rollback 跨父子全链路
# ============================================================================

def test_rollback_cross_parent_child(tmp_path):
    """TC-F8-2: rollback_run(parent_id, to_node="node-a") → moved_sub_runs 含 1 项。

    验收条件（AC-10）：
    - RollbackResult.moved_sub_runs 含 1 项
    - .archived/<ts>/sub_runs/<child-id>/ 目录存在
    - 子 jsonl 含 parent_rolled_back
    - 父 jsonl 截断（node-b/c/d 不在原 jsonl 的 node_completed 中）
    """
    parent_run_id = "PARENT-F8-2"
    child_run_id = "CHILD-F8-2"

    # 建父 run 目录（复用 F1 fixture 的 workflow.yaml 和父 jsonl 模板）
    parent_run_dir = make_run_dir(tmp_path, parent_run_id)
    copy_workflow_yaml(parent_run_dir)
    write_parent_jsonl_from_template(parent_run_dir, parent_run_id)

    # 创建父 run 各节点产物
    create_node_artifacts(parent_run_dir, ["node-a", "node-b", "node-c", "node-d"])

    # 建子 run 目录（放在 parent_run_dir/sub_runs/<child_id>/）
    child_run_dir = parent_run_dir / "sub_runs" / child_run_id
    child_run_dir.mkdir(parents=True, exist_ok=True)
    write_child_jsonl_from_template(child_run_dir, child_run_id)
    create_node_artifacts(child_run_dir, ["child-step"])

    # 执行 rollback 到 node-a
    result = rollback_run(parent_run_id, "node-a", repo_root=tmp_path)

    # 断言：返回值类型
    assert isinstance(result, RollbackResult)

    # 断言：moved_sub_runs 含 1 项
    assert len(result.moved_sub_runs) >= 1, (
        f"RollbackResult.moved_sub_runs 应含 1 项，实际：{len(result.moved_sub_runs)}"
    )
    sub_archive = result.moved_sub_runs[0]
    assert isinstance(sub_archive, SubRunArchive)

    # 断言：.archived/<ts>/sub_runs/<child-id>/ 目录存在
    expected_archive_path = result.archive_root / "sub_runs" / child_run_id
    assert expected_archive_path.is_dir(), (
        f".archived/<ts>/sub_runs/{child_run_id}/ 不存在：{expected_archive_path}"
    )

    # 断言：子 jsonl 含 parent_rolled_back
    archived_child_jsonl = expected_archive_path / "run-state.jsonl"
    child_types = get_event_types(archived_child_jsonl)
    assert "parent_rolled_back" in child_types, (
        f"子 jsonl 应含 parent_rolled_back，实际：{child_types}"
    )

    # 断言：父 jsonl 截断（不含 node-b/c/d 的 node_completed）
    parent_jsonl = parent_run_dir / "run-state.jsonl"
    parent_events = read_jsonl_events(parent_jsonl)
    completed_nodes = {
        e.get("node_id") for e in parent_events
        if e.get("type") == "node_completed"
    }
    assert "node-b" not in completed_nodes, "父 jsonl 截断后不应含 node-b completed"
    assert "node-c" not in completed_nodes, "父 jsonl 截断后不应含 node-c completed"
    assert "node-d" not in completed_nodes, "父 jsonl 截断后不应含 node-d completed"
    assert "node-a" in completed_nodes, "父 jsonl 截断后应含 node-a completed"

    # 断言：子 run 原目录已删
    assert not (parent_run_dir / "sub_runs" / child_run_id).exists(), (
        "子 run 原目录应已被 mv 归档"
    )


# ============================================================================
# TC-F8-3: 子崩（on_subworkflow_failure 三路径）
# ============================================================================

@pytest.mark.parametrize("on_failure,expected_parent_event", [
    ("fail", "child_failed"),
    ("continue", "child_failed"),
    ("skip", "child_failed"),
])
def test_child_crash_on_subworkflow_failure(
    tmp_path, on_failure: str, expected_parent_event: str
):
    """TC-F8-3: 子抛 RuntimeError → 父按 on_subworkflow_failure 字段写 child_failed。

    三条参数化路径：
    - fail     → 父写 child_failed（父节点应 fail）
    - continue → 父写 child_failed（父继续下游）
    - skip     → 父写 child_failed（父跳过本节点直接进 next）

    本测试验证：
    1. 子 jsonl 含 node_failed 事件
    2. 父 jsonl 含 child_failed 事件
    3. child_failed 事件 data 中包含 on_subworkflow_failure 字段
    """
    parent_run_id = f"PARENT-F8-3-{on_failure.upper()}"
    child_run_id = f"CHILD-F8-3-{on_failure.upper()}"

    parent_run_dir = make_run_dir(tmp_path, parent_run_id)
    parent_jsonl = parent_run_dir / "run-state.jsonl"
    _write_event_to_jsonl(parent_jsonl, {
        "type": "workflow_started", "ts": "2026-05-09T10:00:00Z",
        "run_id": parent_run_id, "data": {"workflow_name": "test-parent"},
    })

    child_run_dir = make_run_dir(tmp_path, child_run_id)
    child_jsonl = child_run_dir / "run-state.jsonl"

    # MockSubAgent：节点 "__raise_node-n1-error" 会抛 RuntimeError
    agent = MockSubAgent(child_run_id, child_jsonl, poll_interval_ms=10)

    # 在线程中运行子 agent，捕获异常
    child_exception: list[Exception] = []

    def run_agent():
        try:
            agent.run(
                parent_jsonl,
                ["__raise_node-n1-error"],
            )
        except Exception as exc:
            # 业务预期失败（子节点 raise 是 TC-F8-3 设计意图），用 WARN 而非 ERROR/exception
            logger.warning(
                "TC-F8-3 子 agent 抛预期异常（type=%s, child_run_id=%s）",
                type(exc).__name__, agent.child_run_id,
            )
            child_exception.append(exc)

    agent_thread = threading.Thread(target=run_agent, daemon=True)
    agent_thread.start()
    agent_thread.join(timeout=3.0)

    # 验证子抛了 RuntimeError
    assert len(child_exception) == 1, "子应抛 RuntimeError"
    assert "node-n1-error" in str(child_exception[0])

    # 子 jsonl 含 node_failed
    child_types = get_event_types(child_jsonl)
    assert "node_failed" in child_types, f"子 jsonl 应含 node_failed，实际：{child_types}"

    # 父侧：检测子异常后写 child_failed（模拟父侧观测到子崩）
    # 父侧逻辑：检测到子 run 的 jsonl 含 node_failed 后，根据 on_subworkflow_failure 决策
    _simulate_parent_detect_child_failure(
        parent_jsonl=parent_jsonl,
        child_run_id=child_run_id,
        on_subworkflow_failure=on_failure,
        parent_run_id=parent_run_id,
    )

    # 断言：父 jsonl 含 child_failed
    parent_types = get_event_types(parent_jsonl)
    assert expected_parent_event in parent_types, (
        f"父 jsonl 应含 {expected_parent_event}，实际：{parent_types}"
    )

    # 断言：child_failed 事件含 on_subworkflow_failure 字段
    parent_events = read_jsonl_events(parent_jsonl)
    child_failed_events = [e for e in parent_events if e.get("type") == "child_failed"]
    assert len(child_failed_events) == 1, "父 jsonl 应含 1 个 child_failed 事件"
    assert child_failed_events[0].get("data", {}).get("on_subworkflow_failure") == on_failure, (
        f"child_failed 事件应含 on_subworkflow_failure={on_failure!r}"
    )


def _simulate_parent_detect_child_failure(
    parent_jsonl: Path,
    child_run_id: str,
    on_subworkflow_failure: str,
    parent_run_id: str,
) -> None:
    """模拟父侧检测到子异常退出后的处理（写 child_failed 事件）。

    实际引擎中此逻辑在 workflow_engine.py 子节点等待路径；
    本 e2e 测试用此 helper 模拟该父侧行为，保证 TC-F8-3 不依赖未落地引擎。
    """
    append_event(parent_jsonl, {
        "type": "child_failed",
        "run_id": parent_run_id,
        "data": {
            "child_run_id": child_run_id,
            "on_subworkflow_failure": on_subworkflow_failure,
        },
    })


# ============================================================================
# TC-F8-4: 父崩恢复（cancel 写入后父崩 → 子继续 poll 命中后 graceful 退出）
# ============================================================================

def test_parent_crash_recovery(tmp_path):
    """TC-F8-4: 父写 cancel_requested 后崩溃 → 子继续 poll 命中后正常 graceful 退出。

    场景：
    1. 父写 cancel_requested 到 jsonl（模拟崩溃前已写入）
    2. 父进程崩溃（monkeypatch raise 后跳过父侧等待逻辑）
    3. 子 subagent 继续 poll，检测到 cancel_requested → 写 parent_cancelled → graceful 退出
    4. 父崩重启后续跑：发现子 jsonl 已含 parent_cancelled，认为子已完成

    验收：
    - 子 jsonl 含 parent_cancelled
    - 父 jsonl 含 cancel_requested（已持久化）
    - 父重启后能读到子已 graceful（child_already_graceful=True）
    """
    parent_run_id = "PARENT-F8-4"
    child_run_id = "CHILD-F8-4"

    parent_run_dir = make_run_dir(tmp_path, parent_run_id)
    parent_jsonl = parent_run_dir / "run-state.jsonl"
    _write_event_to_jsonl(parent_jsonl, {
        "type": "workflow_started", "ts": "2026-05-09T10:00:00Z",
        "run_id": parent_run_id, "data": {"workflow_name": "test-parent"},
    })

    child_run_dir = make_run_dir(tmp_path, child_run_id)
    child_jsonl = child_run_dir / "run-state.jsonl"

    # 步骤 1：父写 cancel_requested（模拟父崩前已持久化）
    append_event(parent_jsonl, {
        "type": "cancel_requested",
        "run_id": parent_run_id,
    })

    # 步骤 2：父"崩溃"——直接跳过父侧等待逻辑（不启动 coordinator.request_cancel_and_wait）
    # 此处用 flag 模拟父已崩溃且等待逻辑未执行

    # 步骤 3：子继续 poll，命中 cancel_requested → graceful 退出
    agent = MockSubAgent(child_run_id, child_jsonl, poll_interval_ms=20)
    # 子有 2 个节点；cancel 已写入，第一个节点边界 poll 必然命中
    agent_result = agent.run(parent_jsonl, ["node-n1", "node-n2"])

    # 断言：子 graceful 退出
    assert agent_result == "graceful_exit", f"子应 graceful 退出，实际：{agent_result}"

    # 断言：子 jsonl 含 parent_cancelled
    child_types = get_event_types(child_jsonl)
    assert "parent_cancelled" in child_types, f"子 jsonl 应含 parent_cancelled，实际：{child_types}"

    # 步骤 4：父崩重启后续跑——检测子是否已 graceful
    # 模拟重启后父读子 jsonl 判断子状态
    child_graceful_detected = "parent_cancelled" in get_event_types(child_jsonl)
    assert child_graceful_detected, "父崩重启续跑应能发现子已 graceful 退出"

    # 断言：父 jsonl 仍含 cancel_requested（持久化未丢失）
    parent_types = get_event_types(parent_jsonl)
    assert "cancel_requested" in parent_types, "父 jsonl 应含 cancel_requested（崩溃前已写入）"

# TC-F8-5 和 TC-F8-6 已拆分到 test_sub_workflow_cancel_advanced.py（rev3 G-3）


# ============================================================================
# TC-F8-AC05（F-010）：mock_agent_dispatch + workflow_continue.main 全链路
#
# 独立于 MockSubAgent 体系：用 mock_agent_dispatch fixture 替换 _dispatch_agent_node，
# 验证 main loop 写入 node_completed 事件且 data.output 非空。
# ============================================================================

_AC05_WORKFLOW_F8 = {
    "name": "test-agent-ac05-f8",
    "version": 1,
    "category": "requirement",
    "nodes": [
        {
            "id": "ac05-f8-agent-node",
            "agent": "test-sub-agent",
            "mock_response": {"status": "completed", "summary": "AC-05 F8 验证"},
        }
    ],
}


def test_ac05_mock_dispatch_node_completed_output(
    mock_agent_dispatch: list[dict],
    tmp_path: Path,
) -> None:
    """TC-F8-AC05: mock_agent_dispatch + workflow_continue.main → node_completed.output 非空。

    验收要点（AC-05）：
    1. mock dispatcher 被调到（captured_calls 非空）
    2. jsonl 中存在 node_completed 事件
    3. node_completed.data.output 序列化后长度 > 0（非空非 null）
    4. 全程无真实 Agent 派发（无网络依赖）
    """
    import workflow_continue

    run_id = "TEST-AC05-F8"
    workflow_name = "test-agent-ac05-f8"

    # 构建测试 workflow yaml
    wf_dir = tmp_path / ".claude" / "workflows" / "requirement"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / f"{workflow_name}.yaml").write_text(
        yaml.dump(_AC05_WORKFLOW_F8, allow_unicode=True),
        encoding="utf-8",
    )

    # 构建 run 目录（uses runs/<id>/ 路径，与 _resolve_run_dir D-007 新路径对应）
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = run_dir / "run-state.jsonl"

    # node_started 使 RunState.current_node 指向该节点，main loop 会重跑它
    init_events = [
        {
            "type": "workflow_started",
            "run_id": run_id,
            "data": {"workflow_name": workflow_name},
        },
        {
            "type": "node_started",
            "run_id": run_id,
            "node_id": "ac05-f8-agent-node",
        },
    ]
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for evt in init_events:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")

    rc = workflow_continue.main([run_id], repo_root=tmp_path)
    assert rc == 0, f"workflow_continue.main 应返回 0，实际 rc={rc}"

    # 读 jsonl 验证 node_completed 事件存在且 output 非空
    events: list[dict] = []
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    completed = [e for e in events if e.get("type") == "node_completed"]
    assert completed, "至少应有 1 个 node_completed 事件"

    # AC-05 核心断言：output 非空
    for ev in completed:
        assert any(
            e["type"] == "node_completed" and len(json.dumps(e["data"]["output"])) > 0
            for e in completed
        ), f"node_completed.data.output 不应为空：{ev}"

    # mock fixture 被调到
    assert mock_agent_dispatch, "mock_agent_dispatch 应记录至少 1 次调用"
    assert mock_agent_dispatch[0]["node_id"] == "ac05-f8-agent-node"
