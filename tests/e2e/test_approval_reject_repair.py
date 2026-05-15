"""F-006 · approval reject → repair → approve 完整闭环 e2e 测试。

模拟序列（注意 F-007 save_node_result.py 尚未落地，本测试用 append_event 直接
写 approval_repair_completed 模拟外部 Claude 完成修复后回调）：

    1. approval_pending(N)                  ← seed
    2. reject 第 1 次（attempt=1/max=3）    ← workflow_reject CLI
       → [approval_rejected, approval_repair_started]
       → state == awaiting_claude_action
    3. 模拟 save_node_result 写             ← append_event 直接写
       approval_repair_completed
       → state == approval_pending
    4. approve                              ← workflow_approve CLI
       → [approval_approved, node_completed]
       → state == running

验证全程：
- 末态 state == running
- pending_approval 清空
- 反扫事件序列严格按 7 条顺序
"""
from __future__ import annotations

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
import workflow_reject  # noqa: E402

_MIN_TEMPLATE = """\
name: test-template
version: 1
category: assist
description: F-006 e2e 闭环测试模板
nodes:
  - id: gate-design
    approval:
      message: "请审查方案"
      on_reject:
        prompt: "修复后重提"
        max_attempts: 3
"""


def _patch_git_branch(run_id: str):
    mock_result = MagicMock()
    mock_result.stdout = f"feat/req-{run_id}\n"
    return patch("subprocess.run", return_value=mock_result)


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """临时仓库根目录。"""
    (tmp_path / "runs").mkdir()
    (tmp_path / "requirements").mkdir()
    yaml_dir = tmp_path / ".claude" / "workflows" / "requirement"
    yaml_dir.mkdir(parents=True)
    (yaml_dir / "test-template.yaml").write_text(_MIN_TEMPLATE, encoding="utf-8")
    return tmp_path


def _seed_run(repo: Path, run_id: str, node_id: str = "gate-design") -> Path:
    """初始化 run dir 到 approval_pending(node_id) 状态。"""
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


# ---------- 复用 helper（review F-CR-008/F-CR-016/F-CR-018 同根因抽出）----------

def _assert_after_reject(
    events: list[dict],
    warnings: list,
    *,
    expected_attempt: int,
    expected_max: int,
    node_id: str = "gate-design",
) -> None:
    """断言 reject 后末位 2 事件形状 + attempt + max + prompt_ref（设计 §2.2.2 必填）。

    锚定 review F-CR-016：approval_repair_started.data.prompt_ref 必填，旧测试只查
    attempt/max_attempts 而不锚 prompt_ref。
    """
    assert not warnings, f"不应有 jsonl warn，实际：{warnings}"
    types = [e["type"] for e in events]
    assert types[-2:] == ["approval_rejected", "approval_repair_started"], (
        f"reject 应原子写 [rejected, repair_started]，实际末位 2：{types[-2:]}"
    )
    rej, repair = events[-2], events[-1]
    assert rej["node_id"] == node_id
    assert rej["data"]["attempt"] == expected_attempt
    assert repair["node_id"] == node_id
    assert repair["data"]["attempt"] == expected_attempt
    assert repair["data"]["max_attempts"] == expected_max
    assert repair["data"]["prompt_ref"] == "approval.on_reject.prompt", (
        f"approval_repair_started.data.prompt_ref 应为设计 §2.2.2 固定字符串，"
        f"实际：{repair['data'].get('prompt_ref')!r}"
    )


def _assert_after_repair_completed(
    events: list[dict],
    warnings: list,
    *,
    expected_attempt: int,
    node_id: str = "gate-design",
) -> None:
    """断言 approval_repair_completed 后状态回 approval_pending（rebuild 验证）。"""
    state = RunState.rebuild(events, warnings=warnings)
    assert state.state == "approval_pending", (
        f"approval_repair_completed 后应回 approval_pending，实际 {state.state}"
    )
    assert state.pending_approval == node_id, (
        f"repair_completed 应保留 pending_approval，实际 {state.pending_approval}"
    )
    last_repair_completed = next(
        (e for e in reversed(events) if e["type"] == "approval_repair_completed"), None,
    )
    assert last_repair_completed is not None
    assert last_repair_completed["data"]["attempt"] == expected_attempt


def _assert_after_approve(
    events: list[dict],
    warnings: list,
    *,
    node_id: str = "gate-design",
) -> None:
    """断言 approve 末态：state=running + pending_approval=None + node_completed 形状/output 正确。

    锚定 review F-CR-018：node_completed 应明确带 node_id（不能仅靠 types 隐含）+
    data.output={'decision':'approved'}（设计 §3.2.1）。
    """
    assert not warnings, f"全程不应有 jsonl warn，实际：{warnings}"
    state = RunState.rebuild(events, warnings=warnings)
    assert state.state == "running", f"approve 末态应 running，实际 {state.state}"
    assert state.pending_approval is None, (
        f"approve 末态应清空 pending_approval，实际 {state.pending_approval}"
    )
    completed = events[-1]
    assert completed["type"] == "node_completed", (
        f"末位事件应为 node_completed，实际 {completed['type']}"
    )
    assert completed.get("node_id") == node_id, (
        f"node_completed 应带 node_id={node_id}，实际 {completed.get('node_id')}"
    )
    assert completed.get("data", {}).get("output") == {"decision": "approved"}, (
        f"node_completed.data.output 应为 {{'decision': 'approved'}}（设计 §3.2.1），"
        f"实际：{completed.get('data', {}).get('output')!r}"
    )


def test_full_reject_repair_approve_cycle(tmp_repo: Path) -> None:
    """e2e 闭环：pending → reject → repair → 模拟 save_node_result → pending → approve → next。"""
    run_id = "RUN-F006-E2E-001"
    node_id = "gate-design"
    run_dir = _seed_run(tmp_repo, run_id, node_id)
    jsonl = run_dir / "run-state.jsonl"

    # ---- 步骤 2：reject 第 1 次 ----
    with _patch_git_branch(run_id):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            rc = workflow_reject.main(["设计方案需补充安全分析"], repo_root=tmp_repo)
    assert rc == 0, f"reject 应返回 0，实际 rc={rc}"

    events, warnings = read_events(jsonl)
    _assert_after_reject(events, warnings, expected_attempt=1, expected_max=3, node_id=node_id)
    state = RunState.rebuild(events, warnings=warnings)
    assert state.state == "awaiting_claude_action", (
        f"reject 后应 awaiting_claude_action，实际 {state.state}"
    )
    assert state.pending_approval == node_id

    # ---- 步骤 3：模拟 save_node_result 写 approval_repair_completed（F-007 待落地，此处直写）----
    append_event(jsonl, {
        "type": "approval_repair_completed",
        "run_id": run_id,
        "node_id": node_id,
        "data": {"attempt": 1},
    })

    events, warnings = read_events(jsonl)
    _assert_after_repair_completed(events, warnings, expected_attempt=1, node_id=node_id)

    # ---- 步骤 4：approve ----
    with _patch_git_branch(run_id):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            rc = workflow_approve.main([], repo_root=tmp_repo)
    assert rc == 0, f"approve 应返回 0，实际 rc={rc}"

    # ---- 末态校验 ----
    events, warnings = read_events(jsonl)
    _assert_after_approve(events, warnings, node_id=node_id)

    types = [e["type"] for e in events]
    expected_tail = [
        "approval_pending",
        "approval_rejected",
        "approval_repair_started",
        "approval_repair_completed",
        "approval_approved",
        "node_completed",
    ]
    assert types[-len(expected_tail):] == expected_tail, (
        f"事件序列应严格按闭环顺序，实际末位 {len(expected_tail)}：{types[-len(expected_tail):]}"
    )
