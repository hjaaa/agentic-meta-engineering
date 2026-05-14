"""F-004 rev2 · e2e：DAG 主链路完整跑通（F-CR-001 / F-CR-002 回归保护）。

覆盖范围：
  1. test_dag_multi_sink_full_chain
     fixture workflow_dag_multi_sink.yaml（3 节点 A→B / A→C，多 sink），
     调 _main_loop（同 main() 内部）让 mock dispatch_node 返 completed × 3：
     - F-CR-002 bootstrap：current_node=None 起步 → _select_next_dispatch_target 取 a
     - F-CR-001 _advance_after_completed 按 depends_on_explicit=True 分流：
       a completed 后通过 _select_next_dispatch_target 取 [b, c] 串行 [0]=b → b 完后 c
     - finalize 写 workflow_completed
  2. test_standard_8phase_dag_bootstrap_validate_first_then_second_layer
     调真实 main() 跑 .claude/workflows/requirement/standard-8phase.yaml，
     mock dispatch_node 让 bootstrap-validate completed，断言：
     - bootstrap-validate（无 next 字段、depends_on=[]）首派
     - 完成后第二层 ready 节点 req-input-normalize 正确派发为下一个节点
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event  # noqa: E402
from workflow_continue import _main_loop, main  # noqa: E402
from workflow_loader import load_workflow  # noqa: E402


FIXTURE_MULTI_SINK = REPO_ROOT / "tests" / "fixtures" / "workflow_dag_multi_sink.yaml"
STANDARD_8PHASE = REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                out.append(json.loads(stripped))
    return out


# ============================================================================
# Test 1：多 sink DAG 全链路（覆盖 F-CR-001 + F-CR-002）
# ============================================================================


def test_dag_multi_sink_full_chain(tmp_path):
    """3 节点 DAG A→B / A→C 完整跑通：bootstrap 取 a → advance 推 b → advance 推 c →
    finalize workflow_completed。

    F-CR-001 / F-CR-002 联合回归保护：
      - bootstrap（current_node 初始 None）→ _select_next_dispatch_target → "a"
      - a completed → _advance_after_completed 走 depends_on_explicit=True 分流 →
        _select_next_dispatch_target 取 ready=[b, c][0] = "b"
      - b completed → 同上 → ready=[c][0] = "c"
      - c completed → 无更多 ready → current_node=None → finalize 写 workflow_completed
    """
    from workflow_dispatcher import DispatchResult

    # 加载 fixture 并断言 depends_on_explicit=True（DAG 路径）
    loader_result = load_workflow(FIXTURE_MULTI_SINK)
    assert loader_result.report.errors == 0, loader_result.report.render()
    workflow = loader_result.workflow
    assert workflow["depends_on_explicit"] is True, (
        "fixture 全节点显式 depends_on，loader 应标 explicit=True"
    )

    # 构造 run-state.jsonl 起点：workflow_started + current_node 初始 None
    run_id = "RUN-DAG-MULTI-001"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl = run_dir / "run-state.jsonl"
    append_event(jsonl, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "workflow-dag-multi-sink", "arguments": ""},
    })

    run_state = RunState(run_id=run_id, state="running")  # current_node 默认 None

    # 节点输出 mock
    node_outputs_map = {"a": "a-out", "b": "b-out", "c": "c-out"}

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        def dispatch_side_effect(node, *args, **kwargs):
            return DispatchResult(
                outcome="completed",
                output=node_outputs_map.get(node.get("id"), ""),
            )
        mock_dispatch.side_effect = dispatch_side_effect

        # F-CR-002：main_loop 入口 bootstrap 应自动算出首节点 a
        _main_loop(run_state, workflow, run_dir, tmp_path, jsonl)

    # 验证：3 节点 completed + workflow_completed 末事件
    events = _read_jsonl(jsonl)
    types = [e["type"] for e in events]
    assert types[-1] == "workflow_completed", (
        f"末事件应为 workflow_completed，实际尾部 = {types[-3:]!r}"
    )
    completed_node_ids = [e["node_id"] for e in events if e["type"] == "node_completed"]
    # 注：node_completed 由真实 dispatcher 写入，本测 mock dispatch_node 后 dispatcher 不写事件；
    # 仅通过 mock_dispatch.call_args_list 验证派发顺序（A→B→C 串行）。
    dispatched_ids = [
        call.args[0]["id"] for call in mock_dispatch.call_args_list
    ]
    assert dispatched_ids == ["a", "b", "c"], (
        f"派发顺序应为 a→b→c（多 sink 串行）；实际 {dispatched_ids!r}"
    )
    assert mock_dispatch.call_count == 3
    assert run_state.state == "completed", (
        f"DAG 全链跑完 state 应为 completed；实际 {run_state.state!r}"
    )
    # node_outputs 含全部 3 节点
    for nid in ("a", "b", "c"):
        assert nid in run_state.node_outputs
        assert run_state.node_outputs[nid]["state"] == "completed"


# ============================================================================
# Test 2：真实 standard-8phase.yaml DAG main() 入口（覆盖 F-CR-001 + F-CR-002 + bootstrap）
# ============================================================================


def test_standard_8phase_dag_bootstrap_validate_first_then_second_layer(tmp_path):
    """调真实 main() 跑 standard-8phase.yaml：

    - F-CR-002 bootstrap：真新 run（current_node 起初 None）应通过 main_loop 入口的
      bootstrap 自动算出首节点 bootstrap-validate（DAG 顶节点，depends_on=[]，无 next 字段）
    - F-CR-001 advance：bootstrap-validate completed 后通过 depends_on_explicit=True 分流，
      _select_next_dispatch_target 应推进到第二层 ready 节点 req-input-normalize
      （depends_on=[bootstrap-validate]）

    覆盖手段：mock dispatch_node 让前 2 节点 completed，第三次返 approval_pending 让 main_loop
    优雅退出（避免实际跑完所有 38 节点）。最终断言 dispatcher 第 1/2 次派发的节点 ID 正确。
    """
    if not STANDARD_8PHASE.exists():
        pytest.skip("standard-8phase.yaml not present in this env")
    from workflow_dispatcher import DispatchResult

    # 创建 run 目录（_resolve_run_dir 双路径：先 requirements/<id>/，再 runs/<id>/）
    run_id = "REQ-2099-S8P-DAG-001"
    run_dir = tmp_path / "requirements" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl = run_dir / "run-state.jsonl"

    # _load_workflow_for_run 按 root/.claude/workflows/requirement/<name>.yaml 查模板，
    # 而 main(repo_root=tmp_path) 时根换成 tmp_path → 需把真实 yaml 拷过去
    target_wf_dir = tmp_path / ".claude" / "workflows" / "requirement"
    target_wf_dir.mkdir(parents=True, exist_ok=True)
    (target_wf_dir / "standard-8phase.yaml").write_text(
        STANDARD_8PHASE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    # 写 workflow_started（main() → _setup_run → rebuild 需要 workflow_name）
    append_event(jsonl, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "standard-8phase", "arguments": ""},
    })

    # mock dispatcher：前 2 次 completed，第 3 次起返 approval_pending 优雅退出
    call_log: list[str] = []

    from workflow_dispatcher import DispatchResult as _DR  # noqa: F401

    def dispatch_side_effect(node, *args, **kwargs):
        nid = node.get("id")
        call_log.append(nid)
        if len(call_log) <= 2:
            return DispatchResult(outcome="completed", output=f"{nid}-out")
        # 第 3 次（第二层节点完成后想推进第三层时）返 approval_pending 让 main loop 退出
        return DispatchResult(outcome="approval_pending")

    with patch("workflow_dispatcher.dispatch_node") as mock_dispatch:
        mock_dispatch.side_effect = dispatch_side_effect
        rc = main([run_id], repo_root=tmp_path)

    # main() 应正常退出（approval_pending 是预期分支退出码 0）
    assert rc == 0, f"main() 应正常退出（approval_pending 终态）；实际 rc={rc}"

    # F-CR-002 验证：bootstrap 取出的首节点是 bootstrap-validate
    assert len(call_log) >= 1, "main_loop bootstrap 应至少派发首节点 1 次"
    assert call_log[0] == "bootstrap-validate", (
        f"首派应为 bootstrap-validate（DAG 顶节点）；实际首派 = {call_log[0]!r}"
    )

    # F-CR-001 验证：advance 推进到第二层节点 req-input-normalize
    assert len(call_log) >= 2, (
        "bootstrap-validate completed 后 advance 应推进到第二层 ready 节点 "
        "（_advance_after_completed 按 depends_on_explicit=True 分流到 _select_next_dispatch_target）"
    )
    assert call_log[1] == "req-input-normalize", (
        f"第二派应为 req-input-normalize（depends_on=[bootstrap-validate]）；"
        f"实际第二派 = {call_log[1]!r}"
    )
