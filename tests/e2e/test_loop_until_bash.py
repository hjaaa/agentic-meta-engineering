"""F-010 · e2e：loop until_bash 跑通到 workflow_completed。

覆盖（AC-07 acceptance #5）：
- fixture workflow_loop_until.yaml：单节点 loop + until_bash 'test "$iter" -ge 3' + max_iterations=5
- 预期：跑 3 轮（iter=0,1,2 exit≠0）后，iter=3 exit=0 → loop_completed + workflow_completed
- 断言：jsonl 含 loop_completed + workflow_completed（无 loop_max_iterations_exceeded）

测试运行：
    python3 -m pytest tests/e2e/test_loop_until_bash.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event  # noqa: E402
from workflow_continue import _main_loop  # noqa: E402
from workflow_loader import load_workflow  # noqa: E402
from workflow_scheduler import _select_next_dispatch_target  # noqa: E402


FIXTURE_YAML = REPO_ROOT / "tests" / "fixtures" / "workflow_loop_until.yaml"


def _read_jsonl(path: Path) -> list[dict]:
    """读取 jsonl 文件中所有非空事件行。"""
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                out.append(json.loads(stripped))
    return out


def _build_node_map(workflow: dict) -> dict[str, dict]:
    return {n["id"]: n for n in workflow.get("nodes", [])}


# ============================================================================
# TC-F10-E2E-1：fixture 跑 3 轮后 loop_completed + workflow_completed
# ============================================================================

def test_loop_until_bash_completes_after_three_iterations(tmp_path: Path) -> None:
    """TC-F10-E2E-1：workflow_loop_until.yaml 跑 3 轮后 jsonl 含 loop_completed + workflow_completed。

    验证：
    - loop 节点连续派发，iter=0,1,2 时 until_bash 不满足（loop_continue）
    - iter=3 时 until_bash 满足（exit=0）→ loop_completed
    - main loop 随后写 workflow_completed
    - jsonl 中不含 loop_max_iterations_exceeded（自然退出路径）
    - loop_iteration_started 恰好 3 条（对应 iter=0,1,2 三轮迭代）
    """
    # 1. 加载 fixture
    loader_result = load_workflow(FIXTURE_YAML)
    assert loader_result.report.errors == 0, (
        f"fixture 加载失败：{loader_result.report.render()}"
    )
    workflow = loader_result.workflow

    # 2. 构造 run-state.jsonl 起点
    run_id = "RUN-F010-E2E-001"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl = run_dir / "run-state.jsonl"
    append_event(jsonl, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "workflow-loop-until", "arguments": ""},
    })

    # 3. 构造 RunState 起点并设置首节点
    run_state = RunState(run_id=run_id, state="running")
    node_map = _build_node_map(workflow)
    first_id = _select_next_dispatch_target(run_state, workflow, node_map)
    assert first_id == "check-loop", (
        f"首节点期望 'check-loop'，实际 {first_id!r}"
    )
    run_state.current_node = first_id

    # 4. 调 _main_loop 跑完（root=tmp_path，until_bash 用系统 bash 执行）
    _main_loop(run_state, workflow, run_dir, tmp_path, jsonl)

    # 5. 断言
    events = _read_jsonl(jsonl)
    types = [e["type"] for e in events]

    assert "loop_completed" in types, (
        f"应有 loop_completed 事件，实际事件类型序列：{types}"
    )
    assert types[-1] == "workflow_completed", (
        f"末事件应为 workflow_completed，实际尾部：{types[-3:]!r}"
    )
    assert "loop_max_iterations_exceeded" not in types, (
        "until_bash 自然退出路径不应有 loop_max_iterations_exceeded"
    )

    # iter=0,1,2 三轮迭代（iter=3 时 until_bash exit=0 直接退出，不写 loop_iteration_started）
    iter_started = [e for e in events if e["type"] == "loop_iteration_started"]
    assert len(iter_started) == 3, (
        f"应有 3 条 loop_iteration_started（iter=0,1,2），实际 {len(iter_started)}"
    )
    for i, evt in enumerate(iter_started):
        assert evt.get("data", {}).get("iteration") == i, (
            f"第 {i+1} 条 loop_iteration_started.data.iteration 应为 {i}，"
            f"实际 {evt.get('data', {}).get('iteration')!r}"
        )

    assert run_state.state == "completed", (
        f"run_state.state 应为 completed，实际 {run_state.state!r}"
    )
