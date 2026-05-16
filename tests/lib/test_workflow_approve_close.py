"""F-006 · workflow_approve.py 验收测试（AC-03a）。

覆盖：
- AC-03a：approve 在 approval_pending 下原子写 [approval_approved, node_completed]，
  state 派生 → running
- isatty=False（mock）→ exit 2（R-S01 不破）
- state 非 approval_pending（如 running）→ exit 1（state 矩阵拒绝）

外部依赖（git rev-parse / sys.stdin.isatty）全部 mock。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from run_state import RunState, append_event, read_events  # noqa: E402
import workflow_approve  # noqa: E402

WORKFLOW_APPROVE_PY = REPO_ROOT / "scripts" / "lib" / "workflow_approve.py"


# ---------- 辅助 ----------

def _seed_approval_pending(repo: Path, run_id: str, node_id: str = "gate-1") -> Path:
    """在 repo/runs/<run_id>/run-state.jsonl 写 workflow_started + approval_pending(node_id)。"""
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl = run_dir / "run-state.jsonl"
    append_event(jsonl, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "test-template", "arguments": ""},
    })
    append_event(jsonl, {"type": "node_started", "run_id": run_id, "node_id": node_id})
    append_event(jsonl, {
        "type": "approval_pending",
        "run_id": run_id,
        "node_id": node_id,
    })
    return run_dir


def _patch_git_branch(run_id: str):
    mock_result = MagicMock()
    mock_result.stdout = f"feat/req-{run_id}\n"
    return patch("subprocess.run", return_value=mock_result)


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """临时仓库根目录骨架。"""
    (tmp_path / "runs").mkdir()
    (tmp_path / "requirements").mkdir()
    return tmp_path


# ---------- AC-03a：原子写 [approval_approved, node_completed] ----------

def test_approve_atomically_writes_approval_approved_and_node_completed(tmp_repo: Path) -> None:
    """AC-03a：approve 在 approval_pending 下应原子写两条事件。"""
    run_id = "RUN-F006-APPR-001"
    node_id = "gate-design"
    _seed_approval_pending(tmp_repo, run_id, node_id)

    with _patch_git_branch(run_id):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            rc = workflow_approve.main([], repo_root=tmp_repo)

    assert rc == 0, f"approve 在 approval_pending 应返回 0，实际 rc={rc}"

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, warnings = read_events(jsonl)
    assert not warnings, f"不应有 jsonl warn，实际：{warnings}"

    types = [e["type"] for e in events]
    # 末尾两条必须是 approval_approved 紧跟 node_completed（顺序保证）
    assert types[-2:] == ["approval_approved", "node_completed"], (
        f"approve 应原子写 [approval_approved, node_completed]，实际末位 2 条：{types[-2:]}"
    )

    approval_evt = events[-2]
    completed_evt = events[-1]
    assert approval_evt["node_id"] == node_id
    assert completed_evt["node_id"] == node_id
    assert completed_evt.get("data", {}).get("output") == {"decision": "approved"}, (
        f"node_completed.data.output 应 = {{'decision':'approved'}}，"
        f"实际：{completed_evt.get('data')}"
    )


def test_approve_state_derives_to_running_after_node_completed(tmp_repo: Path) -> None:
    """AC-03a：approve 后 RunState.state 应派生为 running。"""
    run_id = "RUN-F006-APPR-002"
    node_id = "gate-detail"
    _seed_approval_pending(tmp_repo, run_id, node_id)

    with _patch_git_branch(run_id):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            rc = workflow_approve.main([], repo_root=tmp_repo)
    assert rc == 0

    jsonl = tmp_repo / "runs" / run_id / "run-state.jsonl"
    events, warnings = read_events(jsonl)
    state = RunState.rebuild(events, run_id=run_id, warnings=warnings)
    assert state.state == "running", f"approve 后应派生 running，实际 {state.state}"
    assert state.pending_approval is None, (
        f"approve 后 pending_approval 应清空，实际 {state.pending_approval}"
    )


# ---------- isatty=False → exit 2 ----------

def test_isatty_false_returns_exit_2_subprocess() -> None:
    """isatty=False（subprocess 喂空 stdin）→ exit 2（R-S01 不破）。"""
    proc = subprocess.run(
        [sys.executable, str(WORKFLOW_APPROVE_PY)],
        input="",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 2, (
        f"isatty=False 应 exit 2，实际 {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert proc.stderr.strip(), "stderr 不应为空"


# ---------- state != approval_pending → exit 1 ----------

def test_approve_in_running_state_returns_exit_1(tmp_repo: Path) -> None:
    """state=running（非 approval_pending）→ exit 1（state 矩阵拒绝）。"""
    run_id = "RUN-F006-APPR-003"
    run_dir = tmp_repo / "runs" / run_id
    run_dir.mkdir(parents=True)
    jsonl = run_dir / "run-state.jsonl"
    append_event(jsonl, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "test-template", "arguments": ""},
    })

    with _patch_git_branch(run_id):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            rc = workflow_approve.main([], repo_root=tmp_repo)
    assert rc == 1, f"state=running 应 exit 1（state 矩阵拒绝），实际 rc={rc}"
