"""F-004 · `_ready_nodes` + `_select_next_dispatch_target` + `_finalize_after_rebuild`
单元测试（详细设计 §3.3.5 / §3.6.2 / §3.6.3 / ADR D-006 / D-013）。

覆盖 acceptance：
  _ready_nodes：
    - 首次调用（无 success_terminal）→ 返回入度=0 节点集（按 yaml 出现顺序）
    - 依赖满足判定用 SUCCESS_TERMINAL（含 skipped）
    - v8 P1 反向回归 a：N1 skipped 不阻断下游 N2

  _select_next_dispatch_target：
    - explicit=True → _ready_nodes[0]
    - explicit=False 分支 a：真新 run 返 yaml 首节点
    - explicit=False 分支 b：续跑反扫 last_visited(completed) → _next_node
    - explicit=False 分支 b：末节点反扫 → None
    - explicit=False skipped 反向回归（v7 REV-006 P1 闭环）：last_visited=N1(skipped)
      → 返 N2；关键反向：N1 不被重派

  _finalize_after_rebuild_if_last_topology_node：
    - DAG 路径：全节点 ∈ SUCCESS_TERMINAL ∧ 无 failed ∧ _ready_nodes 空 → 补 workflow_completed
    - DAG 路径含 failed → 返 False（不写 workflow_completed）
    - v8 P1 反向回归 b：单链 + node_skipped(N3 末节点) → finalize 补 workflow_completed
    - 多 sink DAG：A 单独 completed → 返 False；A+B 都 completed → 返 True
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import RunState  # noqa: E402
from workflow_continue import (  # noqa: E402
    _finalize_after_rebuild_if_last_topology_node,
    _ready_nodes,
    _select_next_dispatch_target,
)


# ============================================================================
# helper：构造 workflow dict / node_outputs / jsonl
# ============================================================================

def _wf_dag_line() -> dict:
    """构造退化（单链）yaml dict：N1 -> N2 -> N3（用 next 而非 depends_on）。

    设 depends_on_explicit=False 模拟 legacy yaml（首节点 depends_on=[] 不算隐式
    但其余节点也都缺省，此处用 next 替代 depends_on 模拟旧版）。
    """
    return {
        "depends_on_explicit": False,
        "nodes": [
            {"id": "N1", "bash": "echo 1", "next": "N2", "depends_on": []},
            {"id": "N2", "bash": "echo 2", "next": "N3", "depends_on": ["N1"]},
            {"id": "N3", "bash": "echo 3", "depends_on": ["N2"]},
        ],
    }


def _wf_dag_explicit() -> dict:
    """构造 DAG yaml dict：
        N1（入度 0）
        ├── N2 (depends_on=[N1])
        └── N3 (depends_on=[N1])
            N4 (depends_on=[N2, N3])
    depends_on_explicit=True。
    """
    return {
        "depends_on_explicit": True,
        "nodes": [
            {"id": "N1", "bash": "echo 1", "depends_on": []},
            {"id": "N2", "bash": "echo 2", "depends_on": ["N1"]},
            {"id": "N3", "bash": "echo 3", "depends_on": ["N1"]},
            {"id": "N4", "bash": "echo 4", "depends_on": ["N2", "N3"]},
        ],
    }


def _wf_two_sinks() -> dict:
    """多 sink DAG：N1 → A, N1 → B（A 与 B 都是终态 sink，无后续节点）。"""
    return {
        "depends_on_explicit": True,
        "nodes": [
            {"id": "N1", "bash": "echo 1", "depends_on": []},
            {"id": "A", "bash": "echo a", "depends_on": ["N1"]},
            {"id": "B", "bash": "echo b", "depends_on": ["N1"]},
        ],
    }


def _node_map(wf: dict) -> dict[str, dict]:
    return {n["id"]: n for n in wf["nodes"]}


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for evt in events:
            evt.setdefault("ts", "2026-05-14T10:00:00Z")
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")


# ============================================================================
# _ready_nodes 单测
# ============================================================================

def test_ready_nodes_首次调用_返回入度0节点():
    """AC：首次调用（success_terminal=∅）→ 返回入度=0 节点（按 yaml 出现顺序）。"""
    wf = _wf_dag_explicit()
    state = RunState(run_id="R1", state="running")
    ready = _ready_nodes(state, wf)
    assert ready == ["N1"], f"期望 ['N1']，实际 {ready!r}"


def test_ready_nodes_完成入口节点_返回同层多节点():
    """AC：N1 completed 后 → _ready_nodes 应按 yaml 出现顺序返回 [N2, N3]（D-006 串行）。"""
    wf = _wf_dag_explicit()
    state = RunState(
        run_id="R2",
        state="running",
        node_outputs={"N1": {"state": "completed", "output": "ok", "data": {}}},
    )
    ready = _ready_nodes(state, wf)
    assert ready == ["N2", "N3"], f"期望 ['N2','N3']，实际 {ready!r}"


def test_ready_nodes_依赖判定含skipped_v8P1反向回归():
    """v8 P1 反向回归 a：N1 → N2（N2.depends_on=[N1]），node_skipped(N1)
    后 _ready_nodes 返回 ['N2']——杜绝 skipped 节点下游永久阻塞。"""
    wf = {
        "depends_on_explicit": True,
        "nodes": [
            {"id": "N1", "bash": "echo 1", "depends_on": []},
            {"id": "N2", "bash": "echo 2", "depends_on": ["N1"]},
        ],
    }
    state = RunState(
        run_id="R3",
        state="running",
        node_outputs={"N1": {"state": "skipped", "output": None, "data": {}}},
    )
    ready = _ready_nodes(state, wf)
    assert "N2" in ready, f"skipped 不应阻断下游；期望 N2 in ready，实际 {ready!r}"


def test_ready_nodes_failed节点不再ready():
    """failed 节点本身在 NON_READY_STATES 中，不会被重新 ready。"""
    wf = _wf_dag_explicit()
    state = RunState(
        run_id="R4",
        state="running",
        node_outputs={"N1": {"state": "failed", "output": "", "data": {}}},
    )
    ready = _ready_nodes(state, wf)
    # N2/N3 依赖 N1 但 N1 failed（不在 SUCCESS_TERMINAL）→ 依赖未满足
    assert ready == [], f"failed 节点不应让下游 ready，期望空，实际 {ready!r}"


def test_ready_nodes_全完成返回空():
    """全节点 ∈ SUCCESS_TERMINAL → ready 为空（拓扑跑完）。"""
    wf = _wf_dag_explicit()
    state = RunState(
        run_id="R5",
        state="running",
        node_outputs={
            "N1": {"state": "completed", "output": "", "data": {}},
            "N2": {"state": "completed", "output": "", "data": {}},
            "N3": {"state": "skipped", "output": None, "data": {}},
            "N4": {"state": "completed", "output": "", "data": {}},
        },
    )
    ready = _ready_nodes(state, wf)
    assert ready == [], f"全节点终态时 ready 应空，实际 {ready!r}"


# ============================================================================
# _select_next_dispatch_target 单测
# ============================================================================

def test_select_explicit路径走_ready_nodes():
    """explicit=True → _select_next_dispatch_target 返 _ready_nodes[0]。"""
    wf = _wf_dag_explicit()
    state = RunState(run_id="R6", state="running")
    nm = _node_map(wf)
    nxt = _select_next_dispatch_target(state, wf, nm)
    assert nxt == "N1", f"explicit=True 首启动期望 'N1'，实际 {nxt!r}"


def test_select_退化分支a_真新run返首节点():
    """退化路径分支 a 回归：仅 [workflow_started] + 退化 yaml 3 节点 → 返 'N1'。"""
    wf = _wf_dag_line()
    state = RunState(run_id="R7", state="running")  # 无 node_outputs
    nm = _node_map(wf)
    nxt = _select_next_dispatch_target(state, wf, nm)
    assert nxt == "N1", f"真新 run 期望首节点 'N1'，实际 {nxt!r}"


def test_select_退化分支b_续跑反扫completed():
    """退化路径分支 b 回归：current_node is None ∧ node_outputs[N1].state=='completed'
    → 反扫 last_visited=N1 → _next_node(N1, None) = 'N2'。"""
    wf = _wf_dag_line()
    state = RunState(
        run_id="R8",
        state="running",
        current_node=None,
        node_outputs={"N1": {"state": "completed", "output": "ok", "data": {}}},
    )
    nm = _node_map(wf)
    nxt = _select_next_dispatch_target(state, wf, nm)
    assert nxt == "N2", f"续跑反扫期望 'N2'，实际 {nxt!r}"


def test_select_退化分支b_末节点反扫返None():
    """末节点反扫断言：[..., node_completed(N3)] N3 末节点 → 返 None。"""
    wf = _wf_dag_line()
    state = RunState(
        run_id="R9",
        state="running",
        current_node=None,
        node_outputs={
            "N1": {"state": "completed", "output": "", "data": {}},
            "N2": {"state": "completed", "output": "", "data": {}},
            "N3": {"state": "completed", "output": "", "data": {}},
        },
    )
    nm = _node_map(wf)
    nxt = _select_next_dispatch_target(state, wf, nm)
    assert nxt is None, f"末节点反扫期望 None（交 finalize 处理），实际 {nxt!r}"


def test_select_退化skipped反向回归_v7REV006P1闭环():
    """skipped 反向回归（v7 REV-006 P1 闭环）：node_skipped(N1) 反扫 last_visited=N1
    → 返 'N2'。关键反向：N1 不会被错误重派。"""
    wf = _wf_dag_line()
    state = RunState(
        run_id="R10",
        state="running",
        current_node=None,
        node_outputs={"N1": {"state": "skipped", "output": None, "data": {"reason": "on_failure=skip"}}},
    )
    nm = _node_map(wf)
    nxt = _select_next_dispatch_target(state, wf, nm)
    assert nxt == "N2", (
        f"skipped 反扫期望 'N2'（不应重派 N1），实际 {nxt!r}"
    )
    assert nxt != "N1", "关键反向：N1 已 skipped 绝不能被再次派发"


# ============================================================================
# _finalize_after_rebuild_if_last_topology_node 单测
# ============================================================================

def test_finalize_DAG_全完成_补workflow_completed(tmp_path):
    """DAG 路径：全节点 ∈ SUCCESS_TERMINAL ∧ 无 failed ∧ _ready_nodes 空 → 补
    workflow_completed，返 True。"""
    wf = _wf_dag_explicit()
    jsonl = tmp_path / "rs.jsonl"
    _write_jsonl(jsonl, [
        {"type": "workflow_started", "run_id": "RX1", "data": {"workflow_name": "x"}},
        {"type": "node_completed", "node_id": "N1", "data": {}},
        {"type": "node_completed", "node_id": "N2", "data": {}},
        {"type": "node_completed", "node_id": "N3", "data": {}},
        {"type": "node_completed", "node_id": "N4", "data": {}},
    ])
    state = RunState(
        run_id="RX1",
        state="running",
        current_node=None,
        node_outputs={
            "N1": {"state": "completed", "output": "", "data": {}},
            "N2": {"state": "completed", "output": "", "data": {}},
            "N3": {"state": "completed", "output": "", "data": {}},
            "N4": {"state": "completed", "output": "", "data": {}},
        },
    )
    nm = _node_map(wf)
    ret = _finalize_after_rebuild_if_last_topology_node(state, wf, nm, jsonl)
    assert ret is True, "全 SUCCESS_TERMINAL 应触发 finalize，返 True"
    assert state.state == "completed", f"state 应翻到 completed，实际 {state.state!r}"
    # 末事件应为 workflow_completed
    with jsonl.open() as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    assert lines[-1]["type"] == "workflow_completed", (
        f"末事件应为 workflow_completed，实际 {lines[-1]['type']!r}"
    )


def test_finalize_DAG_含failed节点_返False(tmp_path):
    """DAG 路径含 failed 节点 → finalize 返 False（不写 workflow_completed，
    由失败矩阵接管 workflow_failed）。"""
    wf = _wf_dag_explicit()
    jsonl = tmp_path / "rs.jsonl"
    _write_jsonl(jsonl, [
        {"type": "workflow_started", "run_id": "RX2", "data": {"workflow_name": "x"}},
        {"type": "node_completed", "node_id": "N1", "data": {}},
        {"type": "node_failed", "node_id": "N2", "data": {}},
        {"type": "node_completed", "node_id": "N3", "data": {}},
    ])
    state = RunState(
        run_id="RX2",
        state="running",
        current_node=None,
        node_outputs={
            "N1": {"state": "completed", "output": "", "data": {}},
            "N2": {"state": "failed", "output": "", "data": {}},
            "N3": {"state": "completed", "output": "", "data": {}},
        },
    )
    nm = _node_map(wf)
    ret = _finalize_after_rebuild_if_last_topology_node(state, wf, nm, jsonl)
    assert ret is False, (
        "含 failed 节点 finalize 应返 False（由失败矩阵决定 workflow_failed/retry/skip）"
    )
    assert state.state == "running", (
        f"state 不应被改写，实际 {state.state!r}"
    )


def test_finalize_单链末节点skipped_v8P1反向回归(tmp_path):
    """v8 P1 反向回归 b：N1→N2→N3 单链 + node_completed(N1) + node_completed(N2)
    + node_skipped(N3) → 反扫 last_visited=N3 → _next_node(N3, None) is None →
    补 workflow_completed。"""
    wf = _wf_dag_line()  # depends_on_explicit=False，单链 N1.next=N2.next=N3
    jsonl = tmp_path / "rs.jsonl"
    _write_jsonl(jsonl, [
        {"type": "workflow_started", "run_id": "RX3", "data": {"workflow_name": "x"}},
        {"type": "node_completed", "node_id": "N1", "data": {}},
        {"type": "node_completed", "node_id": "N2", "data": {}},
        {"type": "node_skipped", "node_id": "N3", "data": {"reason": "on_failure=skip"}},
    ])
    state = RunState(
        run_id="RX3",
        state="running",
        current_node=None,
        node_outputs={
            "N1": {"state": "completed", "output": "", "data": {}},
            "N2": {"state": "completed", "output": "", "data": {}},
            "N3": {"state": "skipped", "output": None, "data": {}},
        },
    )
    nm = _node_map(wf)
    ret = _finalize_after_rebuild_if_last_topology_node(state, wf, nm, jsonl)
    assert ret is True, (
        "单链末节点 skipped 应触发 finalize（v8 P1 反向回归），返 True"
    )
    assert state.state == "completed", (
        f"state 应翻到 completed，实际 {state.state!r}"
    )


def test_finalize_多sink_单sink完成_返False(tmp_path):
    """多 sink DAG 反向回归：N1 → A / N1 → B 双 sink；A 单独 completed 后 finalize
    应返 False（B 还未完成）。"""
    wf = _wf_two_sinks()
    jsonl = tmp_path / "rs.jsonl"
    _write_jsonl(jsonl, [
        {"type": "workflow_started", "run_id": "RX4", "data": {"workflow_name": "x"}},
        {"type": "node_completed", "node_id": "N1", "data": {}},
        {"type": "node_completed", "node_id": "A", "data": {}},
    ])
    state = RunState(
        run_id="RX4",
        state="running",
        current_node=None,
        node_outputs={
            "N1": {"state": "completed", "output": "", "data": {}},
            "A": {"state": "completed", "output": "", "data": {}},
        },
    )
    nm = _node_map(wf)
    ret = _finalize_after_rebuild_if_last_topology_node(state, wf, nm, jsonl)
    assert ret is False, "单 sink completed 不应触发 finalize（B 仍 ready）"
    assert state.state == "running"


def test_finalize_多sink_全sink完成_返True(tmp_path):
    """多 sink DAG：A+B 都 completed → 返 True，写 workflow_completed。"""
    wf = _wf_two_sinks()
    jsonl = tmp_path / "rs.jsonl"
    _write_jsonl(jsonl, [
        {"type": "workflow_started", "run_id": "RX5", "data": {"workflow_name": "x"}},
        {"type": "node_completed", "node_id": "N1", "data": {}},
        {"type": "node_completed", "node_id": "A", "data": {}},
        {"type": "node_completed", "node_id": "B", "data": {}},
    ])
    state = RunState(
        run_id="RX5",
        state="running",
        current_node=None,
        node_outputs={
            "N1": {"state": "completed", "output": "", "data": {}},
            "A": {"state": "completed", "output": "", "data": {}},
            "B": {"state": "completed", "output": "", "data": {}},
        },
    )
    nm = _node_map(wf)
    ret = _finalize_after_rebuild_if_last_topology_node(state, wf, nm, jsonl)
    assert ret is True, "全 sink completed 应触发 finalize，返 True"
    assert state.state == "completed"
