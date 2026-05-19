"""run-state.jsonl 读写 + RunState 反扫重建（F-001 范围）。

公开 API：
- `read_events(jsonl_path)` → tuple[list[Event], list[str]]：解析 jsonl，返回 (events, warnings)
- `append_event(jsonl_path, event)` → None：用 fcntl.LOCK_EX + O_APPEND 原子追加
- `RunState.rebuild(events, run_id?)` → RunState：从事件流重建状态

内部工具（loader 调用，不对外暴露）：
- `_resolve_run_dir(run_id)` → Path：D-007 双路径解析（先 requirements/<id>/，再 runs/<id>/）

事件枚举（spec §5.4 + D-005 v2.1）：
- workflow_started / workflow_paused / workflow_completed / workflow_failed / workflow_cancelled
- cancel_requested / cancel_taskstop_failed
- run_resumed
- save
- node_started / node_completed / node_failed / node_skipped / node_retried
- approval_pending / approval_approved / approval_rejected
- loop_iteration_started / loop_iteration_completed / loop_completed / loop_max_iterations_exceeded
- loop_counter_advanced
- parent_cancelled / parent_rolled_back

注：cancel_taskstop_failed / run_resumed / save 三个事件**不**映射 WORKFLOW_EVENT_TO_STATE，
    不改变 RunState.state（保持调用前的 state 语义不变）。

兜底规则（spec §13 + plan.md 风险 6）：
- 文件不存在 → 视为初始空（events=[]，warnings=[]）
- 整行 JSON 解析失败 → 跳过 + warn（最后一行损坏与中间损坏统一处理；但本函数会在
  warnings 中明确标记是否是最后一行）
- 缺 type 字段 → 跳过 + warn
- node_started 无对应 node_completed → RunState 视为该节点 running（不入 node_outputs）
"""
from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import REPO_ROOT, WorkflowError


# ============================================================================
# 异常：WorkflowError 统一定义在 common.py（跨模块 except 同一性保证）
# ============================================================================


# ============================================================================
# 常量
# ============================================================================

VALID_EVENT_TYPES: set[str] = {
    # workflow 级
    "workflow_started", "workflow_paused", "workflow_completed",
    "workflow_failed", "workflow_cancelled",
    "cancel_requested",
    # cancel 路径专用（不映射 WORKFLOW_EVENT_TO_STATE，保持 cancel_requested 语义）
    "cancel_taskstop_failed",
    # continue 命令恢复标记（不映射 WORKFLOW_EVENT_TO_STATE，保持 running/paused/failed 语义不变）
    "run_resumed",
    # save 命令检查点（不映射 WORKFLOW_EVENT_TO_STATE，不改 state，允许 5 态）
    "save",
    # 节点级
    "node_started", "node_completed", "node_failed", "node_skipped", "node_retried",
    # approval
    "approval_pending", "approval_approved", "approval_rejected",
    # loop
    "loop_iteration_started", "loop_iteration_completed",
    "loop_completed", "loop_max_iterations_exceeded",
    # loop_counters 持久化（workflow_continue loop_continue 路径递增后写入；
    # 仅承载 loop_counters，不映射 WORKFLOW_EVENT_TO_STATE，不改 state）
    "loop_counter_advanced",
    # 父子联动（子侧事件，子 subagent 自身写入）
    "parent_cancelled", "parent_rolled_back",
    # 父侧子结局事件（父 run 观测子 subagent 结果后写入，不映射 WORKFLOW_EVENT_TO_STATE）
    "child_graceful_exited",  # 子 graceful 退出（≤ 30s 内完成 cancel）
    "child_force_killed",     # TaskStop forceful 兜底（30s 超时）
    "child_failed",           # 子 subagent 执行节点时抛异常（映射 spec §6.4 on_subworkflow_failure）
    # D-007 + AC-04a：节点进入"等待 Claude 动作"状态（approval repair 入口）
    # 注意：这 3 类事件不映射 WORKFLOW_EVENT_TO_STATE——副作用依赖 current_node / pending_approval
    # 扁平字典无法表达，必须在 rebuild 中用独立 elif 处理（对抗审阅 P1-1 教训）
    "node_ready",                   # AC-04a：节点就绪，等待 Claude 执行
    "approval_repair_started",      # AC-03b：approval 修复开始（attempt 计数）
    "approval_repair_completed",    # AC-03b：approval 修复完成，回到 approval_pending
}

# 终态 workflow 事件
TERMINAL_WORKFLOW_EVENTS: set[str] = {
    "workflow_completed", "workflow_failed", "workflow_cancelled",
}

# 终态 state 集合（state 字符串，非事件名）；用于新 elif 分支的终态守卫。
TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# F-004 IB-01：node 级"成功类终态"集合——_ready_nodes 依赖判定 / 退化路径
# last_visited 反扫 / finalize DAG 全节点判定四处必须严格同源，禁止局部 set
# 字面量再定义（v6→v7→v8 三轮 drift 复发风险的永久消除点）。
SUCCESS_TERMINAL: frozenset[str] = frozenset({"completed", "skipped"})

# F-009 IB-33：jsonl 读取失败 warning 的统一前缀。read_events / workflow_status.main
# 两处必须严格同源，避免字串硬编码 drift 导致 AC-08（jsonl unreadable → stderr+exit 1）漏检。
WARN_JSONL_UNREADABLE_PREFIX: str = "jsonl 读取失败"

# state 派生表（最近一次 workflow 级事件 → state 字符串）
WORKFLOW_EVENT_TO_STATE: dict[str, str] = {
    "workflow_started": "running",
    "workflow_paused": "paused",
    "workflow_completed": "completed",
    "workflow_failed": "failed",
    "workflow_cancelled": "cancelled",
    "cancel_requested": "cancel_requested",
}


# ============================================================================
# RunState dataclass
# ============================================================================

@dataclass
class RunState:
    """从 run-state.jsonl 重建出的当前状态快照。

    字段：
    - run_id：本 run 的 ID（含前缀 REQ-/RUN-/REL-）
    - workflow_name：workflow_started 中提取的模板名
    - arguments：workflow_started 中的 ARGUMENTS 原文
    - state：派生自最近一次 workflow 级事件；存在 approval_pending 未匹配时优先标 approval_pending
    - current_node：最后启动但未完成 / 失败的节点 id；无则 None
    - node_outputs：{node_id: {"output": str, "state": completed|failed|skipped, "data": dict}}
    - pending_approval：当前 approval_pending 节点 id（state == approval_pending 时设置）
    - last_event_ts：最后一条合法事件的 ts
    - warnings：反扫期间收集的 warn（损坏行 / 残缺对）
    - loop_counters：{node_id: 当前迭代次数}（由 loop_iteration_started/completed 维护）
    """

    run_id: str | None = None
    workflow_name: str | None = None
    arguments: str | None = None
    state: str = "running"
    current_node: str | None = None
    node_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_approval: str | None = None
    last_event_ts: str | None = None
    warnings: list[str] = field(default_factory=list)
    # F-005：循环节点迭代计数器；key = node_id，value = 最近一次 iteration 编号
    loop_counters: dict[str, int] = field(default_factory=dict)

    @classmethod
    def rebuild(
        cls,
        events: list[dict[str, Any]],
        run_id: str | None = None,
        warnings: list[str] | None = None,
    ) -> "RunState":
        """从事件流（按时间序）重建 RunState。"""
        state = cls(run_id=run_id, warnings=list(warnings or []))
        # 跟踪每节点最近一次 started ts（用于检测残缺对）
        node_started_at: dict[str, str | None] = {}
        for evt in events:
            ev_type = evt.get("type")
            if not ev_type:
                continue
            ts = evt.get("ts")
            if ts:
                state.last_event_ts = ts
            data = evt.get("data") or {}
            node_id = evt.get("node_id")

            if ev_type == "workflow_started":
                state.workflow_name = data.get("workflow_name") or state.workflow_name
                state.arguments = data.get("arguments") or state.arguments
                if not state.run_id:
                    state.run_id = evt.get("run_id") or state.run_id
                state.state = "running"
            # 注意：下方 3 个新 elif 必须在 WORKFLOW_EVENT_TO_STATE 分支之前——
            # 这些事件的副作用依赖 current_node / pending_approval 字段，
            # 无法通过扁平字典表达（对抗审阅 P1-1 教训）
            elif ev_type == "node_ready" and node_id and state.state not in TERMINAL_STATES:
                state.current_node = node_id
                state.state = "awaiting_claude_action"
            elif ev_type == "approval_repair_started" and node_id and state.state not in TERMINAL_STATES:
                state.pending_approval = node_id
                state.state = "awaiting_claude_action"
            elif ev_type == "approval_repair_completed" and node_id and state.state not in TERMINAL_STATES:
                # pending_approval 保留（仍在等下一次 approve/reject）
                state.state = "approval_pending"
            elif ev_type in WORKFLOW_EVENT_TO_STATE:
                state.state = WORKFLOW_EVENT_TO_STATE[ev_type]
            elif ev_type == "node_started" and node_id:
                node_started_at[node_id] = ts
                state.current_node = node_id
            elif ev_type == "node_completed" and node_id:
                node_started_at.pop(node_id, None)
                state.node_outputs[node_id] = {
                    "output": data.get("output", ""),
                    "state": "completed",
                    "data": data,
                }
                if state.current_node == node_id:
                    state.current_node = None
                # node_ready 先把 state 置为 awaiting_claude_action；节点完成后回 running
                if state.state == "awaiting_claude_action":
                    state.state = "running"
            elif ev_type == "node_failed" and node_id:
                node_started_at.pop(node_id, None)
                state.node_outputs[node_id] = {
                    "output": data.get("output", ""),
                    "state": "failed",
                    "data": data,
                }
                if state.current_node == node_id:
                    state.current_node = None
            elif ev_type == "node_skipped" and node_id:
                node_started_at.pop(node_id, None)
                state.node_outputs[node_id] = {
                    "output": data.get("output", ""),
                    "state": "skipped",
                    "data": data,
                }
                if state.current_node == node_id:
                    state.current_node = None
            elif ev_type == "node_retried" and node_id:
                # retry：重新计为 started
                node_started_at[node_id] = ts
                state.current_node = node_id
            elif ev_type == "approval_pending" and node_id and state.state not in TERMINAL_STATES:
                state.pending_approval = node_id
                state.state = "approval_pending"
            elif ev_type == "approval_approved" and node_id and state.state not in TERMINAL_STATES:
                if state.pending_approval == node_id:
                    state.pending_approval = None
                # approve 不直接终结 workflow；后续会有 node_completed 把节点关掉
                if state.state == "approval_pending":
                    state.state = "running"
            elif ev_type == "approval_rejected" and node_id and state.state not in TERMINAL_STATES:
                if state.pending_approval == node_id:
                    state.pending_approval = None
                if state.state == "approval_pending":
                    state.state = "running"
            elif ev_type in ("loop_iteration_started", "loop_iteration_completed") and node_id:
                # 更新循环节点的当前迭代编号（F-005：loop_counters 字段）
                # data["iteration"] 由 _dispatch_loop_node 在写事件时设置
                iteration = data.get("iteration")
                if iteration is not None:
                    state.loop_counters[node_id] = int(iteration)
                # Bug-14：interactive loop 由 save_node_result 写 loop_iteration_completed
                # 时把 state 从 awaiting_claude_action 拉回 running，保证 current_node
                # 不变、下一次 /workflow:continue 能再次进入 loop 节点派发
                if (
                    ev_type == "loop_iteration_completed"
                    and state.state == "awaiting_claude_action"
                ):
                    state.state = "running"
            elif ev_type == "loop_counter_advanced" and node_id:
                # workflow_continue loop_continue 路径递增后写入：data.new_value 为
                # 递增后的"下一轮迭代编号"。crash 后 rebuild 必须看到此事件才能正确
                # 还原 loop_counters，否则 dispatcher 会用旧 iteration 重派同一轮。
                new_value = data.get("new_value")
                if new_value is not None:
                    state.loop_counters[node_id] = int(new_value)

        # 残缺对处理（spec §13）：node_started 无对应 node_completed → 标 warn
        for node_id, started_ts in node_started_at.items():
            state.warnings.append(
                f"节点 {node_id} 有 node_started 但无 node_completed（残缺对，"
                f"重启时该节点视为 running 重跑）；ts={started_ts}"
            )
        return state


# ============================================================================
# jsonl 读取
# ============================================================================

def read_events(jsonl_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """逐行解析 jsonl，返回 (events, warnings)。

    - 文件不存在 → ([], [])
    - 整行 JSON 解析失败 → 跳过 + warn（最后一行额外标记 spec §13）
    - 缺 type / type 不在白名单 → 跳过 + warn（保留兼容）
    """
    events: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not jsonl_path.exists():
        return events, warnings

    try:
        with jsonl_path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        warnings.append(f"{WARN_JSONL_UNREADABLE_PREFIX}: {exc}")
        return events, warnings

    last_idx = len(lines) - 1
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            evt = json.loads(stripped)
        except json.JSONDecodeError as exc:
            tag = "（最后一行）" if idx == last_idx else ""
            warnings.append(
                f"jsonl 第 {idx + 1} 行 JSON 解析失败{tag}: {exc.msg}"
            )
            continue
        if not isinstance(evt, dict):
            warnings.append(f"jsonl 第 {idx + 1} 行不是 object，跳过")
            continue
        ev_type = evt.get("type")
        if not ev_type:
            warnings.append(f"jsonl 第 {idx + 1} 行缺 type 字段，跳过")
            continue
        if ev_type not in VALID_EVENT_TYPES:
            warnings.append(f"jsonl 第 {idx + 1} 行 type={ev_type!r} 不在白名单，跳过")
            continue
        events.append(evt)

    return events, warnings


# ============================================================================
# jsonl 写入（fcntl.LOCK_EX + O_APPEND）
# ============================================================================

def append_event(jsonl_path: Path, event: dict[str, Any]) -> None:
    """原子追加一条事件到 jsonl。

    实现：O_APPEND 保证 write 是原子的；LOCK_EX 保证多进程串行。
    自动补 ts 字段（如果调用方未传）。
    """
    if not isinstance(event, dict):
        raise WorkflowError("event 必须是 dict")
    ev_type = event.get("type")
    if not ev_type:
        raise WorkflowError("event 缺少 type 字段")
    if ev_type not in VALID_EVENT_TYPES:
        raise WorkflowError(f"event type {ev_type!r} 不在白名单")
    if "ts" not in event:
        event["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = json.dumps(event, ensure_ascii=False) + "\n"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(
            str(jsonl_path),
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o644,
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                os.write(fd, payload.encode("utf-8"))
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    except OSError as exc:
        raise WorkflowError(f"写 jsonl 失败: {exc}") from exc


# ============================================================================
# D-007 双路径 _resolve_run_dir
# ============================================================================

def _resolve_run_dir(run_id: str, repo_root: Path | None = None) -> Path:
    """D-007 双路径解析：先 stat `requirements/<run_id>/`，不存在则 stat `runs/<run_id>/`。

    都不存在抛 `WorkflowError`。3 月兼容期结束后只需删第一段即可。

    `repo_root` 默认 = REPO_ROOT；测试可注入 tmp_path 作为根。
    """
    if not run_id or not isinstance(run_id, str):
        raise WorkflowError(f"run_id 非法: {run_id!r}")
    root = repo_root or REPO_ROOT

    legacy = root / "requirements" / run_id
    if legacy.is_dir():
        return legacy
    new_path = root / "runs" / run_id
    if new_path.is_dir():
        return new_path
    raise WorkflowError(
        f"run_id {run_id!r} 不存在：requirements/{run_id}/ 与 runs/{run_id}/ 都未找到"
    )


# ============================================================================
# 一站式：rebuild 主入口（包装 read_events + RunState.rebuild）
# ============================================================================

def rebuild_run_state(
    jsonl_path: Path,
    run_id: str | None = None,
) -> RunState:
    """读 jsonl + 反扫重建 RunState 的便捷入口。

    若 jsonl 不存在则返回初始 RunState（state=running, 无 events）。
    """
    events, warnings = read_events(jsonl_path)
    state = RunState.rebuild(events, run_id=run_id, warnings=warnings)
    return state
