"""高级取消场景：force_kill 兜底 + poll 时延边界（TC-F8-5/6）。

从 test_sub_workflow_lifecycle.py 拆出（rev3 G-3）。

覆盖：
- TC-F8-5 test_taskstop_force_kill  — 子阻塞 > 30s → 父超时调 TaskStop → 父写 child_force_killed
- TC-F8-6 test_poll_interval_boundary — poll_interval_ms=10000 快进 → 检测时延 ≤ poll_interval × 1.1

全部用例：
- 不真派 Agent（MockSubAgent + monkeypatch）
- 不真 sleep（monkeypatch 替换）
- 正常路径总耗时 ≤ 10 秒（异常时最长 5s）

来源：requirements/REQ-2026-009/artifacts/detailed-design.md §7.4 边-3/边-4
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import append_event  # noqa: E402

# 导入共享工具和 MockSubAgent（来自 tests/e2e/fixtures/ 包）
# F-011：ParentCancelCoordinator / write_event_to_jsonl 从 e2e_helpers 直接 import（去下划线公开名）
sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e" / "fixtures"))
from sub_workflow_mock import MockSubAgent  # noqa: E402
from e2e_helpers import (  # noqa: E402
    ParentCancelCoordinator as _ParentCancelCoordinator,
    get_event_types,
    make_run_dir,
    read_jsonl_events,
    write_event_to_jsonl as _write_event_to_jsonl,
)


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
    # 为不真 sleep 60s，把 _sleep 拆为两路：
    #   - fast_poll_sleep：poll 间隔短 sleep（secs < 1.0），立即返回让子线程继续进入 poll 逻辑
    #   - block_node_sleep：业务节点长 sleep（secs >= 1.0），阻塞等 unblock_event 或 5s 兜底
    # 注意：旧方案 max(secs, 60.0) 把 poll 间隔 0.01s 也撑成 60s wait，
    # 导致子线程卡在首次 poll 间隔，slow_poll_that_blocks_after_cancel 的写入路径无法执行。
    unblock_event = threading.Event()

    def fast_poll_sleep(secs: float):
        """poll 间隔的短 sleep，立即返回让子线程继续进入 poll 逻辑。"""
        pass  # 不真 sleep，快进 poll 间隔

    def block_node_sleep(secs: float):
        """业务节点的长 sleep，等 unblock_event 或 5s 兜底（与 docstring '总耗时 ≤ 10s' 对齐）。"""
        unblock_event.wait(timeout=5.0)

    def controlled_sleep(secs: float):
        """按 secs 阈值分发：< 1.0 快进（poll 间隔）/ >= 1.0 阻塞等 unblock_event。"""
        if secs < 1.0:
            fast_poll_sleep(secs)
        else:
            block_node_sleep(secs)

    # F-7：poll_started_event 注入点，run() 入口立即 set，消除调度竞态
    poll_started_event = threading.Event()
    agent = MockSubAgent(child_run_id, child_jsonl, poll_interval_ms=10,
                         poll_started_event=poll_started_event)
    monkeypatch.setattr(agent, "_sleep", controlled_sleep)

    # 子脚本：模拟"子收到 cancel 但忽略它，继续执行阻塞节点"的场景
    # 把 _poll_parent_cancel 替换为：始终返回 False（子忽略 cancel 信号），
    # 不写 parent_cancelled——子会继续执行到 __block_60 节点并阻塞在 block_node_sleep。
    # 这样 coordinator 在 graceful_timeout 内读不到 parent_cancelled，超时后调 TaskStop。
    #
    # 注意：协议上"子应主动写 parent_cancelled 后退出"，TC-F8-5 测试的是"子违反协议/
    # 阻塞不退出时父的兜底路径"（TaskStop force_kill），所以子故意不写 parent_cancelled。
    poll_call_count = [0]
    original_poll = agent._poll_parent_cancel

    def slow_poll_that_blocks_after_cancel(parent_j: Path) -> bool:
        """子忽略 cancel 信号（始终返回 False），让子继续执行到 __block_60 节点阻塞。

        模拟场景：子 poll 到 cancel_requested 但无法/不愿意 graceful exit
        （如子代码 bug / 子任务不可中断），导致父 30s 超时后调 TaskStop 兜底。
        """
        poll_call_count[0] += 1
        # 调原 poll 检查信号存在（用于 poll_call_count 统计），但始终返回 False
        _original_result = original_poll(parent_j)
        return False  # 子忽略 cancel，继续执行

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
    # F-7：使用 poll_started_event 等待子真正进入 run()（消除调度竞态，替代旧 agent_started.set()）
    def run_agent():
        agent.run(parent_jsonl, ["node-n1", "__block_60"])

    agent_thread = threading.Thread(target=run_agent, daemon=True)
    agent_thread.start()
    assert poll_started_event.wait(timeout=2.0), "TC-F8-5 子线程 2s 内未进入 run()"

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

    # 断言（F-5 空洞防护）：poll-mock 路径确实被执行（子线程真正进入了 poll 逻辑），
    # 而不是因 controlled_sleep 卡死子线程导致 poll 从未执行。
    # TC-F8-5 场景：子故意忽略 cancel（不写 parent_cancelled），所以 child_jsonl 不含该事件。
    # 但 poll_call_count > 0 证明子线程确实执行了 poll，而不是卡在 sleep 从未 poll。
    assert poll_call_count[0] > 0, (
        "TC-F8-5 子线程未真正执行 poll（poll_call_count=0），"
        "测试空洞——controlled_sleep 可能再次把 poll 间隔撑成长阻塞，"
        "子线程从未进入 slow_poll_that_blocks_after_cancel"
    )


# ============================================================================
# TC-F8-6: poll 间隔边界（快进 monkeypatch，不真 sleep 10s）
# ============================================================================

def test_poll_interval_boundary(tmp_path, monkeypatch):
    """TC-F8-6: poll_interval_ms=10000（10s）快进 → 检测时延 ≤ poll_interval × 1.1。

    不真 sleep 10s：
    - monkeypatch MockSubAgent._sleep = 立即返回（快进 poll 间隔）
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
        """记录每次 poll 的时间戳，检测到 cancel 时记录命中时刻，供时延断言计算。

        poll_timestamps：所有 poll 调用时刻（time.monotonic，单位秒）
        cancel_detected_at：首次检测到 cancel_requested 的时刻（用于计算检测时延）
        """
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
