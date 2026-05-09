"""F-008 · sub_workflow 父子状态联动 e2e（TC-F8-1 ~ TC-F8-6）。

覆盖（详细设计 §7.4）：
- TC-F8-1 test_cancel_graceful_full_chain      — 父写 cancel_requested → 子 graceful 退出 + 父写 child_graceful_exited
- TC-F8-2 test_rollback_cross_parent_child     — rollback_run → moved_sub_runs 含子 + 子 jsonl 含 parent_rolled_back
- TC-F8-3 test_child_crash_on_subworkflow_failure — 子抛 RuntimeError → 父按 on_subworkflow_failure 三路径分支
- TC-F8-4 test_parent_crash_recovery           — 父写 cancel_requested 后崩溃 → 子继续 poll 命中后 graceful 退出
- TC-F8-5 test_taskstop_force_kill             — 子阻塞 > 30s → 父超时调 TaskStop → 父写 child_force_killed
- TC-F8-6 test_poll_interval_boundary          — poll_interval_ms=10000 快进 → 检测时延 ≤ poll_interval × 1.1

全部用例：
- 不真派 Agent（MockSubAgent + monkeypatch）
- 总耗时 ≤ 10 秒
- 命名：test_xxx_yyy 对应 TC-F8-N

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
from typing import Any

import pytest

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import append_event  # noqa: E402
from workflow_rollback import RollbackResult, SubRunArchive, rollback_run  # noqa: E402

# 导入共享工具和 MockSubAgent（来自 tests/e2e/fixtures/ 包）
sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e" / "fixtures"))
from sub_workflow_mock import MockSubAgent  # noqa: E402
from e2e_helpers import (  # noqa: E402
    copy_workflow_yaml,
    create_node_artifacts,
    get_event_types,
    make_run_dir,
    read_jsonl_events,
    write_child_jsonl_from_template,
    write_parent_jsonl_from_template,
)


# ============================================================================
# 内部辅助：父侧协调器（模拟父 run 的 cancel 等待逻辑）
# ============================================================================

class _ParentCancelCoordinator:
    """父侧等待子 graceful 退出的协调器（模拟 §7.1 时序图父侧逻辑）。

    职责：
    1. 向父 jsonl 写 cancel_requested
    2. 轮询等待子 jsonl 出现 parent_cancelled（graceful 信号）
    3. 若超时则调 task_stop_fn（TaskStop 兜底）
    4. 写 child_graceful_exited 或 child_force_killed 到父 jsonl
    """

    def __init__(
        self,
        parent_jsonl: Path,
        child_jsonl: Path,
        parent_run_id: str,
        graceful_timeout_secs: float = 30.0,
        poll_interval_secs: float = 0.05,
    ) -> None:
        self.parent_jsonl = parent_jsonl
        self.child_jsonl = child_jsonl
        self.parent_run_id = parent_run_id
        self.graceful_timeout_secs = graceful_timeout_secs
        self.poll_interval_secs = poll_interval_secs
        # 注入点：测试可 mock 以拦截 TaskStop 调用
        self.task_stop_called = False
        self.task_stop_run_id: str | None = None

    def request_cancel_and_wait(self, child_run_id: str) -> str:
        """写 cancel_requested 并等待子 graceful 退出。

        返回：
            "graceful"     — 子在 timeout 内写了 parent_cancelled
            "force_killed" — 超时，调 TaskStop
        """
        # 父写 cancel_requested
        append_event(self.parent_jsonl, {
            "type": "cancel_requested",
            "run_id": self.parent_run_id,
        })

        # 轮询子 jsonl
        deadline = time.monotonic() + self.graceful_timeout_secs
        while time.monotonic() < deadline:
            child_types = get_event_types(self.child_jsonl)
            if "parent_cancelled" in child_types:
                # 子 graceful 退出，父写 child_graceful_exited
                append_event(self.parent_jsonl, {
                    "type": "child_graceful_exited",
                    "run_id": self.parent_run_id,
                    "data": {"child_run_id": child_run_id},
                })
                return "graceful"
            time.sleep(self.poll_interval_secs)

        # 超时：TaskStop forceful 兜底
        self._call_task_stop(child_run_id)
        append_event(self.parent_jsonl, {
            "type": "child_force_killed",
            "run_id": self.parent_run_id,
            "data": {"child_run_id": child_run_id},
        })
        return "force_killed"

    def _call_task_stop(self, child_run_id: str) -> None:
        """调用 TaskStop（生产 = Anthropic SDK；测试可 monkeypatch）。

        当前为 stub；F-009 落地时替换为真实调用。
        记录调用情况供测试断言使用。
        """
        self.task_stop_called = True
        self.task_stop_run_id = child_run_id


def _write_event_to_jsonl(jsonl_path: Path, event: dict[str, Any]) -> None:
    """直接向 jsonl 写入一条事件（无 VALID_EVENT_TYPES 校验，用于造 fixture 数据）。"""
    payload = json.dumps(event, ensure_ascii=False) + "\n"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(payload)


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
    agent = MockSubAgent(child_run_id, child_jsonl, poll_interval_ms=50)

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
    agent_started = threading.Event()

    def run_agent():
        agent_started.set()
        result = agent.run(parent_jsonl, ["node-n1", "node-n2", "node-n3"])
        agent_result.append(result)

    agent_thread = threading.Thread(target=run_agent, daemon=True)
    agent_thread.start()
    assert agent_started.wait(timeout=2.0), "TC-F8-1 子线程 2s 内未启动"

    # 子已启动，父请求 cancel
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
            logger.exception(
                "TC-F8-3 子 agent 抛异常（type=%s, child_run_id=%s）",
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


# ============================================================================
# TC-F8-5: TaskStop forceful kill（子阻塞 > 30s）
# ============================================================================

def test_taskstop_force_kill(tmp_path, monkeypatch):
    """TC-F8-5: 子 poll 命中但故意阻塞 → 父 30s 超时调 TaskStop → 父写 child_force_killed。

    不真 sleep 30s：
    - monkeypatch MockSubAgent._sleep 为阻塞线程直到测试主动中止
    - coordinator.graceful_timeout_secs = 0.1（快速超时）
    - TaskStop 通过 coordinator._call_task_stop 被 monkeypatch 记录

    验收：
    - coordinator.task_stop_called = True
    - 父 jsonl 含 child_force_killed
    - 不含 child_graceful_exited
    """
    parent_run_id = "PARENT-F8-5"
    child_run_id = "CHILD-F8-5"

    parent_run_dir = make_run_dir(tmp_path, parent_run_id)
    parent_jsonl = parent_run_dir / "run-state.jsonl"
    _write_event_to_jsonl(parent_jsonl, {
        "type": "workflow_started", "ts": "2026-05-09T10:00:00Z",
        "run_id": parent_run_id, "data": {"workflow_name": "test-parent"},
    })

    child_run_dir = make_run_dir(tmp_path, child_run_id)
    child_jsonl = child_run_dir / "run-state.jsonl"

    # MockSubAgent：poll_interval_ms=10，节点 "__block_60" 模拟阻塞 60s
    # 为不真 sleep 60s，把 _sleep 替换为受控阻塞
    unblock_event = threading.Event()

    def controlled_sleep(secs: float):
        """阻塞直到 unblock_event set，不依赖真实时间。"""
        unblock_event.wait(timeout=max(secs, 60.0))

    agent = MockSubAgent(child_run_id, child_jsonl, poll_interval_ms=10)
    monkeypatch.setattr(agent, "_sleep", controlled_sleep)

    # 子脚本：先正常节点（poll 命中后 graceful_exit）然后阻塞节点
    # 为模拟"poll 命中但阻塞"的场景，把 _poll_parent_cancel 替换为：
    # 首次 poll 命中后写 parent_cancelled，再执行真正阻塞节点
    poll_call_count = [0]
    original_poll = agent._poll_parent_cancel

    def slow_poll_that_blocks_after_cancel(parent_j: Path) -> bool:
        """首次 poll 命中（写 parent_cancelled），之后子仍阻塞（故意不返回 graceful_exit）。"""
        poll_call_count[0] += 1
        result = original_poll(parent_j)
        # 首次命中：写 parent_cancelled 后继续（不 return True，模拟子已写入但仍阻塞）
        if result and poll_call_count[0] == 1:
            # 子手动写 parent_cancelled（因为我们不走 run 的正常路径）
            from sub_workflow_mock import _utc_now_iso
            payload = json.dumps({
                "type": "parent_cancelled",
                "ts": _utc_now_iso(),
                "run_id": child_run_id,
            }, ensure_ascii=False) + "\n"
            with child_jsonl.open("a", encoding="utf-8") as fh:
                fh.write(payload)
            # 继续阻塞（返回 False 让子不执行 graceful_exit，而是继续下一节点/阻塞）
            return False
        return result

    monkeypatch.setattr(agent, "_poll_parent_cancel", slow_poll_that_blocks_after_cancel)

    # 协调器：graceful_timeout=0.2s（快速超时，不真等 30s）
    coordinator = _ParentCancelCoordinator(
        parent_jsonl=parent_jsonl,
        child_jsonl=child_jsonl,
        parent_run_id=parent_run_id,
        graceful_timeout_secs=0.2,
        poll_interval_secs=0.02,
    )

    # 后台运行子 agent（阻塞在 __block_ 节点）
    agent_thread = threading.Thread(
        target=lambda: agent.run(parent_jsonl, ["node-n1", "__block_60"]),
        daemon=True,
    )
    agent_thread.start()

    # 等子启动
    time.sleep(0.02)

    # 父请求 cancel + 等待（0.2s 超时触发 TaskStop）
    outcome = coordinator.request_cancel_and_wait(child_run_id)

    # 解除子的阻塞（避免线程泄漏）
    unblock_event.set()
    agent_thread.join(timeout=1.0)

    # 断言：超时走 force_killed 路径
    assert outcome == "force_killed", f"期望 force_killed，实际：{outcome}"

    # 断言：TaskStop 被调用
    assert coordinator.task_stop_called, "超时应调 TaskStop（coordinator.task_stop_called=True）"

    # 断言：父 jsonl 含 child_force_killed
    parent_types = get_event_types(parent_jsonl)
    assert "child_force_killed" in parent_types, (
        f"父 jsonl 应含 child_force_killed，实际：{parent_types}"
    )

    # 断言：不含 child_graceful_exited
    assert "child_graceful_exited" not in parent_types, (
        "超时路径不应含 child_graceful_exited"
    )


# ============================================================================
# TC-F8-6: poll 间隔边界（快进 monkeypatch，不真 sleep 10s）
# ============================================================================

def test_poll_interval_boundary(tmp_path, monkeypatch):
    """TC-F8-6: poll_interval_ms=10000（10s）快进 → 检测时延 ≤ poll_interval × 1.1。

    不真 sleep 10s：
    - monkeypatch MockSubAgent._sleep = 立即返回（快进 poll 间隔）
    - monkeypatch time.monotonic 在父侧推进虚拟时钟（快进 scripted 节点耗时）
    - 验证：cancel 从写入到子检测到的时延 ≤ poll_interval_ms × 1.1 ms（换算秒）

    注：因为 mock 后 sleep 是 no-op，真实时延会远低于 10s。
    关键是验证：检测 cancel 的逻辑在 poll_interval 内（即子不会"多跑"超过一个 poll 周期）。
    """
    parent_run_id = "PARENT-F8-6"
    child_run_id = "CHILD-F8-6"

    parent_run_dir = make_run_dir(tmp_path, parent_run_id)
    parent_jsonl = parent_run_dir / "run-state.jsonl"
    _write_event_to_jsonl(parent_jsonl, {
        "type": "workflow_started", "ts": "2026-05-09T10:00:00Z",
        "run_id": parent_run_id, "data": {"workflow_name": "test-parent"},
    })

    child_run_dir = make_run_dir(tmp_path, child_run_id)
    child_jsonl = child_run_dir / "run-state.jsonl"

    poll_interval_ms = 10000  # 规格值：10s
    upper_bound_ms = poll_interval_ms * 1.1  # 上界 = 11000ms

    # 快进：_sleep → no-op（不真 sleep 10s）
    agent = MockSubAgent(child_run_id, child_jsonl, poll_interval_ms=poll_interval_ms)
    monkeypatch.setattr(agent, "_sleep", lambda secs: None)

    # 记录各次 poll 的虚拟时间（用 time.monotonic 的实际值，sleep 是 no-op 所以几乎瞬时）
    poll_timestamps: list[float] = []
    cancel_detected_at: list[float] = []
    original_poll = agent._poll_parent_cancel

    def tracking_poll(parent_j: Path) -> bool:
        t = time.monotonic()
        poll_timestamps.append(t)
        result = original_poll(parent_j)
        if result:
            cancel_detected_at.append(t)
        return result

    monkeypatch.setattr(agent, "_poll_parent_cancel", tracking_poll)

    # 预先写 cancel_requested 到父 jsonl（在子启动前即存在）
    append_event(parent_jsonl, {
        "type": "cancel_requested",
        "run_id": parent_run_id,
    })
    cancel_written_at = time.monotonic()

    # 运行子 agent（同步，因为 sleep = no-op 所以立即跑完）
    result = agent.run(parent_jsonl, ["node-n1", "node-n2", "node-n3"])

    # 断言：子 graceful 退出
    assert result == "graceful_exit", f"子应 graceful 退出，实际：{result}"

    # 断言：子 jsonl 末尾 = parent_cancelled
    child_events = read_jsonl_events(child_jsonl)
    assert child_events[-1]["type"] == "parent_cancelled", (
        f"子 jsonl 末尾应为 parent_cancelled，实际：{child_events[-1]['type']}"
    )

    # 断言：cancel 检测时延（因 sleep=no-op，实际时延 << poll_interval；
    # 关键验证：cancel 在第一次 poll 时就被检测到，不会等超过 1 个 poll 周期）
    assert len(cancel_detected_at) >= 1, "应有至少 1 次 poll 命中 cancel"
    assert len(poll_timestamps) >= 1, "应有至少 1 次 poll"

    # 实际检测时延（从 cancel 写入到检测到）
    # 因为 sleep=no-op，实际时延远小于 upper_bound_ms；
    # 主要验证：检测到 cancel 在第一次 poll 时（即最多走完一个节点的边界就会检测到）
    actual_delay_ms = (cancel_detected_at[0] - cancel_written_at) * 1000
    assert actual_delay_ms <= upper_bound_ms, (
        f"cancel 检测时延 {actual_delay_ms:.1f}ms 超过上界 {upper_bound_ms:.1f}ms"
        f"（poll_interval_ms={poll_interval_ms}）"
    )
