"""F-011 · _dispatch_loop_node / _dispatch_sub_workflow_node 单元测试。

覆盖：
- TC-F11-1：loop 节点 loop_continue 路径（迭代 < max_iterations）
- TC-F11-2：loop 节点 loop_done 路径（迭代 >= max_iterations）
- TC-F11-3：loop 事件写入包含 iteration 字段（RunState.rebuild 可消费）
- TC-F11-4：sub_workflow 节点 sub_workflow_pending outcome
- TC-F11-5：sub_workflow 节点子 run 目录建在 run_dir/sub_runs/<node_id>/

测试运行：
    python3 -m pytest tests/lib/test_workflow_dispatcher_f011.py -v
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from run_state import RunState  # noqa: E402
from workflow_dispatcher import (  # noqa: E402
    DispatchResult,
    _dispatch_loop_node,
    _dispatch_sub_workflow_node,
)


# ============================================================================
# 公共 fixture
# ============================================================================

@pytest.fixture
def tmp_jsonl(tmp_path: Path) -> Path:
    """提供临时 jsonl 文件路径（不预先创建，append_event 会自动创建）。"""
    return tmp_path / "run-state.jsonl"


def _make_run_state(loop_counters: dict[str, int] | None = None) -> RunState:
    """构造含指定 loop_counters 的 RunState。"""
    rs = RunState(run_id="REQ-2026-010")
    if loop_counters:
        rs.loop_counters = dict(loop_counters)
    return rs


def _read_events(jsonl_path: Path) -> list[dict]:
    """从 jsonl 文件读取所有事件行。"""
    if not jsonl_path.exists():
        return []
    events = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


# ============================================================================
# TC-F11-1：loop 节点第一轮（loop_continue，iteration=0，max_iterations=3）
# ============================================================================

def test_loop_continue_first_iteration(tmp_jsonl: Path) -> None:
    """首轮 dispatch：loop_counters 无 node_id → 当前 iteration=0，outcome=loop_continue。"""
    node = {"id": "review-loop", "loop": {"max_iterations": 3}}
    run_state = _make_run_state()  # loop_counters 为空

    result = _dispatch_loop_node(node, {}, run_state, tmp_jsonl)

    assert result.outcome == "loop_continue", f"首轮应 loop_continue，实际 {result.outcome}"
    assert result.error is None


def test_loop_continue_second_iteration(tmp_jsonl: Path) -> None:
    """第二轮 dispatch（loop_counters["review-loop"]=1）：iteration=1，outcome=loop_continue。"""
    node = {"id": "review-loop", "loop": {"max_iterations": 3}}
    run_state = _make_run_state({"review-loop": 1})

    result = _dispatch_loop_node(node, {}, run_state, tmp_jsonl)

    assert result.outcome == "loop_continue", f"第二轮应 loop_continue，实际 {result.outcome}"


# ============================================================================
# TC-F11-2：loop 节点最后一轮（loop_done）
# ============================================================================

def test_loop_done_at_max_iterations(tmp_jsonl: Path) -> None:
    """当 current_iteration + 1 >= max_iterations 时 outcome=loop_done。"""
    node = {"id": "review-loop", "loop": {"max_iterations": 3}}
    # loop_counters["review-loop"]=2 → current_iteration=2，2+1=3 >= 3 → loop_done
    run_state = _make_run_state({"review-loop": 2})

    result = _dispatch_loop_node(node, {}, run_state, tmp_jsonl)

    assert result.outcome == "loop_done", f"应 loop_done，实际 {result.outcome}"


def test_loop_done_max_iterations_one(tmp_jsonl: Path) -> None:
    """max_iterations=1：首次 dispatch 即为最后一轮，应 loop_done。"""
    node = {"id": "single-loop", "loop": {"max_iterations": 1}}
    run_state = _make_run_state()  # iteration=0，0+1=1 >= 1 → loop_done

    result = _dispatch_loop_node(node, {}, run_state, tmp_jsonl)

    assert result.outcome == "loop_done"


# ============================================================================
# TC-F11-3：loop 事件写入含 iteration 字段，RunState.rebuild 可正确消费
# ============================================================================

def test_loop_events_written_with_iteration_field(tmp_jsonl: Path) -> None:
    """_dispatch_loop_node 写入 loop_iteration_started / loop_iteration_completed，
    两者均含 data.iteration；RunState.rebuild 后 loop_counters 正确累计。"""
    node = {"id": "check-loop", "loop": {"max_iterations": 5}}
    run_state = _make_run_state({"check-loop": 2})  # 第三轮（iteration=2）

    _dispatch_loop_node(node, {}, run_state, tmp_jsonl)

    events = _read_events(tmp_jsonl)
    loop_events = [e for e in events if e.get("type") in (
        "loop_iteration_started", "loop_iteration_completed"
    )]
    assert len(loop_events) == 2, f"应写 2 条 loop 事件，实际 {len(loop_events)}"
    for evt in loop_events:
        assert "iteration" in (evt.get("data") or {}), (
            f"事件 {evt['type']} 缺少 data.iteration"
        )
        assert evt["data"]["iteration"] == 2


def test_loop_counters_rebuilt_from_events(tmp_jsonl: Path) -> None:
    """连续 dispatch 两轮后，用 RunState.rebuild 重建 loop_counters 应等于最后 iteration。"""
    node_id = "iter-node"
    node = {"id": node_id, "loop": {"max_iterations": 5}}

    # 第 0 轮
    rs0 = _make_run_state()
    _dispatch_loop_node(node, {}, rs0, tmp_jsonl)

    # 第 1 轮（模拟 workflow_continue 递增后的 loop_counters）
    rs1 = _make_run_state({node_id: 1})
    _dispatch_loop_node(node, {}, rs1, tmp_jsonl)

    # 从写入的 jsonl 重建 RunState
    import run_state as rs_mod  # noqa: PLC0415
    events, _ = rs_mod.read_events(tmp_jsonl)
    rebuilt = RunState.rebuild(events, run_id="REQ-2026-010")

    # 最后一条 loop_iteration_completed.data.iteration = 1
    assert rebuilt.loop_counters.get(node_id) == 1, (
        f"rebuild 后 loop_counters[{node_id!r}] 应为 1，实际 {rebuilt.loop_counters}"
    )


# ============================================================================
# TC-F11-4 / P2（codex 2026-05-12）：sub_workflow 直接落在 sub_runs/<node_id>/，
# 不再走 workflow_run.main 另起 runs/<auto_id>/
# ============================================================================

def _make_fake_template(root: Path, template_id: str = "standard-8phase",
                       category: str = "requirement") -> Path:
    """在 tmp_path/.claude/workflows/<category>/<id>.yaml 写一份占位模板。

    P2 修订后 _dispatch_sub_workflow_node 只校验模板文件存在，不再 load_workflow。
    """
    target_dir = root / ".claude" / "workflows" / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{template_id}.yaml"
    target.write_text(
        "schema_version: '1.0'\nname: " + template_id + "\ncategory: " + category + "\n",
        encoding="utf-8",
    )
    return target


def test_sub_workflow_pending_outcome(tmp_path: Path, tmp_jsonl: Path) -> None:
    """_dispatch_sub_workflow_node 应返回 outcome=sub_workflow_pending。"""
    _make_fake_template(tmp_path)
    node = {"id": "sub-req", "sub_workflow": {"template": "standard-8phase"}}
    run_dir = tmp_path / "runs" / "RUN-20260512-001"
    run_dir.mkdir(parents=True)
    rs = _make_run_state()

    result = _dispatch_sub_workflow_node(node, rs, run_dir, tmp_path, tmp_jsonl)
    assert result.outcome == "sub_workflow_pending", f"应 sub_workflow_pending，实际 {result.outcome}"


def test_sub_workflow_missing_template_raises(tmp_path: Path, tmp_jsonl: Path) -> None:
    """sub_workflow 字段缺 template 应触发 WorkflowError。"""
    from common import WorkflowError  # noqa: PLC0415

    node = {"id": "bad-sub", "sub_workflow": {}}  # 缺 template
    run_dir = tmp_path / "runs" / "RUN-20260512-002"
    run_dir.mkdir(parents=True)
    rs = _make_run_state()

    with pytest.raises(WorkflowError, match="缺少 template 字段"):
        _dispatch_sub_workflow_node(node, rs, run_dir, tmp_path, tmp_jsonl)


def test_sub_workflow_unknown_template_raises(tmp_path: Path, tmp_jsonl: Path) -> None:
    """template 指向不存在的 yaml 时抛 WorkflowError。"""
    from common import WorkflowError  # noqa: PLC0415

    node = {"id": "ghost-sub", "sub_workflow": {"template": "no-such-template"}}
    run_dir = tmp_path / "runs" / "RUN-20260512-005"
    run_dir.mkdir(parents=True)
    rs = _make_run_state()

    with pytest.raises(WorkflowError, match="未在 .claude/workflows/ 找到"):
        _dispatch_sub_workflow_node(node, rs, run_dir, tmp_path, tmp_jsonl)


# ============================================================================
# TC-F11-5：sub_workflow 子 run 目录建在 run_dir/sub_runs/<node_id>/
# ============================================================================

def test_sub_workflow_creates_sub_run_dir(tmp_path: Path, tmp_jsonl: Path) -> None:
    """子 run 目录必须建在 run_dir/sub_runs/<node_id>/（与 workflow_status 约定一致）。"""
    _make_fake_template(tmp_path)
    node_id = "phase-sub"
    node = {"id": node_id, "sub_workflow": {"template": "standard-8phase"}}
    run_dir = tmp_path / "runs" / "RUN-20260512-003"
    run_dir.mkdir(parents=True)
    expected_sub_dir = run_dir / "sub_runs" / node_id
    rs = _make_run_state()

    _dispatch_sub_workflow_node(node, rs, run_dir, tmp_path, tmp_jsonl)
    assert expected_sub_dir.exists(), f"子 run 目录 {expected_sub_dir} 未被创建"


def test_sub_workflow_writes_meta_and_jsonl_directly_into_sub_run_dir(
    tmp_path: Path, tmp_jsonl: Path,
) -> None:
    """P2 修订关键回归：sub_runs/<node_id>/ 内必须含 meta.yaml + run-state.jsonl，
    顶层 runs/ 不应被污染（不再调 workflow_run.main 另起 runs/<auto_id>/）。"""
    import yaml as _yaml  # noqa: PLC0415

    _make_fake_template(tmp_path)
    node_id = "real-sub"
    node = {
        "id": node_id,
        "sub_workflow": {"template": "standard-8phase", "args": "demo arg"},
    }
    parent_run_dir = tmp_path / "runs" / "PARENT-001"
    parent_run_dir.mkdir(parents=True)
    rs = _make_run_state()
    rs.run_id = "PARENT-001"

    _dispatch_sub_workflow_node(node, rs, parent_run_dir, tmp_path, tmp_jsonl)

    # sub_runs/<node_id>/ 含 meta.yaml + run-state.jsonl
    sub_dir = parent_run_dir / "sub_runs" / node_id
    meta_path = sub_dir / "meta.yaml"
    jsonl_path = sub_dir / "run-state.jsonl"
    assert meta_path.is_file(), f"sub meta.yaml 未写入：{meta_path}"
    assert jsonl_path.is_file(), f"sub run-state.jsonl 未写入：{jsonl_path}"

    # meta key 与 _run_generic 对齐（template_path 而非 workflow_template_path）
    meta = _yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    assert meta["run_id"] == node_id, "sub_run_id 应等于 node_id（status/rollback 约定）"
    assert meta["template"] == "standard-8phase"
    assert meta["template_path"].endswith(".yaml")
    assert meta["arguments"] == "demo arg"
    assert meta["parent_run_id"] == "PARENT-001", "meta 必须带 parent_run_id 供追溯"
    assert meta["state"] == "running"

    # jsonl 含 workflow_started 事件，data.parent_run_id 同步
    events = _read_events(jsonl_path)
    types = [e["type"] for e in events]
    assert "workflow_started" in types, f"jsonl 缺 workflow_started，实际 {types}"
    started = next(e for e in events if e["type"] == "workflow_started")
    assert started["run_id"] == node_id
    assert started["data"]["workflow_name"] == "standard-8phase"
    assert started["data"]["parent_run_id"] == "PARENT-001"

    # 顶层 runs/ 不应被污染（P2 关键回归）
    top_runs = tmp_path / "runs"
    sibling_runs = [p.name for p in top_runs.iterdir() if p.is_dir()]
    assert sibling_runs == ["PARENT-001"], (
        f"顶层 runs/ 不应再生成 RUN-<auto>/ 兄弟目录，实际 {sibling_runs}"
    )


# ============================================================================
# codex P1-2（2026-05-12）：sub_workflow 重复派发守卫
# ============================================================================

def test_sub_workflow_dispatch_guard_skips_when_marker_exists(
    tmp_path: Path, tmp_jsonl: Path,
) -> None:
    """二次进入同一 sub_workflow 节点时，标记文件存在 → 跳过 meta + jsonl 重写。"""
    _make_fake_template(tmp_path)
    node_id = "guarded-sub"
    node = {"id": node_id, "sub_workflow": {"template": "standard-8phase"}}
    run_dir = tmp_path / "runs" / "RUN-20260512-P12"
    run_dir.mkdir(parents=True)
    rs = _make_run_state()

    # 第 1 次派发：写 meta + jsonl + .dispatched 标记
    r1 = _dispatch_sub_workflow_node(node, rs, run_dir, tmp_path, tmp_jsonl)
    assert r1.outcome == "sub_workflow_pending"

    sub_dir = run_dir / "sub_runs" / node_id
    marker = sub_dir / ".dispatched"
    jsonl_path = sub_dir / "run-state.jsonl"
    assert marker.exists()
    events_after_first = _read_events(jsonl_path)
    assert len(events_after_first) == 1, "首次派发应写 1 条 workflow_started"

    # 第 2 次派发：标记存在 → 不再追加事件
    r2 = _dispatch_sub_workflow_node(node, rs, run_dir, tmp_path, tmp_jsonl)
    assert r2.outcome == "sub_workflow_pending"
    events_after_second = _read_events(jsonl_path)
    assert len(events_after_second) == 1, (
        f"二次派发不应追加新事件（守卫失效），实际事件数 {len(events_after_second)}"
    )
    assert marker.read_text(encoding="utf-8") == "standard-8phase"


def test_sub_workflow_dispatch_template_missing_does_not_write_marker(
    tmp_path: Path, tmp_jsonl: Path,
) -> None:
    """模板不存在抛 WorkflowError 时，标记文件不应被写——保证 fix 后调用方可以 retry。"""
    from common import WorkflowError  # noqa: PLC0415

    node_id = "retry-sub"
    node = {"id": node_id, "sub_workflow": {"template": "missing-template"}}
    run_dir = tmp_path / "runs" / "RUN-20260512-P12B"
    run_dir.mkdir(parents=True)
    rs = _make_run_state()

    with pytest.raises(WorkflowError, match="未在 .claude/workflows/ 找到"):
        _dispatch_sub_workflow_node(node, rs, run_dir, tmp_path, tmp_jsonl)

    marker = run_dir / "sub_runs" / node_id / ".dispatched"
    assert not marker.exists(), (
        f"模板缺失路径不应写入标记 {marker}，否则补建模板后 retry 会被守卫错跳过"
    )


# ============================================================================
# TC-F11-6：loop 节点连续 N 次序列断言（features.json F-011 acceptance #1）
# ============================================================================

def test_loop_dispatch_until_done_sequence(tmp_jsonl: Path) -> None:
    """max_iterations=3 时连续调用应产生 [loop_continue, loop_continue, loop_done] 序列。

    每次调用之间模拟 workflow_continue.py:266 的 loop_counters[node_id] += 1 行为。
    断言 outcomes 列表与 acceptance #1 要求的 [loop_continue]*(N-1) + [loop_done] 一致。
    """
    node_id = "seq-loop"
    node = {"id": node_id, "loop": {"max_iterations": 3}}
    outcomes: list[str] = []

    run_state = _make_run_state()  # loop_counters 初始为空（iteration=0）
    for _ in range(3):
        result = _dispatch_loop_node(node, {}, run_state, tmp_jsonl)
        outcomes.append(result.outcome)
        # 模拟 workflow_continue.py:266 内存递增（iteration +1）
        run_state.loop_counters[node_id] = run_state.loop_counters.get(node_id, 0) + 1

    assert outcomes == ["loop_continue", "loop_continue", "loop_done"], (
        f"连续 3 轮 outcome 序列错误，期望 ['loop_continue', 'loop_continue', 'loop_done']，实际 {outcomes}"
    )


# ============================================================================
# IB-21b · _dispatch_node_by_type_key 未知节点类型抛 WorkflowError
# ============================================================================

def test_dispatch_node_unknown_type_returns_failed(tmp_path: Path, tmp_jsonl: Path) -> None:
    """IB-21b：未知节点类型（无 agent/skill/prompt/.../artifact 键）→ outcome=failed + jsonl 含 node_failed。

    dispatch_node 应捕获 _dispatch_node_by_type_key 抛出的 WorkflowError，
    写 node_failed 事件并返回 outcome=failed（不向外传播异常）。
    """
    import json
    from common import WorkflowError
    from workflow_dispatcher import _dispatch_node_by_type_key, dispatch_node

    node_id = "unknown-node-type"
    node = {"id": node_id, "unknown_key": "something"}
    rs = _make_run_state()

    # dispatch_node 主入口：应返回 outcome=failed（内部吃掉 WorkflowError）
    result = dispatch_node(node, rs, run_dir=tmp_path, root=tmp_path, env={}, jsonl_path=tmp_jsonl)
    assert result.outcome == "failed", f"未知节点类型应返回 failed，实际 {result.outcome!r}"
    assert "未知节点类型" in (result.error or ""), (
        f"error 消息应含 '未知节点类型'，实际 {result.error!r}"
    )

    # jsonl 里应有 node_failed 事件
    lines = tmp_jsonl.read_text(encoding="utf-8").splitlines()
    events = [json.loads(ln) for ln in lines if ln.strip()]
    failed_events = [e for e in events if e.get("type") == "node_failed"]
    assert len(failed_events) == 1, f"期望 1 条 node_failed，实际 {len(failed_events)}"
    assert failed_events[0].get("node_id") == node_id

    # _dispatch_node_by_type_key 直接调：应抛 WorkflowError
    with pytest.raises(WorkflowError, match="未知节点类型"):
        _dispatch_node_by_type_key(node, rs, tmp_path, tmp_path, {}, tmp_jsonl)
