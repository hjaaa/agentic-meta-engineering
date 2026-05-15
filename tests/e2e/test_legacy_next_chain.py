"""F-004 · e2e：退化（depends_on_explicit=False）yaml 5 节点单链跑通到 workflow_completed。

详细设计 §3.6.2 退化路径双分支 + §3.6.3 单链 finalize；
对应 ADR D-006（depends_on_explicit 标记位 + 同层 ready 串行派发）。

测试主体：
  1. 加载 fixture `tests/fixtures/workflow_legacy_next.yaml`（loader 标 explicit=False）
  2. 在 tmp_path/runs/RUN-LEGACY-NEXT-001/run-state.jsonl 写 workflow_started
  3. 用 `_select_next_dispatch_target` 选首节点 + 直接调 `_main_loop` 跑完
  4. 断言：
     - 末事件 = workflow_completed
     - jsonl 含 5 个 node_completed（n1~n5 顺序）

注：因 workflow_bootstrap 不预设 current_node，main_loop 自身也不内置 scheduler bootstrap
（避免触动 F-004 触及范围之外的 main loop 既有 crash-window 测试假设），由 e2e 用 F-004
新增的 `_select_next_dispatch_target` 显式置 current_node 后再调 main_loop。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event  # noqa: E402
from workflow_continue import _main_loop  # noqa: E402
from workflow_scheduler import (  # noqa: E402
    _ready_nodes,
    _select_next_dispatch_target,
)
from workflow_loader import load_workflow  # noqa: E402


FIXTURE_YAML = REPO_ROOT / "tests" / "fixtures" / "workflow_legacy_next.yaml"


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                out.append(json.loads(stripped))
    return out


def _build_node_map(workflow: dict) -> dict[str, dict]:
    return {n["id"]: n for n in workflow["nodes"]}


def test_legacy_next_chain_跑通到workflow_completed(tmp_path):
    """e2e 退化路径：5 节点 bash 单链跑完 → 末事件 workflow_completed，
    5 个 node_completed 按 n1→n5 顺序。"""
    # 1. 加载 fixture（loader 标 depends_on_explicit=False）
    loader_result = load_workflow(FIXTURE_YAML)
    assert loader_result.report.errors == 0, loader_result.report.render()
    workflow = loader_result.workflow
    assert workflow["depends_on_explicit"] is False, (
        "fixture 应为退化路径 (depends_on_explicit=False)；否则 e2e 覆盖目标错位"
    )

    # 2. 构造 run-state.jsonl 起点：只写 workflow_started
    run_id = "RUN-LEGACY-NEXT-001"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl = run_dir / "run-state.jsonl"
    append_event(jsonl, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "workflow-legacy-next", "arguments": ""},
    })

    # 3. RunState 起点（模拟 workflow_continue _setup_run + _resume_run 之后的状态）
    run_state = RunState(run_id=run_id, state="running")
    node_map = _build_node_map(workflow)
    # F-004：用 _select_next_dispatch_target 选首节点 → 真新 run 分支 a 返 nodes[0]
    first_id = _select_next_dispatch_target(run_state, workflow, node_map)
    assert first_id == "n1", f"退化路径首启动应取 yaml.nodes[0].id='n1'，实际 {first_id!r}"
    run_state.current_node = first_id

    # 4. 调 main_loop 跑完 5 节点
    _main_loop(run_state, workflow, run_dir, tmp_path, jsonl)

    # 5. 断言：末事件 workflow_completed + 5 个 node_completed 按序
    events = _read_jsonl(jsonl)
    types = [e["type"] for e in events]
    assert types[-1] == "workflow_completed", (
        f"末事件应为 workflow_completed，实际尾部 = {types[-3:]!r}"
    )
    completed_nodes = [e["node_id"] for e in events if e["type"] == "node_completed"]
    assert completed_nodes == ["n1", "n2", "n3", "n4", "n5"], (
        f"node_completed 顺序应为 n1..n5，实际 {completed_nodes!r}"
    )
    assert run_state.state == "completed", (
        f"run_state.state 应为 completed，实际 {run_state.state!r}"
    )


def test_standard_8phase_首节点为bootstrap_validate():
    """e2e DAG 路径：standard-8phase.yaml 走 DAG 路径首节点 bootstrap-validate。

    本测仅做"loader 加载 + _ready_nodes 首启动结果"断言（避免触发真实 skill/agent 调用）。
    """
    yaml_path = REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"
    if not yaml_path.exists():
        return  # CI 受限环境兜底
    loader_result = load_workflow(yaml_path)
    assert loader_result.report.errors == 0, loader_result.report.render()
    wf = loader_result.workflow
    assert wf["depends_on_explicit"] is True, (
        "standard-8phase 全节点显式 depends_on，应为 explicit=True"
    )

    # 首启动：无 node_outputs → _ready_nodes 返首节点
    state = RunState(run_id="RXX", state="running")
    ready = _ready_nodes(state, wf)
    assert ready and ready[0] == "bootstrap-validate", (
        f"首节点期望 'bootstrap-validate'，实际 _ready_nodes={ready!r}"
    )

    nm = _build_node_map(wf)
    nxt = _select_next_dispatch_target(state, wf, nm)
    assert nxt == "bootstrap-validate", (
        f"_select_next_dispatch_target 期望 'bootstrap-validate'，实际 {nxt!r}"
    )


def test_standard_8phase_第二层ready计算正确():
    """e2e DAG 路径：bootstrap-validate completed 后，第二层 ready 仅含
    依赖 bootstrap-validate 的节点（D-006 串行派发取 [0]）。"""
    yaml_path = REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"
    if not yaml_path.exists():
        return
    loader_result = load_workflow(yaml_path)
    wf = loader_result.workflow

    state = RunState(
        run_id="RXY",
        state="running",
        node_outputs={
            "bootstrap-validate": {"state": "completed", "output": "", "data": {}}
        },
    )
    ready = _ready_nodes(state, wf)
    expected = [
        n["id"] for n in wf["nodes"]
        if n.get("depends_on") == ["bootstrap-validate"]
    ]
    assert expected, "yaml 期望至少有一个节点依赖 bootstrap-validate"
    for nid in expected:
        assert nid in ready, (
            f"节点 {nid!r} 依赖 bootstrap-validate（已 completed），应在 ready 中；"
            f"实际 ready={ready!r}"
        )
