"""workflow runtime DAG 调度器（B4a IB-13 拆出，原属 workflow_continue.py）。

职责：DAG 拓扑推进 / ready 节点选择 / 终态判定 / 末节点 finalize。
不直接 IO；事件写入由调用方负责。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import (  # noqa: E402
    SUCCESS_TERMINAL,
    RunState,
    append_event,
    read_events,
)


def _next_node(
    current_node: dict,
    hint: str | None,
) -> str | None:
    """确定下一个节点 ID。

    优先级：
      1. hint 非 None 时返回 hint（显式覆盖，e.g. on_reject）
      2. 否则读 current_node.next（若存在）
      3. 否则返回 None（拓扑末尾）

    注：F-008 接入显式跳转（on_failure / on_skip）时，由调用方计算 hint 后传入；
    node_map 不由本函数持有，保持职责单一。
    """
    if hint is not None:
        return hint
    return current_node.get("next")


# F-004 IB-01：NON_READY_STATES 与 SUCCESS_TERMINAL 同源——SUCCESS_TERMINAL 从
# run_state 模块 import（永久消除 v6→v7→v8 三轮 drift 复发风险）。
_NON_READY_STATES: frozenset[str] = SUCCESS_TERMINAL | frozenset(
    {"failed", "running", "awaiting_claude_action"}
)


def _ready_nodes(
    run_state: RunState,
    workflow: dict,
) -> list[str]:
    """计算当前 ready 节点 ID 列表（D-013：每次全量重算）。

    算法（detail-design §3.3.5；v8 REV-007 P1 修订 — SUCCESS_TERMINAL 贯穿）：
      1. 取 workflow.nodes 全集
      2. 对每个候选节点：
         - 已在任一非 ready 终态 / 派发中（SUCCESS_TERMINAL ∪ {failed, running,
           awaiting_claude_action}）→ 跳过
         - 所有 depends_on 节点的 state ∈ SUCCESS_TERMINAL（含 skipped）→ 加入 ready
      3. 按 yaml 出现顺序返回（D-006 串行派发的事件顺序确定）

    Returns:
        list[str]: 0~N 个 ready node id（空 = 拓扑跑完 或 全部阻塞）

    Time: O(V × avg_deps)，50 节点 × 5 deps ≈ 250 set 查询 < 5ms。
    """
    success_done = {
        nid
        for nid, entry in run_state.node_outputs.items()
        if (entry or {}).get("state") in SUCCESS_TERMINAL
    }
    ready: list[str] = []
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if not nid or nid == run_state.current_node:
            continue
        existing_state = (run_state.node_outputs.get(nid) or {}).get("state")
        if existing_state in _NON_READY_STATES:
            continue
        deps = node.get("depends_on") or []
        if all(d in success_done for d in deps):
            ready.append(nid)
    return ready


def _dag_next(run_state: RunState, workflow: dict) -> str | None:
    """DAG 分支（depends_on_explicit=True）：取 `_ready_nodes`[0] 串行派发。

    F-CR-003 拆分自 `_select_next_dispatch_target`，单一职责让 CCN ≤ 2。

    Returns:
      str | None: 下一个待派发节点 ID；若无 ready 节点（拓扑跑完或全部阻塞）返回 None
    """
    ready = _ready_nodes(run_state, workflow)
    return ready[0] if ready else None


def _legacy_first_node(workflow: dict) -> str | None:
    """退化路径分支 a：真新 run → 返回 yaml 首节点 id（首个含 id 的节点）。

    F-CR-008 子拆：单一职责让 CCN ≤ 4、嵌套深度 ≤ 2。

    Returns:
      str | None: workflow.nodes 中第一个含 id 的节点 ID；yaml 无节点时返回 None
    """
    for node in workflow.get("nodes") or []:
        if isinstance(node, dict) and node.get("id"):
            return node["id"]
    return None


def _legacy_resume_from_last_visited(
    run_state: RunState,
    node_map: dict[str, dict],
) -> str | None:
    """退化路径分支 b：有 SUCCESS_TERMINAL 节点但 current_node is None →
    反扫 node_outputs 取最后一个进入 SUCCESS_TERMINAL 的节点，走
    `_next_node(last_visited, None)` 推进。

    Python 3.7+ dict 保留插入序；rebuild 按事件流逐条 setattr，
    循环末位赋值即末位 visited 节点。

    F-CR-008 子拆 + F-CR-007 WARN 守卫：yaml 已无 last_visited 节点（迁移 / rename
    / 删节点）—— spec 严重事件，必须 WARN 暴露排查线索（对齐 _handle_retry:184-188 风格）。

    Returns:
      str | None: last_visited 节点的 next 节点 ID；无 SUCCESS_TERMINAL 节点或 yaml 缺失时返回 None
    """
    last_visited_id: str | None = None
    for nid, out in run_state.node_outputs.items():
        if (out or {}).get("state") in SUCCESS_TERMINAL:
            last_visited_id = nid
    if last_visited_id is None:
        return None
    last_node = node_map.get(last_visited_id)
    if last_node is None:
        # F-CR-007：yaml 已无该节点，必须 WARN 暴露排查线索（与 _finalize 同款 WARN）。
        print(
            f"WARN: jsonl 提及节点 {last_visited_id!r} 但 yaml node_map 缺失，"
            f"yaml 可能与 run 历史不一致，无法推进退化路径",
            file=sys.stderr,
        )
        return None
    return _next_node(last_node, None)


def _legacy_bootstrap_or_resume(
    run_state: RunState,
    workflow: dict,
    node_map: dict[str, dict],
) -> str | None:
    """退化路径（depends_on_explicit=False）current_node is None 的双分支分流。

    F-CR-003 + F-CR-008 拆分：本函数仅做 any_visited 判定 + 分流，CCN ≤ 4；
    细节下沉到 `_legacy_first_node`（分支 a）/ `_legacy_resume_from_last_visited`
    （分支 b）。

    双分支（v6 P1-2 + v7 REV-006 P1 + v8 P1 修订）：
      (a) 无任何 SUCCESS_TERMINAL 节点（真新 run）→ yaml 首节点 nodes[0].id
      (b) 有 SUCCESS_TERMINAL 节点 → 反扫 node_outputs 取最后 SUCCESS_TERMINAL
          节点，走 `_next_node(last_visited, None)` 推进。
      关键反向：on_failure=skip 让 N1 skipped 后，N1 不会被错误重新派发。

    Returns:
      str | None: 下一个待派发节点 ID；拓扑末尾或无法推进时返回 None
    """
    any_visited = any(
        (out or {}).get("state") in SUCCESS_TERMINAL
        for out in run_state.node_outputs.values()
    )
    if not any_visited:
        return _legacy_first_node(workflow)
    return _legacy_resume_from_last_visited(run_state, node_map)


def _legacy_advance(
    run_state: RunState,
    node_map: dict[str, dict],
) -> str | None:
    """退化路径 current_node 非空时的单链推进（F-CR-003 拆分）。

    F-CR-007 同模式扫描：node_map.get 返 None 时（yaml 改名 / 删节点 / 迁移）必须
    WARN 暴露排查线索，禁止静默 return（对齐 _legacy_resume_from_last_visited 与
    _finalize_after_rebuild_if_last_topology_node 同款 WARN）。

    Returns:
      str | None: current_node 的 next 节点 ID；current_node 在 yaml 缺失或已是末尾时返回 None
    """
    cur_node = node_map.get(run_state.current_node)
    if cur_node is None:
        print(
            f"WARN: current_node {run_state.current_node!r} 在 yaml node_map 缺失，"
            f"yaml 可能与 run 历史不一致，无法推进退化路径",
            file=sys.stderr,
        )
        return None
    return _next_node(cur_node, None)


def _select_next_dispatch_target(
    run_state: RunState,
    workflow: dict,
    node_map: dict[str, dict],
) -> str | None:
    """选择下一个待派发节点 id（detail-design §3.6.2）。

    F-CR-003 重构：主函数只做 DAG / 退化分流，CCN ≤ 3；细节下沉到三 helper：
      - `_dag_next`：DAG 串行派发（depends_on_explicit=True）
      - `_legacy_bootstrap_or_resume`：退化路径 current_node is None 双分支 a/b
      - `_legacy_advance`：退化路径 current_node 非空的单链推进
    """
    if workflow.get("depends_on_explicit"):
        return _dag_next(run_state, workflow)

    if run_state.current_node is None:
        return _legacy_bootstrap_or_resume(run_state, workflow, node_map)

    return _legacy_advance(run_state, node_map)


def _is_dag_topology_done(run_state: RunState, workflow: dict) -> bool:
    """DAG 路径拓扑跑完判定（F-CR-004 抽出）。

    复合判定（v6 P1-3 + v8 P1 修订）：
      - 全节点 state ∈ SUCCESS_TERMINAL
      - 不存在 failed 节点（has_failed 即放弃 finalize，由 _route_outcome 失败矩阵接管）
      - _ready_nodes 空（无更多可派发）

    Returns:
      bool: True 当且仅当所有节点 state ∈ SUCCESS_TERMINAL 且无 failed 且无更多 ready；否则 False
    """
    node_states = {
        n["id"]: (run_state.node_outputs.get(n["id"]) or {}).get("state")
        for n in workflow.get("nodes") or []
        if isinstance(n, dict) and n.get("id")
    }
    has_failed = any(s == "failed" for s in node_states.values())
    all_success_terminal = all(
        s in SUCCESS_TERMINAL for s in node_states.values()
    )
    no_more_ready = len(_ready_nodes(run_state, workflow)) == 0
    return all_success_terminal and no_more_ready and not has_failed


def _is_legacy_topology_done(last_node: dict) -> bool:
    """单链路径拓扑跑完判定（F-CR-004 抽出）。

    单链末节点 = `_next_node(last_node, None) is None`。

    Returns:
      bool: True 当且仅当 last_node 无后继（next 字段缺失或为 None）；否则 False
    """
    return _next_node(last_node, None) is None


def _scan_last_visited(
    events: list[dict],
    node_map: dict[str, dict],
) -> tuple[str | None, bool]:
    """从 events 反扫最后 visited 节点 ID，返回 (last_node_id_or_None, emitted_warn)。

    用于 _finalize_after_rebuild_if_last_topology_node 的失败路径反扫；从主函数抽出
    使主函数 CCN ≈ 6，给后续重构留余量。

    v8 REV-007 P1：候选集含 node_completed 与 node_skipped，不含 node_failed——
    failed 节点由失败矩阵决定 workflow_failed/retry/skip，finalize 不接管。

    F-CR-007：yaml 已无该节点（迁移 / rename / 删节点）时必须 WARN 暴露排查线索，
    禁止静默 return None（对齐 _handle_retry:184-188 风格）。

    Returns:
      tuple[str | None, bool]: (last_node_id_or_None, True if emitted WARN else False)
    """
    last_visited_id: str | None = None
    for evt in events:
        if evt.get("type") in ("node_completed", "node_skipped"):
            last_visited_id = evt.get("node_id")
    if not last_visited_id:
        return None, False
    if node_map.get(last_visited_id) is None:
        print(
            f"WARN: jsonl 提及节点 {last_visited_id!r} 但 yaml node_map 缺失，"
            f"yaml 可能与 run 历史不一致，跳过 finalize 补救",
            file=sys.stderr,
        )
        return None, True
    return last_visited_id, False


def _finalize_after_rebuild_if_last_topology_node(
    run_state: RunState,
    workflow: dict,
    node_map: dict,
    jsonl_path: Path,
) -> bool:
    """main_loop 入口的回填补救（detail-design §3.6.3；F-004 双分支 + v8 P1 修订）。

    背景（round-5 P2）：
      `_advance_after_completed` 已把 current_node 置 None 但
      `_finalize_if_topology_done` append_event 之前 crash → 重启时 rebuild 出
      current_node=None / state=running，main_loop 因 while 失败立刻退出，run 卡死。

    本 helper 在 main_loop 进入循环前补救：若 current_node is None ∧ state==running
    ∧ 拓扑跑完（按下方双分支判定）→ 补写 workflow_completed。

    判定双分支（AC-01 / R-T01）：
      - depends_on_explicit=False（单链）→ `_is_legacy_topology_done`
      - depends_on_explicit=True （DAG）→ `_is_dag_topology_done`
      详见两 helper 的 docstring。

    F-CR-004 重构：判定子句下沉到 _is_dag_topology_done / _is_legacy_topology_done，
    F-CR2-005 重构：WARN-and-scan 块抽为 _scan_last_visited，本函数 CCN ≈ 6。

    返回：True 表示已补写 workflow_completed（调用方应跳过 while）；False 表示无需补救。
    """
    if run_state.current_node is not None or run_state.state != "running":
        return False
    # F-CR-011：与 _handle_retry:184-188 风格对齐，warnings 非空打 WARN 暴露 jsonl 损坏行。
    # 旧版 `events, _ = read_events(jsonl_path)` 解包后丢弃 warnings，反扫漏算无任何告警。
    events, warnings = read_events(jsonl_path)
    if warnings:
        print(
            f"WARN: finalize 读 jsonl 含 {len(warnings)} 行损坏，"
            f"last_visited 反扫可能漏算: {warnings}",
            file=sys.stderr,
        )
    last_visited_id, _ = _scan_last_visited(events, node_map)
    if not last_visited_id:
        return False
    last_node = node_map[last_visited_id]  # _scan_last_visited 已确认 key 存在

    if workflow.get("depends_on_explicit"):
        is_last = _is_dag_topology_done(run_state, workflow)
    else:
        is_last = _is_legacy_topology_done(last_node)

    if is_last:
        append_event(jsonl_path, {"type": "workflow_completed", "data": {}})
        run_state.state = "completed"
        return True
    return False


def _finalize_if_topology_done(
    run_state: RunState,
    jsonl_path: Path,
    workflow: dict | None = None,
) -> bool:
    """末节点 outcome=completed/loop_done/sub_workflow_done 推进后，若 next_id is None
    说明拓扑跑完——写 workflow_completed 事件 + 翻 state=completed，返回 True 让调用方 break。

    P1-c v2（codex round-4 2026-05-12）修订：
      旧实现把 workflow_completed 写在 _main_loop 退出后并以 `current_node is None` 判断完成，
      存在 crash 窗口——dispatcher 已写 node_completed 但 _advance_after_completed 没跑（无
      advance 事件），重启后 RunState.rebuild 在 node_completed 分支把 current_node 置 None
      （rebuild 凭"current_node == node_id 则置 None"判定），与"自然跑完"无法区分，导致
      workflow_completed 被误写、剩余节点被静默截断。
      新实现把 workflow_completed 的写入下沉到 _route_outcome——只有真的从一次成功的
      completed/loop_done/sub_workflow_done 路径推进且无 next 时才写，crash 路径不触发。

    返回值：True 表示已写 workflow_completed（调用方应 break）；False 表示还有后继节点。
    """
    if run_state.current_node is None:
        # IB-09：DAG 路径补形式正确性 assert，防后续重构破坏不变量。
        # happy path 下 _advance_after_completed + _handle_skip/abort 早返保证
        # current_node=None ⟺ 全节点 SUCCESS_TERMINAL，assert 在 happy path 不触发；
        # 若未来新增绕过路径，assert 第一时间暴露。
        if workflow is not None and workflow.get("depends_on_explicit"):
            assert _is_dag_topology_done(run_state, workflow), (
                f"_finalize_if_topology_done DAG 分支：current_node=None 但 topology 未全 SUCCESS_TERMINAL，"
                f"可能由失败处理路径绕过 _handle_skip/abort 早返触发；请检查最新 advance 路径"
            )
        append_event(jsonl_path, {"type": "workflow_completed", "data": {}})
        run_state.state = "completed"
        return True
    return False
