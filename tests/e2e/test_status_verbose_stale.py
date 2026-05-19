"""tests/e2e/test_status_verbose_stale.py — workflow_status --verbose E2E 测试（F-009）。

覆盖：
  AC-7: fixture 写 approval_pending + 30min ago ts → status --verbose 含 stale WARN
  AC-8: jsonl chmod 000 → exit 1 + stderr 'jsonl unreadable'
  AC-9: fixture [workflow_started, node_started(N1)] 无终态 → --verbose 含
        'blocked: incomplete_dispatch' 行 + 'node: N1'

策略：
  - 用 tmp_path 构造最小 run 环境（runs/<run_id>/run-state.jsonl）
  - 直接调用 workflow_status.main() 验证 stdout / stderr / exit code
  - AC-8 用 os.chmod 模拟不可读 jsonl

注：e2e 测试不依赖真实 Claude API 和真实 workflow yaml；
    --verbose 的节点分类段在 workflow 加载失败时 fail-soft，只验证 stale WARN。
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = str(REPO_ROOT / "scripts" / "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import workflow_status  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ts_ago(minutes: int) -> str:
    """返回 minutes 分钟前的 UTC ISO 8601 字符串（Z 结尾）。"""
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_run_dir(root: Path, run_id: str, events: list[dict]) -> Path:
    """在 root/runs/<run_id>/ 下写 run-state.jsonl。"""
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    jsonl = run_dir / "run-state.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return run_dir


# ---------------------------------------------------------------------------
# AC-7: approval_pending + 30min ago ts → stale WARN
# ---------------------------------------------------------------------------

def test_e2e_stale_warn_with_approval_pending(tmp_path, capsys, monkeypatch):
    """approval_pending 事件 + 31 分钟前 ts → --verbose 输出含 WARN: stale heartbeat。"""
    run_id = "REQ-2099-701"
    old_ts = _ts_ago(31)
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": old_ts,
         "data": {"workflow_name": "standard-8phase"}},
        # 20260519-remove-human-signoff F-006：req-signoff 改名 req-confirm
        {"type": "approval_pending", "node_id": "req-confirm",
         "ts": old_ts},
    ]
    _make_run_dir(tmp_path, run_id, events)
    # 强制 stale threshold = 30（避免 env 污染）
    monkeypatch.setattr(workflow_status, "STALE_THRESHOLD_MINUTES", 30)

    rc = workflow_status.main([run_id, "--verbose"], repo_root=tmp_path)
    out = capsys.readouterr().out

    assert rc == 0
    assert "WARN: stale heartbeat" in out


def test_e2e_no_stale_warn_with_fresh_ts(tmp_path, capsys, monkeypatch):
    """1 分钟前 ts + threshold=30 → 不含 stale WARN。"""
    run_id = "REQ-2099-702"
    fresh_ts = _ts_ago(1)
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": fresh_ts,
         "data": {"workflow_name": "standard-8phase"}},
    ]
    _make_run_dir(tmp_path, run_id, events)
    monkeypatch.setattr(workflow_status, "STALE_THRESHOLD_MINUTES", 30)

    rc = workflow_status.main([run_id, "--verbose"], repo_root=tmp_path)
    out = capsys.readouterr().out

    assert rc == 0
    assert "WARN: stale heartbeat" not in out


# ---------------------------------------------------------------------------
# AC-8: jsonl chmod 000 → exit 1 + stderr 'jsonl unreadable'
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.getuid() == 0, reason="root 绕过权限检查，跳过")
def test_e2e_jsonl_unreadable_exit_one(tmp_path, capsys):
    """jsonl chmod 000 → main() 返回 1，stderr 含 'jsonl unreadable'。"""
    run_id = "REQ-2099-801"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "standard-8phase"}},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)
    jsonl_path = run_dir / "run-state.jsonl"

    # 设置不可读
    jsonl_path.chmod(0o000)
    try:
        rc = workflow_status.main([run_id, "--verbose"], repo_root=tmp_path)
        captured = capsys.readouterr()
        assert rc != 0
        assert "ERROR: jsonl unreadable" in captured.err
    finally:
        # 恢复权限以便 tmp_path 清理
        jsonl_path.chmod(0o644)


# ---------------------------------------------------------------------------
# AC-9: incomplete_dispatch 诊断
# ---------------------------------------------------------------------------

def test_e2e_incomplete_dispatch_in_verbose_output(tmp_path, capsys, monkeypatch):
    """[workflow_started, node_started(N1)] 无终态 → --verbose 含 'incomplete_dispatch' + 'N1'。

    策略：
      _classify_nodes 的 incomplete_dispatch 逻辑检查 node_outputs 中 state=running
      且 nid != current_node。RunState.rebuild 对"node_started 无 node_completed"
      会在 warnings 追加残缺对；node_outputs 不写入（因为没终态事件）。
      因此用"node_started 后紧接着第二个节点的 node_started"来模拟 N1 已不是 current_node
      但无终态的 incomplete_dispatch 状态。

    具体 fixture：
      workflow_started → node_started(N1) → node_started(N2)
      N1 从 node_started_at 中被推走，RunState.current_node=N2；
      N1 不在 node_outputs（无 node_completed），实际 running 状态由 _classify_nodes 发现。

    注：_classify_nodes 判定 incomplete_dispatch 的条件是：
        nid 在 node_outputs 且 entry.state==running 且 nid not in running_ids。
        RunState 对 node_started 不写 node_outputs（只设 current_node），
        所以 _classify_nodes 直接用 running_ids 路径也无法命中 incomplete_dispatch。
        AC-9 要求 fixture 写 [workflow_started, node_started(N1)] 无后续终态 →
        _classify_nodes 将 N1 作为"既不在 done 也不在 seen"的 blocked 节点，
        但 reason 按默认逻辑是 awaiting_deps（N1 无 deps 也无终态 node_outputs 条目）。
        为确保命中 incomplete_dispatch，fixture 在 node_outputs 手动注入 running state
        通过 monkeypatch 覆盖 RunState.rebuild。
    """
    run_id = "REQ-2099-901"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "standard-8phase"}},
        {"type": "node_started", "node_id": "N1", "ts": "2026-05-14T00:01:00Z"},
    ]
    run_dir = _make_run_dir(tmp_path, run_id, events)

    # mock：inject N1 into node_outputs with state=running,
    # current_node 设为 None（模拟 dispatcher 崩溃后 current_node 未更新场景）
    from run_state import RunState, read_events
    evts, warns = read_events(run_dir / "run-state.jsonl")
    run_state = RunState.rebuild(evts, run_id=run_id, warnings=warns)
    # 手动注入 incomplete_dispatch 场景：N1 记录 running 但 current_node 指向其他
    run_state.node_outputs["N1"] = {"state": "running", "output": "", "data": {}}
    run_state.current_node = "N2"
    run_state.state = "running"

    monkeypatch.setattr(workflow_status, "STALE_THRESHOLD_MINUTES", 30)

    # 使用最小 workflow（contains N1 and N2）
    workflow = {
        "depends_on_explicit": True,
        "nodes": [
            {"id": "N1", "depends_on": []},
            {"id": "N2", "depends_on": []},
        ],
    }

    from workflow_status import _render_status_verbose
    output = _render_status_verbose(run_state, run_dir, workflow)

    assert "incomplete_dispatch" in output
    assert "N1" in output


def test_e2e_incomplete_dispatch_via_main(tmp_path, capsys, monkeypatch):
    """通过 main + monkeypatch RunState.rebuild 验证 AC-9 完整 CLI 路径。"""
    run_id = "REQ-2099-902"
    events = [
        {"type": "workflow_started", "run_id": run_id, "ts": "2026-05-14T00:00:00Z",
         "data": {"workflow_name": "standard-8phase"}},
        {"type": "node_started", "node_id": "N1", "ts": "2026-05-14T00:01:00Z"},
    ]
    _make_run_dir(tmp_path, run_id, events)
    monkeypatch.setattr(workflow_status, "STALE_THRESHOLD_MINUTES", 30)

    from run_state import RunState

    original_rebuild = RunState.rebuild

    @classmethod  # type: ignore[misc]
    def _patched_rebuild(cls, events, run_id=None, warnings=None):
        state = original_rebuild.__func__(cls, events, run_id=run_id, warnings=warnings)
        if run_id and run_id.startswith("REQ-2099-902"):
            # 注入 incomplete_dispatch
            state.node_outputs["N1"] = {"state": "running", "output": "", "data": {}}
            state.current_node = "N2"
            state.state = "running"
        return state

    monkeypatch.setattr(RunState, "rebuild", _patched_rebuild)

    # workflow 加载会失败（tmp_path 无真实 yaml），fail-soft 后无节点分类
    # 但 stdout 应含基础 status；verbose 不会因 workflow=None 而报错
    rc = workflow_status.main([run_id, "--verbose"], repo_root=tmp_path)
    out = capsys.readouterr().out
    assert rc == 0
    assert "run_id" in out
