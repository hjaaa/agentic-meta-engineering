"""Bug-14 · save_node_result --kind=loop_iteration 单元测试 + e2e 闭环。

覆盖：
- TC-SLI-1：outcome=continue 写 loop_iteration_completed{iter, continue} + loop_counter_advanced{iter+1}
- TC-SLI-2：outcome=all_done 写 loop_iteration_completed{iter, all_done}（不写 counter_advanced）
- TC-SLI-3：outcome 非法 → exit=1 + E-NODE-RESULT-006
- TC-SLI-4：state != awaiting_claude_action → exit=2 + E-NODE-RESULT-001
- TC-SLI-5：末位 node_ready.data 缺 loop_iteration → exit=1
- TC-SLI-6：rebuild 规则——loop_iteration_completed 把 awaiting_claude_action 拉回 running
- TC-SLI-7（e2e）：dispatch → save continue → dispatch → save all_done → dispatch 终止
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event, read_events  # noqa: E402
from save_node_result import main as save_main  # noqa: E402
from workflow_dispatcher import _dispatch_loop_node  # noqa: E402


def _read_events_raw(jsonl: Path) -> list[dict]:
    if not jsonl.exists():
        return []
    out = []
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _bootstrap_run_dir(tmp_path: Path, run_id: str) -> tuple[Path, Path]:
    """构造 requirements/<run_id>/ 目录 + 空 run-state.jsonl。"""
    req_dir = tmp_path / "requirements" / run_id
    req_dir.mkdir(parents=True)
    jsonl = req_dir / "run-state.jsonl"
    jsonl.touch()
    return req_dir, jsonl


def _inject_node_ready(jsonl: Path, node_id: str, iteration: int) -> None:
    """把 jsonl 推进到 awaiting_claude_action 状态：写 node_started + node_ready{loop}。"""
    append_event(jsonl, {
        "type": "node_started",
        "node_id": node_id,
        "run_id": "REQ-2026-009",
    })
    append_event(jsonl, {
        "type": "loop_iteration_started",
        "node_id": node_id,
        "data": {"iteration": iteration},
    })
    append_event(jsonl, {
        "type": "node_ready",
        "node_id": node_id,
        "run_id": "REQ-2026-009",
        "data": {
            "node_kind": "loop_iteration",
            "prompt": "p",
            "loop_iteration": iteration,
            "external_action_contract": {},
        },
    })


# ============================================================================
# TC-SLI-1：outcome=continue → loop_iteration_completed + loop_counter_advanced
# ============================================================================

def test_save_loop_iteration_continue_writes_two_events(tmp_path: Path) -> None:
    run_id = "REQ-2026-009"
    _req_dir, jsonl = _bootstrap_run_dir(tmp_path, run_id)
    _inject_node_ready(jsonl, "dev-loop", iteration=2)

    rc = save_main([
        "--run", run_id,
        "--node", "dev-loop",
        "--kind", "loop_iteration",
        "--output", '{"outcome":"continue"}',
        "--repo-root", str(tmp_path),
    ])
    assert rc == 0

    events = _read_events_raw(jsonl)
    tail = [e["type"] for e in events[-2:]]
    assert tail == ["loop_iteration_completed", "loop_counter_advanced"]
    assert events[-2]["data"]["iteration"] == 2
    assert events[-2]["data"]["outcome"] == "continue"
    assert events[-1]["data"]["new_value"] == 3


# ============================================================================
# TC-SLI-2：outcome=all_done → 只写 loop_iteration_completed
# ============================================================================

def test_save_loop_iteration_all_done_writes_single_event(tmp_path: Path) -> None:
    run_id = "REQ-2026-009"
    _req_dir, jsonl = _bootstrap_run_dir(tmp_path, run_id)
    _inject_node_ready(jsonl, "dev-loop", iteration=4)

    rc = save_main([
        "--run", run_id,
        "--node", "dev-loop",
        "--kind", "loop_iteration",
        "--output", '{"outcome":"all_done"}',
        "--repo-root", str(tmp_path),
    ])
    assert rc == 0

    events = _read_events_raw(jsonl)
    tail = events[-1]
    assert tail["type"] == "loop_iteration_completed"
    assert tail["data"]["outcome"] == "all_done"
    # 不应写 loop_counter_advanced
    assert not any(e["type"] == "loop_counter_advanced" for e in events)


# ============================================================================
# TC-SLI-3：outcome 非法 → exit=1
# ============================================================================

def test_save_loop_iteration_invalid_outcome_rejected(tmp_path: Path, capsys) -> None:
    run_id = "REQ-2026-009"
    _req_dir, jsonl = _bootstrap_run_dir(tmp_path, run_id)
    _inject_node_ready(jsonl, "dev-loop", iteration=0)

    rc = save_main([
        "--run", run_id,
        "--node", "dev-loop",
        "--kind", "loop_iteration",
        "--output", '{"outcome":"weird"}',
        "--repo-root", str(tmp_path),
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "E-NODE-RESULT-006" in err


# ============================================================================
# TC-SLI-4：state != awaiting_claude_action → exit=2
# ============================================================================

def test_save_loop_iteration_state_guard(tmp_path: Path, capsys) -> None:
    run_id = "REQ-2026-009"
    _req_dir, jsonl = _bootstrap_run_dir(tmp_path, run_id)
    # 不写 node_ready，state 仍 running
    append_event(jsonl, {
        "type": "workflow_started",
        "data": {"workflow_name": "test", "arguments": ""},
        "run_id": run_id,
    })

    # _check_state_or_fail 直接 sys.exit(2)，需要 pytest.raises 包住
    with pytest.raises(SystemExit) as excinfo:
        save_main([
            "--run", run_id,
            "--node", "dev-loop",
            "--kind", "loop_iteration",
            "--output", '{"outcome":"continue"}',
            "--repo-root", str(tmp_path),
        ])
    assert excinfo.value.code == 2
    assert "E-NODE-RESULT-001" in capsys.readouterr().err


# ============================================================================
# TC-SLI-5：末位 node_ready 缺 loop_iteration → exit=1
# ============================================================================

def test_save_loop_iteration_missing_iter_in_node_ready(tmp_path: Path, capsys) -> None:
    run_id = "REQ-2026-009"
    _req_dir, jsonl = _bootstrap_run_dir(tmp_path, run_id)
    append_event(jsonl, {
        "type": "node_started",
        "node_id": "dev-loop",
        "run_id": run_id,
    })
    # node_ready 没 loop_iteration 字段
    append_event(jsonl, {
        "type": "node_ready",
        "node_id": "dev-loop",
        "run_id": run_id,
        "data": {"node_kind": "loop_iteration", "prompt": "p", "external_action_contract": {}},
    })

    rc = save_main([
        "--run", run_id,
        "--node", "dev-loop",
        "--kind", "loop_iteration",
        "--output", '{"outcome":"continue"}',
        "--repo-root", str(tmp_path),
    ])
    assert rc == 1
    assert "loop_iteration" in capsys.readouterr().err


# ============================================================================
# TC-SLI-6：rebuild 规则——loop_iteration_completed 把 awaiting_claude_action 拉回 running
# ============================================================================

def test_rebuild_loop_iteration_completed_restores_running(tmp_path: Path) -> None:
    """Bug-14 修复后的 rebuild 规则：interactive loop 在收到 Claude
    loop_iteration_completed 后必须把 state 从 awaiting_claude_action 拉回 running。
    否则下一次 /workflow:continue state 矩阵会判失败。
    """
    events = [
        {"type": "workflow_started", "data": {"workflow_name": "t", "arguments": ""}, "run_id": "REQ-X"},
        {"type": "node_started", "node_id": "dev-loop", "run_id": "REQ-X"},
        {"type": "loop_iteration_started", "node_id": "dev-loop", "data": {"iteration": 0}},
        {"type": "node_ready", "node_id": "dev-loop", "run_id": "REQ-X",
         "data": {"node_kind": "loop_iteration", "prompt": "p", "loop_iteration": 0,
                  "external_action_contract": {}}},
        {"type": "loop_iteration_completed", "node_id": "dev-loop",
         "data": {"iteration": 0, "outcome": "continue"}},
        {"type": "loop_counter_advanced", "node_id": "dev-loop", "data": {"new_value": 1}},
    ]
    rs = RunState.rebuild(events, run_id="REQ-X")

    assert rs.state == "running", f"state 应被 loop_iteration_completed 拉回 running，实际 {rs.state!r}"
    assert rs.current_node == "dev-loop", "current_node 应保留为 loop 节点"
    assert rs.loop_counters["dev-loop"] == 1


# ============================================================================
# TC-SLI-7：e2e 闭环——dispatch → save continue → dispatch → save all_done → dispatch 终止
# ============================================================================

def test_e2e_loop_dispatch_save_continue_all_done(tmp_path: Path) -> None:
    run_id = "REQ-2026-009"
    _req_dir, jsonl = _bootstrap_run_dir(tmp_path, run_id)

    node = {
        "id": "dev-loop",
        "loop": {
            "prompt": "iter $LOOP_ITERATION",
            "interactive": True,
            "max_iterations": 5,
        },
    }

    # ── 第 1 轮：dispatch → awaiting_claude_action（counter=0）
    rs = RunState(run_id=run_id, state="running")
    res1 = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)
    assert res1.outcome == "awaiting_claude_action"

    # ── Claude 干完活 → save continue
    rc = save_main([
        "--run", run_id, "--node", "dev-loop",
        "--kind", "loop_iteration", "--output", '{"outcome":"continue"}',
        "--repo-root", str(tmp_path),
    ])
    assert rc == 0

    # ── rebuild 后 state=running、counter=1
    events, _ = read_events(jsonl)
    rs = RunState.rebuild(events, run_id=run_id)
    assert rs.state == "running"
    assert rs.loop_counters["dev-loop"] == 1

    # ── 第 2 轮：dispatch → awaiting_claude_action（counter=1，prompt 含 "iter 1"）
    res2 = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)
    assert res2.outcome == "awaiting_claude_action"
    events, _ = read_events(jsonl)
    nr = [e for e in events if e["type"] == "node_ready"][-1]
    assert nr["data"]["loop_iteration"] == 1
    assert "iter 1" in nr["data"]["prompt"]

    # ── Claude 报 all_done
    rc = save_main([
        "--run", run_id, "--node", "dev-loop",
        "--kind", "loop_iteration", "--output", '{"outcome":"all_done"}',
        "--repo-root", str(tmp_path),
    ])
    assert rc == 0

    # ── 第 3 轮 dispatch：看到 last outcome=all_done → loop_done
    events, _ = read_events(jsonl)
    rs = RunState.rebuild(events, run_id=run_id)
    res3 = _dispatch_loop_node(node, {}, rs, jsonl, root=tmp_path)
    assert res3.outcome == "loop_done"

    events = _read_events_raw(jsonl)
    types = [e["type"] for e in events]
    # 完整事件序列应包含两轮的 started + node_ready，最终 loop_completed + node_completed
    assert types.count("loop_iteration_started") == 2
    assert types.count("node_ready") == 2
    assert types.count("loop_iteration_completed") == 2
    assert "loop_completed" in types
    # 最终 node_completed 必须 loop_done:true
    nc = [e for e in events if e["type"] == "node_completed"][-1]
    assert nc["data"]["loop_done"] is True
