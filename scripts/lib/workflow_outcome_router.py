"""workflow 节点 outcome 路由（B4a IB-13 拆出，原属 workflow_continue.py）。

职责：把 dispatch_node 返回的 DispatchResult.outcome 转为 RunState 状态推进 + 事件追加。
不直接判定 ready 节点；ready 由 workflow_scheduler 负责。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import (  # noqa: E402
    RunState,
    append_event,
    read_events,
)
from workflow_scheduler import (  # noqa: E402
    _finalize_if_topology_done,
    _next_node,
    _select_next_dispatch_target,
)


def _handle_retry(
    run_state: RunState,
    node: dict,
    jsonl_path: Path,
    error: str | None,
) -> bool:
    """retry 策略：统计已失败次数，未达上限则静默等待下次续跑，超出则升级为 abort。

    参照 workflow_dispatcher.py:185-200 _dispatch_skill_node 风格编写。

    返回值：False（调用方应 break，等待下次 continue 或因 abort 终结）。

    注意：dispatcher 已写 node_failed 事件，此处不重复写；
         超上限时才追加 workflow_failed 事件。
    """
    node_id = node["id"]
    # F-5：保留 warnings，暴露 jsonl 损坏行（损坏行会导致 fail_count 偏低）
    events, warnings = read_events(jsonl_path)
    if warnings:
        print(
            f"WARN: jsonl 含 {len(warnings)} 行损坏，retry 计数可能偏低: {warnings}",
            file=sys.stderr,
        )
    # node_failed 事件由 dispatcher 写入，node_id 在事件顶层（与 run_state.rebuild 读法一致）
    fail_count = sum(
        1 for evt in events
        if evt.get("type") == "node_failed" and evt.get("node_id") == node_id
    )
    max_retries: int = node.get("max_retries", 3)

    if fail_count < max_retries:
        # 未到重试上限：写 node_retried 让 rebuild 把 current_node 重新设回该节点
        # （否则 node_failed 已把 current_node 清成 None；下次 continue 重启会触发
        # _select_next_dispatch_target 反扫，因失败节点在 _NON_READY_STATES 里被
        # 永久过滤，最终 next_id=None 命中 _finalize_if_topology_done 的 assert）。
        append_event(
            jsonl_path,
            {
                "type": "node_retried",
                "node_id": node_id,
                "data": {
                    "fail_count": fail_count,
                    "max_retries": max_retries,
                    "error": error or "",
                },
            },
        )
        print(
            f"INFO: 节点 {node_id!r} 失败（第 {fail_count} 次），"
            f"将重试（max_retries={max_retries}）",
            file=sys.stderr,
        )
        return False

    # 超出重试上限：升级为 abort，写 workflow_failed 事件
    print(
        f"WARN: 节点 {node_id!r} 重试次数已达上限 {max_retries}，升级为 abort",
        file=sys.stderr,
    )
    append_event(
        jsonl_path,
        {
            "type": "workflow_failed",
            "data": {
                "node_id": node_id,
                "error": error or f"节点 {node_id!r} 超出最大重试次数 {max_retries}",
                "reason": "retry_exhausted",
            },
        },
    )
    run_state.state = "failed"
    return False


def _handle_skip(
    run_state: RunState,
    node: dict,
    jsonl_path: Path,
    error: str | None,
    workflow: dict,
    node_map: dict[str, dict],
) -> bool:
    """skip 策略：写 node_skipped 事件，推进 current_node，返回 True（主循环继续）。

    参照 workflow_dispatcher.py:185-200 _dispatch_skill_node 风格编写。

    返回值：True（调用方应继续循环，推进到下一节点）。

    注意：
      - node_skipped.data.reason 遵循 spec §2.1，记录实际错误信息。
      - depends_on_explicit=True（DAG）走 _select_next_dispatch_target；
        False（单链）保持 _next_node。与 _advance_after_completed 同源（F-CR-001），
        修复 DAG yaml 节点无 next 字段时 skip 路径无法推进的 bug。
    """
    node_id = node["id"]
    # node_skipped 事件：node_id 在顶层（与 run_state.rebuild 读法一致）
    append_event(
        jsonl_path,
        {
            "type": "node_skipped",
            "node_id": node_id,
            "data": {
                "reason": error or "on_failure=skip 但无具体错误",
            },
        },
    )
    # 更新 node_outputs（状态=skipped）
    run_state.node_outputs[node_id] = {
        "output": None,
        "state": "skipped",
        "data": {"reason": error or "on_failure=skip 但无具体错误"},
    }
    if workflow.get("depends_on_explicit"):
        # DAG 路径：先清 current_node（已记 skipped 入 node_outputs，
        # 让 _ready_nodes 不把它当 current 跳过），再走 scheduler 取下个 ready。
        run_state.current_node = None
        next_id = _select_next_dispatch_target(run_state, workflow, node_map)
    else:
        next_id = _next_node(node, None)
    run_state.current_node = next_id
    print(
        f"INFO: 节点 {node_id!r} 跳过（on_failure=skip），推进到 {next_id!r}",
        file=sys.stderr,
    )
    return True


def _handle_abort(
    run_state: RunState,
    node: dict,
    jsonl_path: Path,
    error: str | None,
    on_failure: str,
) -> bool:
    """abort 策略（或未知策略降级为 abort）：写 workflow_failed 事件，终结 run。

    参照 workflow_dispatcher.py:185-200 _dispatch_skill_node 风格编写。

    返回值：False（调用方应 break，run 终结）。

    注意：未知策略先打 WARN，再走 abort 路径。
    """
    node_id = node["id"]
    if on_failure != "abort":
        print(
            f"WARN: 未知 on_failure 策略 {on_failure!r}，降级为 abort",
            file=sys.stderr,
        )
    append_event(
        jsonl_path,
        {
            "type": "workflow_failed",
            "data": {
                "node_id": node_id,
                "error": error or f"节点 {node_id!r} 执行失败（abort）",
                "reason": "node_failed",
            },
        },
    )
    run_state.state = "failed"
    return False


def _handle_failure(
    run_state: RunState,
    node: dict,
    on_failure: str,
    jsonl_path: Path,
    error: str | None,
    workflow: dict,
    node_map: dict[str, dict],
) -> bool:
    """按 on_failure 策略路由到对应助手函数。

    返回值语义：
      True  → 调用方继续循环（_handle_skip 成功推进）
      False → 调用方 break（_handle_retry 等待下次 / _handle_abort 终结 workflow）

    注意：
      - dispatcher 已写 node_failed 事件，本函数不重复写；
        仅通过助手函数写 node_skipped / workflow_failed 两类新事件。
      - workflow + node_map 透传给 _handle_skip，让 DAG 路径走 scheduler 推进。
    """
    if on_failure == "retry":
        return _handle_retry(run_state, node, jsonl_path, error)
    elif on_failure == "skip":
        return _handle_skip(run_state, node, jsonl_path, error, workflow, node_map)
    else:
        return _handle_abort(run_state, node, jsonl_path, error, on_failure)


def _advance_after_completed(
    run_state: RunState,
    node: dict,
    result: "DispatchResult",  # type: ignore[name-defined]  # noqa: F821
    workflow: dict,
    node_map: dict[str, dict],
) -> None:
    """completed / loop_done / sub_workflow_done 场景的公用推进逻辑。

    F-CR-001 修复：按 `workflow["depends_on_explicit"]` 分流，杜绝 DAG yaml 节点无
    `next` 字段时 _next_node 必返 None → DAG workflow 仅跑首节点即终止的 bug。

      - True（DAG）：先更新 node_outputs 让 _ready_nodes 看到该节点 SUCCESS_TERMINAL，
                     再调 `_select_next_dispatch_target` 取下一个 ready 节点。
      - False（单链退化）：保持 `_next_node(node, result.next_node_hint)` 旧语义。
        next_node_hint 仅在单链路径有意义（on_reject 显式跳转）；DAG 路径走 ready
        计算，不读 hint（DAG 的跳转应靠 depends_on 表达，不靠 hint 跳跃）。

    - 更新 node_outputs（outcome=completed 时记录 output；其余场景 output 可能为 None）
    - 推进 current_node：按 depends_on_explicit 分流
    """
    node_id = node["id"]
    run_state.node_outputs[node_id] = {
        "output": result.output,
        "state": "completed",
        "data": {"output": result.output},
    }
    if workflow.get("depends_on_explicit"):
        # DAG 路径：先把当前节点置于 SUCCESS_TERMINAL（上面已写 node_outputs），
        # 再让 _select_next_dispatch_target 全量重算 ready，取 [0] 串行派发。
        # 为让 _ready_nodes 不把当前节点当作"current_node"跳过，先清 current_node。
        run_state.current_node = None
        next_id = _select_next_dispatch_target(run_state, workflow, node_map)
    else:
        next_id = _next_node(node, result.next_node_hint)
    run_state.current_node = next_id


def _route_outcome(
    run_state: RunState,
    node: dict,
    result: "DispatchResult",  # type: ignore[name-defined]  # noqa: F821
    jsonl_path: Path,
    workflow: dict,
    node_map: dict[str, dict],
) -> bool:
    """将 dispatch_node 返回的 outcome 路由到对应处理逻辑。

    返回值：True=继续循环（while 条件仍满足），False=立即 break。

    路由表（dispatcher 已写的事件不在此重复）：
      completed          → _advance_after_completed（推进 current_node）→ True
      loop_continue      → loop_counters += 1 + 写 loop_counter_advanced 事件，
                           current_node 不变 → True
      loop_done          → _advance_after_completed（推进 current_node）→ True
      sub_workflow_done  → _advance_after_completed（推进 current_node）→ True
      approval_pending   → state=approval_pending → False
      sub_workflow_pending → state 保持 running → False（等待子 workflow 回调）
      awaiting_claude_action → state=awaiting_claude_action → False
                            （F-002/F-013：dispatcher 已写 node_ready；
                             等 Claude 调 save_node_result.py 推进）
      failed             → _handle_failure 返回值（retry/skip/abort 决定）
      未知 outcome       → 写 workflow_failed，state=failed → False
    """
    outcome = result.outcome
    node_id = node["id"]

    if outcome == "completed":
        # node_completed 事件已由 dispatcher 写入；仅更新 RunState + 推进指针
        # F-CR-001：传入 workflow + node_map 让 advance 按 depends_on_explicit 分流
        _advance_after_completed(run_state, node, result, workflow, node_map)
        if _finalize_if_topology_done(run_state, jsonl_path, workflow):
            return False
        return True

    elif outcome == "loop_continue":
        # 循环节点继续迭代：递增计数器并写 loop_counter_advanced 事件。
        # 仅内存 +1 在 crash 后会被 rebuild 漏读，导致 dispatcher 用旧 iteration 重派同一轮。
        new_value = run_state.loop_counters.get(node_id, 0) + 1
        run_state.loop_counters[node_id] = new_value
        append_event(
            jsonl_path,
            {
                "type": "loop_counter_advanced",
                "node_id": node_id,
                "data": {"new_value": new_value},
            },
        )
        return True

    elif outcome in ("loop_done", "sub_workflow_done"):
        # 循环/子 workflow 完成：推进到下一节点
        # F-CR-001：与 completed 分支同步传 workflow + node_map
        _advance_after_completed(run_state, node, result, workflow, node_map)
        if _finalize_if_topology_done(run_state, jsonl_path, workflow):
            return False
        return True

    elif outcome == "approval_pending":
        # 派发器已写 approval_pending 事件；main loop 仅设置状态并退出
        run_state.state = "approval_pending"
        return False

    elif outcome == "sub_workflow_pending":
        # 子 workflow 已发起但尚未完成；state 保持 running，等待回调续跑
        return False

    elif outcome == "awaiting_claude_action":
        # F-002/F-013: dispatcher 已写 node_ready 事件（含 external_action_contract），
        # main loop 在此暂停，等待 Claude Code 调 save_node_result.py --kind=skill_result 推进。
        # rebuild 会从 node_ready 事件恢复同 state；此处仅更新 in-memory state 让 while 退出。
        run_state.state = "awaiting_claude_action"
        return False

    elif outcome == "failed":
        # 按 on_failure 策略路由：retry / skip / abort
        on_failure: str = node.get("on_failure", "retry")
        return _handle_failure(
            run_state, node, on_failure, jsonl_path, result.error, workflow, node_map
        )

    else:
        # 未知 outcome（防御性兜底）：写 workflow_failed，避免 state 留 running 引发静默死循环
        append_event(
            jsonl_path,
            {
                "type": "workflow_failed",
                "data": {
                    "node_id": node_id,
                    "error": f"未知 outcome: {outcome!r}",
                },
            },
        )
        run_state.state = "failed"
        return False
