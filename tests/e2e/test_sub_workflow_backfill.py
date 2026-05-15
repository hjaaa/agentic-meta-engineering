"""F-011 · e2e：sub_workflow 父子完成回填 → 父 workflow_completed（AC-08 AC-6）。

覆盖 AC-6：
- 父 yaml（workflow_parent_sub.yaml）含 sub_workflow 节点
- 子 yaml（workflow_child_simple.yaml）2 节点全跑通（预置子 jsonl 末位 workflow_completed）
- 调用父 _main_loop → _poll_sub_workflows 回填 → 父 jsonl 末位 workflow_completed

测试运行：
    python3 -m pytest tests/e2e/test_sub_workflow_backfill.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event  # noqa: E402
from workflow_continue import _main_loop  # noqa: E402
from workflow_loader import load_workflow  # noqa: E402
from workflow_scheduler import _select_next_dispatch_target  # noqa: E402


PARENT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "workflow_parent_sub.yaml"
CHILD_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "workflow_child_simple.yaml"

SUB_NODE_ID = "sub-node"


def _read_jsonl(path: Path) -> list[dict]:
    """读取 jsonl 文件中所有非空事件行。"""
    out: list[dict] = []
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                out.append(json.loads(stripped))
    return out


def _write_child_completed_jsonl(sub_run_dir: Path, child_run_id: str) -> None:
    """预置子 run 的 run-state.jsonl：workflow_started + 2 bash 节点完成 + workflow_completed。"""
    sub_run_dir.mkdir(parents=True, exist_ok=True)
    jsonl = sub_run_dir / "run-state.jsonl"
    events = [
        {
            "type": "workflow_started",
            "run_id": child_run_id,
            "data": {"workflow_name": "workflow-child-simple", "arguments": ""},
            "ts": "2026-05-15T00:00:00Z",
        },
        {
            "type": "node_started",
            "node_id": "child-step-1",
            "ts": "2026-05-15T00:00:01Z",
        },
        {
            "type": "node_completed",
            "node_id": "child-step-1",
            "data": {"output": "child step 1 done"},
            "ts": "2026-05-15T00:00:02Z",
        },
        {
            "type": "node_started",
            "node_id": "child-step-2",
            "ts": "2026-05-15T00:00:03Z",
        },
        {
            "type": "node_completed",
            "node_id": "child-step-2",
            "data": {"output": "child step 2 done"},
            "ts": "2026-05-15T00:00:04Z",
        },
        {
            "type": "workflow_completed",
            "data": {},
            "ts": "2026-05-15T00:00:05Z",
        },
    ]
    with jsonl.open("w", encoding="utf-8") as fh:
        for evt in events:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")


# ============================================================================
# TC-F11-E2E-1：父 yaml + 子 jsonl 末位 workflow_completed → 父末位 workflow_completed
# ============================================================================

def test_sub_workflow_backfill_parent_completed(tmp_path: Path) -> None:
    """TC-F11-E2E-1 (AC-6)：父含 sub_workflow 节点 + 子 jsonl 末位 workflow_completed。

    验证流程：
    1. 加载父 fixture yaml（workflow_parent_sub.yaml）
    2. 预置子 run（sub_runs/sub-node/）jsonl 末位为 workflow_completed
    3. 构造父 RunState：current_node = "sub-node"（模拟父 run 已派发子但未回填）
    4. 调用 _main_loop：_poll_sub_workflows 回填 child_graceful_exited + node_completed
    5. _finalize_after_rebuild 检测 sub-node 已 completed → 写 workflow_completed

    断言：
    - 父 jsonl 含 child_graceful_exited
    - 父 jsonl 含 node_completed（sub-node）
    - 父 jsonl 末位 = workflow_completed
    - run_state.state == completed
    """
    # 1. 加载父 fixture
    loader_result = load_workflow(PARENT_FIXTURE)
    assert loader_result.report.errors == 0, (
        f"父 fixture 加载失败：{loader_result.report.render()}"
    )
    workflow = loader_result.workflow

    # 2. 构造父 run 目录 + jsonl
    run_id = "RUN-F011-E2E-001"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    parent_jsonl = run_dir / "run-state.jsonl"
    append_event(parent_jsonl, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "workflow-parent-sub", "arguments": ""},
    })

    # 3. 预置子 run：sub_runs/sub-node/ 已 workflow_completed
    sub_run_dir = run_dir / "sub_runs" / SUB_NODE_ID
    _write_child_completed_jsonl(sub_run_dir, child_run_id=SUB_NODE_ID)

    # 4. 构造父 RunState：current_node = SUB_NODE_ID（模拟父已派发子但未回填）
    run_state = RunState(run_id=run_id, state="running")
    run_state.current_node = SUB_NODE_ID

    # 5. 调用 _main_loop（root=tmp_path，_poll_sub_workflows 在入口回填）
    _main_loop(run_state, workflow, run_dir, tmp_path, parent_jsonl)

    # 6. 断言
    events = _read_jsonl(parent_jsonl)
    types = [e["type"] for e in events]

    assert "child_graceful_exited" in types, (
        f"父 jsonl 应含 child_graceful_exited，实际事件序列：{types}"
    )
    assert "node_completed" in types, (
        f"父 jsonl 应含 node_completed，实际事件序列：{types}"
    )
    assert types[-1] == "workflow_completed", (
        f"父 jsonl 末事件应为 workflow_completed，实际尾部：{types[-3:]!r}"
    )
    assert run_state.state == "completed", (
        f"run_state.state 应为 completed，实际 {run_state.state!r}"
    )

    # child_graceful_exited 事件包含 sub_run_id
    cge = next(e for e in events if e["type"] == "child_graceful_exited")
    assert cge.get("node_id") == SUB_NODE_ID or cge.get("data", {}).get("sub_run_id") == SUB_NODE_ID
