"""F-003 · last_event_ts 语义复用 + heartbeat 隐式更新 · 验收测试。

覆盖 4 条 acceptance criteria（AC-A3）：
- AC-1：append_event 不传 ts → 自动塞 ISO8601 UTC ts
- AC-2：append_events 批量 5 条 → 每条都被塞 ts（若未传）
- AC-3：RunState.rebuild 读 5 条事件 → state.last_event_ts == 最后一条事件的 ts
- AC-4：node_ready 事件不被排除在 last_event_ts 更新外（与既有事件等同）

测试运行：
    python3 -m pytest tests/lib/test_run_state_last_ts.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from run_state import RunState, append_event  # noqa: E402
from append_events import append_events  # noqa: E402

# ISO8601 UTC 格式正则：YYYY-MM-DDTHH:MM:SSZ
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _is_valid_ts(ts: str) -> bool:
    """校验 ts 是否符合 ISO8601 UTC 格式。"""
    return bool(_TS_RE.match(ts))


# ============================================================================
# AC-1：append_event 不传 ts → 自动塞 ISO8601 UTC ts
# ============================================================================

def test_append_event_自动补ts(tmp_path):
    """AC-1：调用 append_event 时不传 ts，写入后读回的事件应含合法 ts。"""
    jsonl = tmp_path / "run-state.jsonl"
    event = {"type": "workflow_started", "run_id": "R-AC1"}
    # 确认调用前无 ts
    assert "ts" not in event

    append_event(jsonl, event)

    # append_event 对传入 dict 做 in-place mutate
    assert "ts" in event, "append_event 未向 event dict 写入 ts 字段"
    assert _is_valid_ts(event["ts"]), f"ts 格式不合规：{event['ts']!r}"


# ============================================================================
# AC-2：append_events 批量 5 条 → 每条都被塞 ts
# ============================================================================

def test_append_events_批量自动补ts(tmp_path):
    """AC-2：append_events 批量写入 5 条无 ts 事件，每条均应被自动塞 ISO8601 UTC ts。"""
    jsonl = tmp_path / "run-state.jsonl"
    events = [
        {"type": "workflow_started", "run_id": "R-AC2", "data": {"workflow_name": "wf"}},
        {"type": "node_started", "node_id": "step-1"},
        {"type": "node_ready", "node_id": "step-1",
         "data": {"node_kind": "prompt", "external_action_contract": {}}},
        {"type": "node_completed", "node_id": "step-1", "data": {"output": "ok"}},
        {"type": "workflow_completed", "data": {}},
    ]
    assert len(events) == 5
    for e in events:
        assert "ts" not in e, f"测试前置条件：事件不应含 ts，实际 {e}"

    append_events(jsonl, events)

    for i, e in enumerate(events):
        assert "ts" in e, f"第 {i} 条事件（type={e['type']!r}）未被补 ts"
        assert _is_valid_ts(e["ts"]), f"第 {i} 条事件 ts 格式不合规：{e['ts']!r}"


# ============================================================================
# AC-3：RunState.rebuild 读 5 条事件 → last_event_ts == 最后一条事件的 ts
# ============================================================================

def test_rebuild_last_event_ts_等于最后事件ts():
    """AC-3：rebuild 5 条带 ts 的事件后，state.last_event_ts 应等于最后一条事件的 ts。"""
    events = [
        {"type": "workflow_started", "run_id": "R-AC3", "ts": "2026-05-14T01:00:00Z",
         "data": {"workflow_name": "wf"}},
        {"type": "node_started", "node_id": "step-1", "ts": "2026-05-14T01:01:00Z"},
        {"type": "node_completed", "node_id": "step-1", "ts": "2026-05-14T01:02:00Z",
         "data": {"output": "ok"}},
        {"type": "node_started", "node_id": "step-2", "ts": "2026-05-14T01:03:00Z"},
        {"type": "node_completed", "node_id": "step-2", "ts": "2026-05-14T01:04:00Z",
         "data": {"output": "done"}},
    ]
    last_ts = events[-1]["ts"]

    state = RunState.rebuild(events, run_id="R-AC3")

    assert state.last_event_ts == last_ts, (
        f"期望 last_event_ts={last_ts!r}，实际 {state.last_event_ts!r}"
    )


# ============================================================================
# AC-4：node_ready 事件不被排除在 last_event_ts 更新外
# ============================================================================

def test_rebuild_node_ready_更新last_event_ts():
    """AC-4：node_ready 事件应同普通事件一样更新 last_event_ts，不被跳过。"""
    events = [
        {"type": "workflow_started", "run_id": "R-AC4", "ts": "2026-05-14T02:00:00Z",
         "data": {"workflow_name": "wf"}},
        {"type": "node_started", "node_id": "gate", "ts": "2026-05-14T02:01:00Z"},
        {"type": "node_ready", "node_id": "gate", "ts": "2026-05-14T02:02:00Z",
         "data": {"node_kind": "skill", "external_action_contract": {}}},
    ]
    expected_ts = "2026-05-14T02:02:00Z"  # node_ready 事件的 ts

    state = RunState.rebuild(events, run_id="R-AC4")

    assert state.last_event_ts == expected_ts, (
        f"node_ready 事件的 ts 未更新到 last_event_ts；"
        f"期望 {expected_ts!r}，实际 {state.last_event_ts!r}"
    )
    # 同时验证 node_ready 的业务副作用正常（与 ts 更新不互斥）
    assert state.state == "awaiting_claude_action", (
        f"node_ready 后 state 应为 awaiting_claude_action，实际 {state.state}"
    )
    assert state.current_node == "gate", (
        f"node_ready 后 current_node 应为 gate，实际 {state.current_node}"
    )
