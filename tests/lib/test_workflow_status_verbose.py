"""F-009 · workflow_status --verbose + stale 检测 + 树形分类输出 单元测试。

覆盖：
  AC-1: 五行分类输出（done/ready/running/awaiting/blocked）
  AC-2: blocked reason 三枚举（incomplete_dispatch/awaiting_deps/awaiting_claude_action）
  AC-3: awaiting kind 两枚举（skill_result/approval_repair）
  AC-4: stale WARN（mock last_event_ts 为 30+ 分钟前）
  AC-5: env override CLAUDE_WORKFLOW_STALE_MINUTES=1 + 2 分钟前 ts → stale
  AC-6: 无 --verbose 与原 _render_status 输出一致
  边界: last_event_ts=None → 不 WARN; ts 非法 ISO → 不 WARN; workflow=None fail-soft

测试运行：
    python3 -m pytest tests/lib/test_workflow_status_verbose.py -v
"""
from __future__ import annotations

import datetime
import importlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import workflow_status  # noqa: E402
from workflow_status import (  # noqa: E402
    _is_stale,
    _infer_awaiting_kind,
    _blocked_reason,
    _render_status,
    _render_status_verbose,
    main,
)
from run_state import RunState  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_run_dir(tmp_path: Path, run_id: str, events: list[dict]) -> Path:
    """在 tmp_path/runs/<run_id>/ 下建最小 run 环境。"""
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    jsonl = run_dir / "run-state.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return run_dir


def _make_workflow(nodes: list[dict], explicit: bool = True) -> dict:
    """构造最小 workflow dict。"""
    return {"depends_on_explicit": explicit, "nodes": nodes}


def _ts_ago(minutes: int) -> str:
    """返回 minutes 分钟前的 UTC ISO 8601 字符串（带 Z 后缀）。"""
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_ago_iso(minutes: int) -> str:
    """返回 minutes 分钟前的 UTC ISO 8601（+00:00 格式）。"""
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return dt.isoformat()


def _build_run_state(events: list[dict], run_id: str = "TEST-RUN") -> RunState:
    from run_state import RunState
    return RunState.rebuild(events, run_id=run_id)


# ---------------------------------------------------------------------------
# AC-1: 五行分类输出
# ---------------------------------------------------------------------------

def test_verbose_five_category_lines(tmp_path):
    """_render_status_verbose 输出含 ready/running/awaiting/blocked/done 五行。"""
    run_id = "TEST-001"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "wf"}},
        {"type": "node_completed", "node_id": "N1", "ts": "2026-05-14T00:01:00Z",
         "data": {"output": "ok"}},
        {"type": "node_started", "node_id": "N2", "ts": "2026-05-14T00:02:00Z"},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    run_state = _build_run_state(events, run_id)
    workflow = _make_workflow([
        {"id": "N1", "depends_on": []},
        {"id": "N2", "depends_on": ["N1"]},
        {"id": "N3", "depends_on": ["N2"]},
    ])
    output = _render_status_verbose(run_state, run_dir, workflow)

    assert "ready (" in output
    assert "running (" in output
    assert "awaiting (" in output
    assert "blocked (" in output
    assert "done (" in output


def test_verbose_done_contains_completed_node(tmp_path):
    """done 行应包含 node_completed 的节点。"""
    run_id = "TEST-002"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "wf"}},
        {"type": "node_completed", "node_id": "N1", "ts": "2026-05-14T00:01:00Z",
         "data": {"output": "ok"}},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    run_state = _build_run_state(events, run_id)
    workflow = _make_workflow([{"id": "N1", "depends_on": []}])
    output = _render_status_verbose(run_state, run_dir, workflow)
    assert "N1" in output
    assert "done (1)" in output


# ---------------------------------------------------------------------------
# AC-2: blocked reason 三枚举
# ---------------------------------------------------------------------------

def test_blocked_reason_awaiting_deps():
    """依赖未满足 → reason=awaiting_deps，extra 含 deps 列表。"""
    run_state = _build_run_state([
        {"type": "workflow_started", "run_id": "T", "ts": "2026-01-01T00:00:00Z",
         "data": {"workflow_name": "wf"}},
    ])
    node = {"id": "N2", "depends_on": ["N1"]}
    reason, extra = _blocked_reason("N2", node, run_state, done_ids=set(), running_ids=set())
    assert reason == "awaiting_deps"
    assert "N1" in extra


def test_blocked_reason_incomplete_dispatch(tmp_path):
    """node_outputs 中 state=running 且不是 current_node → reason=incomplete_dispatch。"""
    run_state = RunState(
        run_id="T",
        state="running",
        current_node="N2",
        node_outputs={"N1": {"state": "running", "output": "", "data": {}}},
    )
    node = {"id": "N1", "depends_on": []}
    reason, extra = _blocked_reason("N1", node, run_state, done_ids=set(), running_ids={"N2"})
    assert reason == "incomplete_dispatch"
    assert "N1" in extra


def test_blocked_reason_awaiting_claude_action():
    """run_state.state=awaiting_claude_action + 无 unmet deps → reason=awaiting_claude_action。"""
    run_state = RunState(
        run_id="T",
        state="awaiting_claude_action",
        current_node="N1",
    )
    node = {"id": "N2", "depends_on": []}
    reason, extra = _blocked_reason("N2", node, run_state, done_ids={"N1"}, running_ids=set())
    assert reason == "awaiting_claude_action"


def test_verbose_blocked_incomplete_dispatch_in_output(tmp_path):
    """_render_status_verbose 输出含 incomplete_dispatch 字样（AC-9 前置单测）。"""
    run_id = "TEST-003"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "wf"}},
        {"type": "node_started", "node_id": "N1", "ts": "2026-05-14T00:01:00Z"},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    # 手工构造 node_outputs 含 running state 但 current_node 不同
    run_state = RunState(
        run_id=run_id,
        state="running",
        current_node="N2",
        node_outputs={"N1": {"state": "running", "output": "", "data": {}}},
    )
    workflow = _make_workflow([
        {"id": "N1", "depends_on": []},
        {"id": "N2", "depends_on": []},
    ])
    output = _render_status_verbose(run_state, run_dir, workflow)
    assert "incomplete_dispatch" in output


# ---------------------------------------------------------------------------
# AC-3: awaiting kind 两枚举
# ---------------------------------------------------------------------------

def test_infer_awaiting_kind_skill_result(tmp_path):
    """末位事件 node_ready → kind=skill_result。"""
    run_id = "TEST-KIND-SR"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "wf"}},
        {"type": "node_ready", "node_id": "N1", "ts": "2026-05-14T00:01:00Z"},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    kind = _infer_awaiting_kind(run_dir)
    assert kind == "skill_result"


def test_infer_awaiting_kind_approval_repair(tmp_path):
    """末位事件 approval_repair_started → kind=approval_repair。"""
    run_id = "TEST-KIND-AR"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "wf"}},
        {"type": "approval_repair_started", "node_id": "N1", "ts": "2026-05-14T00:01:00Z"},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    kind = _infer_awaiting_kind(run_dir)
    assert kind == "approval_repair"


def test_verbose_awaiting_kind_in_output(tmp_path):
    """_render_status_verbose 输出含 kind= 字样（awaiting 节点）。"""
    run_id = "TEST-004"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "wf"}},
        {"type": "node_ready", "node_id": "N1", "ts": "2026-05-14T00:01:00Z"},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    run_state = _build_run_state(events, run_id)
    workflow = _make_workflow([{"id": "N1", "depends_on": []}])
    output = _render_status_verbose(run_state, run_dir, workflow)
    assert "kind=" in output


# ---------------------------------------------------------------------------
# AC-4: stale WARN
# ---------------------------------------------------------------------------

def test_is_stale_returns_true_when_old():
    """30 分钟前 ts，threshold=30 → True。"""
    ts = _ts_ago(31)
    assert _is_stale(ts, 30) is True


def test_is_stale_returns_false_when_fresh():
    """1 分钟前 ts，threshold=30 → False。"""
    ts = _ts_ago(1)
    assert _is_stale(ts, 30) is False


def test_verbose_stale_warn_in_output(tmp_path):
    """last_event_ts 为 31 分钟前 → 输出含 WARN: stale heartbeat。"""
    run_id = "TEST-STALE"
    ts = _ts_ago(31)
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": ts,
         "data": {"workflow_name": "wf"}},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    run_state = _build_run_state(events, run_id)
    # 强制 STALE_THRESHOLD_MINUTES=30
    import workflow_status as ws
    orig = ws.STALE_THRESHOLD_MINUTES
    ws.STALE_THRESHOLD_MINUTES = 30
    try:
        output = _render_status_verbose(run_state, run_dir, None)
    finally:
        ws.STALE_THRESHOLD_MINUTES = orig
    assert "WARN: stale heartbeat" in output


# ---------------------------------------------------------------------------
# AC-5: env override
# ---------------------------------------------------------------------------

def test_stale_env_override(monkeypatch, tmp_path):
    """env CLAUDE_WORKFLOW_STALE_MINUTES=1 + 2 分钟前 ts → stale。"""
    monkeypatch.setenv("CLAUDE_WORKFLOW_STALE_MINUTES", "1")
    # 重新加载模块以触发模块级常量重解析
    importlib.reload(workflow_status)
    ts = _ts_ago(2)
    assert _is_stale(ts, workflow_status.STALE_THRESHOLD_MINUTES) is True


def test_stale_env_override_not_stale_with_fresh_ts(monkeypatch):
    """env CLAUDE_WORKFLOW_STALE_MINUTES=1 + 30 秒前 ts → 不 stale。"""
    ts = _ts_ago_iso(0)  # 刚刚（0 分钟前）
    assert _is_stale(ts, 1) is False


# ---------------------------------------------------------------------------
# AC-6: 无 --verbose 与原 _render_status 输出一致
# ---------------------------------------------------------------------------

def test_no_verbose_output_matches_render_status(tmp_path, capsys):
    """main() 无 --verbose 时输出等同于 _render_status 直接调用。"""
    run_id = "TEST-NOVERB"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "wf"}},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    # 构造 runs/ 目录被 _resolve_run_dir 识别
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(exist_ok=True)

    main([run_id, "--verbose"], repo_root=tmp_path)
    captured_verbose = capsys.readouterr().out

    rc2 = main([run_id], repo_root=tmp_path)
    captured_plain = capsys.readouterr().out

    from run_state import read_events, RunState
    evts, warns = read_events(run_dir / "run-state.jsonl")
    rs = RunState.rebuild(evts, run_id=run_id, warnings=warns)
    expected = _render_status(rs, run_dir) + "\n"

    assert captured_plain == expected
    assert rc2 == 0
    # verbose 输出应包含 plain 输出的内容（子集关系）
    assert captured_plain.strip() in captured_verbose


# ---------------------------------------------------------------------------
# 边界：last_event_ts=None → 不 WARN
# ---------------------------------------------------------------------------

def test_is_stale_none_ts():
    """last_event_ts=None → False，不输出 WARN。"""
    assert _is_stale(None, 30) is False


def test_verbose_no_stale_warn_when_ts_none(tmp_path):
    """空 jsonl（last_event_ts=None）→ 不输出 WARN。"""
    run_id = "TEST-NONE-TS"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run-state.jsonl").write_text("", encoding="utf-8")
    run_state = RunState(run_id=run_id, state="running", last_event_ts=None)
    output = _render_status_verbose(run_state, run_dir, None)
    assert "WARN: stale heartbeat" not in output


# ---------------------------------------------------------------------------
# 边界：ts 非法 ISO → 不 WARN
# ---------------------------------------------------------------------------

def test_is_stale_invalid_ts():
    """非法 ISO 字符串 → False（不抛异常）。"""
    assert _is_stale("not-a-timestamp", 30) is False


# ---------------------------------------------------------------------------
# 边界：workflow=None → fail-soft，只输出基础段
# ---------------------------------------------------------------------------

def test_verbose_fail_soft_when_workflow_none(tmp_path):
    """workflow=None 时 _render_status_verbose 应正常返回基础 status（不抛）。"""
    run_id = "TEST-FAILSOFT"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "wf"}},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    run_state = _build_run_state(events, run_id)
    output = _render_status_verbose(run_state, run_dir, None)
    assert "run_id" in output
    assert "state" in output
    # 不含节点分类行
    assert "ready (" not in output
