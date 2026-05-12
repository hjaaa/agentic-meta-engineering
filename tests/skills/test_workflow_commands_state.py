"""F-005 · /workflow:* 命令单测（状态矩阵校验）。

覆盖范围：
  TC-F5-2  invalid_state_rejected：矩阵 ✗ 格子 → exit 1 + stderr 含 E-WF-STATE-001
  TC-F5-3  continue_resume_three_states：running/paused/failed 三状态续跑 main loop（F-007 真实实现）
  TC-matrix state_machine_matrix：CMD_ALLOWED_STATES 与 detailed-design §1.3 完全对齐验证
  TC-events new_events_do_not_change_state：3 个新事件写入后 RunState.state 不被推送

外部依赖全部 mock（git / TaskStop / isatty）。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
_SKILLS_TEST_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))
if str(_SKILLS_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILLS_TEST_DIR))

# ---------- 被测模块 ----------

from run_state import RunState, append_event, read_events  # noqa: E402
from workflow_state_validator import CMD_ALLOWED_STATES, validate_state_for_cmd  # noqa: E402
import workflow_continue  # noqa: E402
import workflow_approve  # noqa: E402
import workflow_cancel  # noqa: E402

# ---------- 共享辅助 ----------

from _test_workflow_commands_helpers import (  # noqa: E402
    _make_run_dir,
    _patch_git_branch,
)


# ---------- 公共 fixture ----------


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """创建临时仓库根目录（含基础目录结构）。"""
    (tmp_path / "runs").mkdir()
    (tmp_path / "requirements").mkdir()
    (tmp_path / ".claude" / "workflows").mkdir(parents=True)
    return tmp_path


# ============================================================
# TC-F5-2: invalid_state_rejected — 矩阵 ✗ 格子 → exit 1
# ============================================================

class TestInvalidStateRejected:
    """TC-F5-2：矩阵每个 ✗ 格子 → exit 1 + stderr 含 E-WF-STATE-001。"""

    # 各命令 × 拒绝状态（从矩阵中选取典型 ✗ 格子）
    @pytest.mark.parametrize("cmd,state", [
        ("continue", "completed"),
        ("continue", "approval_pending"),
        ("continue", "cancelled"),
        ("save",     "cancel_requested"),
        ("save",     "cancelled"),
        ("approve",  "running"),
        ("approve",  "failed"),
        ("reject",   "completed"),
        ("reject",   "running"),
        ("rollback", "cancelled"),
        ("rollback", "cancel_requested"),
        ("cancel",   "completed"),
        ("cancel",   "failed"),
        ("cancel",   "cancelled"),
    ])
    def test_invalid_state_raises_workflow_error(self, cmd: str, state: str, tmp_repo: Path):
        """given_cmd_and_invalid_state_when_validate_then_WorkflowError_raised。"""
        from common import WorkflowError
        with pytest.raises(WorkflowError) as exc_info:
            validate_state_for_cmd(cmd, "RUN-FAKE", state)
        assert "E-WF-STATE-001" in str(exc_info.value), (
            f"错误文案应含 E-WF-STATE-001，实际：{exc_info.value}"
        )
        assert cmd in str(exc_info.value), f"错误文案应含 cmd={cmd!r}"
        assert state in str(exc_info.value), f"错误文案应含 state={state!r}"

    def test_continue_rejects_completed_state_exits_1(self, tmp_repo: Path):
        """given_run_state_completed_when_continue_then_exit_1。"""
        run_id = "RUN-20260509-020"
        _make_run_dir(tmp_repo, run_id, "completed")

        with _patch_git_branch(run_id):
            rc = workflow_continue.main([], repo_root=tmp_repo)

        assert rc == 1, f"continue 在 completed 状态应返回 1，实际 rc={rc}"

    def test_approve_rejects_running_state_exits_1(self, tmp_repo: Path):
        """given_run_state_running_when_approve_then_exit_1。"""
        run_id = "RUN-20260509-021"
        _make_run_dir(tmp_repo, run_id, "running")

        with _patch_git_branch(run_id):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                rc = workflow_approve.main([], repo_root=tmp_repo)

        assert rc == 1, f"approve 在 running 状态应返回 1（非 approval_pending），实际 rc={rc}"

    def test_cancel_rejects_completed_state_exits_1(self, tmp_repo: Path):
        """given_run_state_completed_when_cancel_then_exit_1。"""
        run_id = "RUN-20260509-022"
        _make_run_dir(tmp_repo, run_id, "completed")

        with _patch_git_branch(run_id):
            rc = workflow_cancel.main([], repo_root=tmp_repo, _skip_wait=True)

        assert rc == 1, f"cancel 在 completed 状态应返回 1，实际 rc={rc}"


# ============================================================
# TC-F5-3: continue_resume_three_states
# ============================================================

class TestContinueResumeThreeStates:
    """TC-F5-3：running / paused / failed 三状态续跑 main loop（F-007 已替换原 stub）。"""

    @pytest.mark.parametrize("state", ["running", "paused", "failed"])
    def test_continue_allows_state(self, state: str, tmp_repo: Path, capsys):
        """given_state_in_allowed_set_when_continue_then_exit_0_and_main_loop_called。

        F-007 用真实 _main_loop 替换了 stub，测试改为 mock _load_workflow_for_run
        和 _main_loop，只验证状态矩阵通过且 main() 返回 0。
        """
        run_id = f"RUN-20260509-03{state[:1]}"
        _make_run_dir(tmp_repo, run_id, state)

        _fake_workflow = {"id": "fake", "nodes": []}
        with _patch_git_branch(run_id), \
                patch("workflow_continue._load_workflow_for_run", return_value=_fake_workflow), \
                patch("workflow_continue._main_loop"):
            rc = workflow_continue.main([], repo_root=tmp_repo)

        assert rc == 0, f"continue 在 {state!r} 状态应返回 0，实际 rc={rc}"
        captured = capsys.readouterr()
        assert "恢复 workflow run" in captured.out, (
            f"continue 应打印恢复信息，实际输出：{captured.out}"
        )

    @pytest.mark.parametrize("state", ["completed", "approval_pending", "cancelled"])
    def test_continue_rejects_state(self, state: str, tmp_repo: Path):
        """given_state_not_in_allowed_set_when_continue_then_exit_1。"""
        run_id = f"RUN-20260509-04{state[:1]}"
        _make_run_dir(tmp_repo, run_id, state)

        with _patch_git_branch(run_id):
            rc = workflow_continue.main([], repo_root=tmp_repo)

        assert rc == 1, f"continue 在 {state!r} 状态应返回 1，实际 rc={rc}"


# ============================================================
# 补充：state_matrix 覆盖 —— 所有命令 × 所有状态的矩阵正确性
# ============================================================

class TestStateMachineMatrix:
    """验证 CMD_ALLOWED_STATES 矩阵与 detailed-design §1.3 完全对齐。"""

    # 矩阵真值表（来自 detailed-design.md §1.3）
    _EXPECTED_MATRIX = {
        # cmd → set of allowed states (None = 无需状态)
        "run":      None,
        "continue": {"running", "paused", "failed"},
        "save":     {"running", "paused", "approval_pending", "failed", "completed"},
        "status":   {"running", "paused", "approval_pending", "cancel_requested",
                     "cancelled", "failed", "completed"},
        "list":     None,
        "approve":  {"approval_pending"},
        "reject":   {"approval_pending"},
        "rollback": {"running", "paused", "approval_pending", "failed", "completed"},
        "cancel":   {"running", "paused", "approval_pending"},
    }

    def test_all_commands_in_allowed_states_map(self):
        """given_CMD_ALLOWED_STATES_when_compared_to_spec_then_all_match。"""
        assert set(CMD_ALLOWED_STATES.keys()) == set(self._EXPECTED_MATRIX.keys()), (
            f"CMD_ALLOWED_STATES 命令集合与 spec 不符\n"
            f"实际：{set(CMD_ALLOWED_STATES.keys())}\n"
            f"期望：{set(self._EXPECTED_MATRIX.keys())}"
        )

    @pytest.mark.parametrize("cmd", list(_EXPECTED_MATRIX.keys()))
    def test_allowed_states_match_spec(self, cmd: str):
        """given_cmd_when_check_allowed_states_then_match_spec_matrix。"""
        expected = self._EXPECTED_MATRIX[cmd]
        actual = CMD_ALLOWED_STATES[cmd]
        assert actual == expected, (
            f"cmd={cmd!r} 的允许状态与 spec §1.3 不符\n"
            f"实际：{actual}\n"
            f"期望：{expected}"
        )


# ============================================================
# rev2 新增：3 个新事件不改变 RunState.state 的验证
# ============================================================

class TestNewEventsDoNotChangeState:
    """验证 cancel_taskstop_failed / run_resumed / save 三个新事件写出后，
    RunState.state 不被 WORKFLOW_EVENT_TO_STATE 错误推送。"""

    def test_cancel_taskstop_failed_event_does_not_change_state(self, tmp_repo: Path):
        """given_cancel_requested_state_when_cancel_taskstop_failed_event_appended_then_state_unchanged。"""
        run_id = "RUN-20260509-900"
        run_dir = _make_run_dir(tmp_repo, run_id, "running")
        jsonl_path = run_dir / "run-state.jsonl"

        # 先写 cancel_requested 推进状态
        append_event(jsonl_path, {"type": "cancel_requested", "run_id": run_id})

        # 再写 cancel_taskstop_failed
        append_event(jsonl_path, {
            "type": "cancel_taskstop_failed",
            "run_id": run_id,
            "data": {"error": "TaskStop 模拟失败"},
        })

        events, _ = read_events(jsonl_path)
        state = RunState.rebuild(events, run_id=run_id)

        # cancel_taskstop_failed 不应把 state 推到 failed，应保持 cancel_requested
        assert state.state == "cancel_requested", (
            f"cancel_taskstop_failed 事件不应改变 state，期望 cancel_requested，"
            f"实际：{state.state}"
        )

    def test_run_resumed_event_does_not_change_state(self, tmp_repo: Path):
        """given_paused_state_when_run_resumed_event_appended_then_state_still_paused。"""
        run_id = "RUN-20260509-901"
        run_dir = _make_run_dir(tmp_repo, run_id, "paused")
        jsonl_path = run_dir / "run-state.jsonl"

        # 写 run_resumed 事件
        append_event(jsonl_path, {"type": "run_resumed", "run_id": run_id})

        events, _ = read_events(jsonl_path)
        state = RunState.rebuild(events, run_id=run_id)

        # run_resumed 不应改变 state，应保持 paused
        assert state.state == "paused", (
            f"run_resumed 事件不应改变 state，期望 paused，实际：{state.state}"
        )

    def test_save_event_does_not_change_state(self, tmp_repo: Path):
        """given_running_state_when_save_event_appended_then_state_still_running。"""
        run_id = "RUN-20260509-902"
        run_dir = _make_run_dir(tmp_repo, run_id, "running")
        jsonl_path = run_dir / "run-state.jsonl"

        # 写 save 事件（不应把 state 推到 paused）
        append_event(jsonl_path, {
            "type": "save",
            "run_id": run_id,
            "data": {"note": "测试检查点"},
        })

        events, _ = read_events(jsonl_path)
        state = RunState.rebuild(events, run_id=run_id)

        # save 不应改变 state，应保持 running
        assert state.state == "running", (
            f"save 事件不应改变 state，期望 running，实际：{state.state}"
        )
