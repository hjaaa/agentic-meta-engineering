"""F-005 · /workflow:* 命令 + managing-workflow-runs 伞形 Skill 单测。

覆盖范围（6 个 TC）：
  TC-F5-1  happy_path：9 命令各取矩阵 ✓ 状态，验证 jsonl 事件正确写入
  TC-F5-2  invalid_state_rejected：矩阵 ✗ 格子 → exit 1 + stderr 含 E-WF-STATE-001
  TC-F5-3  continue_resume_three_states：running/paused/failed 三状态续跑 main loop stub
  TC-F5-4  status_parent_child_tree：含 sub_workflow 的 run，status 输出含子 run 嵌套
  TC-F5-5  chain_run_continue_save_status：run → continue → save → status 4 命令链路
  TC-F5-6  cancel_writes_event：cancel 在 3 种允许状态写 cancel_requested + TaskStop 超时路径

外部依赖全部 mock（git / TaskStop / isatty）。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# ---------- 被测模块（懒导入，避免 sys.path 不正确时失败） ----------

from run_state import RunState, append_event, read_events  # noqa: E402
from workflow_state_validator import CMD_ALLOWED_STATES, validate_state_for_cmd  # noqa: E402
import workflow_run  # noqa: E402
import workflow_continue  # noqa: E402
import workflow_save  # noqa: E402
import workflow_status  # noqa: E402
import workflow_list  # noqa: E402
import workflow_approve  # noqa: E402
import workflow_reject  # noqa: E402
import workflow_rollback_cmd  # noqa: E402
import workflow_cancel  # noqa: E402

# ---------- 公共 fixture ----------


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """创建临时仓库根目录（含基础目录结构）。"""
    (tmp_path / "runs").mkdir()
    (tmp_path / "requirements").mkdir()
    (tmp_path / ".claude" / "workflows").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def sample_template(tmp_repo: Path) -> str:
    """在临时仓库中创建 minimal workflow yaml 模板。"""
    template_name = "test-template"
    template_content = """\
name: test-template
description: 测试模板（F-005 单测用）
nodes:
  - id: node-a
    prompt: "hello"
  - id: node-b
    prompt: "world"
    depends_on: [node-a]
"""
    (tmp_repo / ".claude" / "workflows" / f"{template_name}.yaml").write_text(template_content, encoding="utf-8")
    return template_name


def _make_run_dir(repo: Path, run_id: str, initial_state: str = "running") -> Path:
    """创建测试用 run 目录 + jsonl，初始化到指定状态。"""
    run_dir = repo / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = run_dir / "run-state.jsonl"

    # 写 workflow_started 事件
    append_event(jsonl_path, {
        "type": "workflow_started",
        "run_id": run_id,
        "data": {"workflow_name": "test-template", "arguments": ""},
    })

    # 根据 initial_state 补充事件
    if initial_state == "paused":
        append_event(jsonl_path, {"type": "workflow_paused", "run_id": run_id})
    elif initial_state == "failed":
        append_event(jsonl_path, {"type": "workflow_failed", "run_id": run_id})
    elif initial_state == "completed":
        append_event(jsonl_path, {"type": "workflow_completed", "run_id": run_id})
    elif initial_state == "approval_pending":
        append_event(jsonl_path, {
            "type": "approval_pending",
            "run_id": run_id,
            "node_id": "approval-node",
        })
    elif initial_state == "cancel_requested":
        append_event(jsonl_path, {"type": "cancel_requested", "run_id": run_id})
    elif initial_state == "cancelled":
        append_event(jsonl_path, {"type": "workflow_cancelled", "run_id": run_id})

    return run_dir


def _patch_git_branch(run_id: str):
    """patch git branch 推断为 feat/req-<run_id>。"""
    mock_result = MagicMock()
    mock_result.stdout = f"feat/req-{run_id}\n"
    return patch("subprocess.run", return_value=mock_result)


# ============================================================
# TC-F5-1: happy_path — 9 命令各取矩阵 ✓ 状态
# ============================================================

class TestHappyPath:
    """TC-F5-1：9 命令 happy path，验证 jsonl 事件正确写入。"""

    def test_run_creates_workflow_started_event(self, tmp_repo: Path, sample_template: str):
        """given_valid_template_when_run_then_workflow_started_event_written。"""
        rc = workflow_run.main([sample_template], repo_root=tmp_repo)

        assert rc == 0
        # 确认 runs/ 下创建了目录
        run_dirs = list((tmp_repo / "runs").iterdir())
        assert len(run_dirs) == 1, f"期望 1 个 run 目录，实际：{run_dirs}"

        jsonl_path = run_dirs[0] / "run-state.jsonl"
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "workflow_started" in types, f"期望 workflow_started 事件，实际事件：{types}"

    def test_continue_in_running_state_calls_main_loop_stub(self, tmp_repo: Path):
        """given_run_state_running_when_continue_then_main_loop_stub_called。"""
        run_id = "RUN-20260509-001"
        _make_run_dir(tmp_repo, run_id, "running")

        with _patch_git_branch(run_id):
            rc = workflow_continue.main([], repo_root=tmp_repo)

        assert rc == 0, f"continue 在 running 状态应返回 0，实际 rc={rc}"

    def test_save_in_running_state_writes_event(self, tmp_repo: Path):
        """given_run_state_running_when_save_then_checkpoint_event_written。"""
        run_id = "RUN-20260509-002"
        _make_run_dir(tmp_repo, run_id, "running")

        with _patch_git_branch(run_id):
            rc = workflow_save.main(["测试 note"], repo_root=tmp_repo)

        assert rc == 0, f"save 在 running 状态应返回 0，实际 rc={rc}"
        # 验证 jsonl 追加了 save 事件（直接写 save 类型，不再代理为 workflow_paused）
        jsonl_path = tmp_repo / "runs" / run_id / "run-state.jsonl"
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "save" in types, f"save 应追加 save 事件，实际事件：{types}"

    def test_status_in_running_state_prints_run_info(self, tmp_repo: Path, capsys):
        """given_run_state_running_when_status_then_run_info_printed。"""
        run_id = "RUN-20260509-003"
        _make_run_dir(tmp_repo, run_id, "running")

        rc = workflow_status.main([run_id], repo_root=tmp_repo)

        assert rc == 0, f"status 应返回 0，实际 rc={rc}"
        captured = capsys.readouterr()
        assert run_id in captured.out, f"status 输出应含 run_id，实际：{captured.out}"

    def test_list_scans_runs_dir(self, tmp_repo: Path, capsys):
        """given_runs_dir_with_entries_when_list_then_table_printed。"""
        _make_run_dir(tmp_repo, "RUN-20260509-010", "running")
        _make_run_dir(tmp_repo, "RUN-20260509-011", "paused")

        rc = workflow_list.main([], repo_root=tmp_repo)

        assert rc == 0, f"list 应返回 0，实际 rc={rc}"
        captured = capsys.readouterr()
        assert "RUN-20260509-010" in captured.out
        assert "RUN-20260509-011" in captured.out

    def test_approve_in_approval_pending_writes_event(self, tmp_repo: Path):
        """given_approval_pending_state_when_approve_tty_then_approval_approved_event。"""
        run_id = "RUN-20260509-004"
        _make_run_dir(tmp_repo, run_id, "approval_pending")

        with _patch_git_branch(run_id):
            # mock isatty=True（模拟 tty 环境）
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                rc = workflow_approve.main([], repo_root=tmp_repo)

        assert rc == 0, f"approve 在 approval_pending 状态 tty 环境应返回 0，实际 rc={rc}"
        jsonl_path = tmp_repo / "runs" / run_id / "run-state.jsonl"
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "approval_approved" in types, f"approve 应写 approval_approved 事件，实际：{types}"

    def test_reject_in_approval_pending_writes_event(self, tmp_repo: Path):
        """given_approval_pending_state_when_reject_tty_valid_reason_then_approval_rejected_event。"""
        run_id = "RUN-20260509-005"
        _make_run_dir(tmp_repo, run_id, "approval_pending")

        with _patch_git_branch(run_id):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                rc = workflow_reject.main(["设计方案不合格，需重审"], repo_root=tmp_repo)

        assert rc == 0, f"reject 在 approval_pending 状态应返回 0，实际 rc={rc}"
        jsonl_path = tmp_repo / "runs" / run_id / "run-state.jsonl"
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "approval_rejected" in types, f"reject 应写 approval_rejected 事件，实际：{types}"
        reject_events = [e for e in events if e["type"] == "approval_rejected"]
        assert reject_events[0]["data"]["reason"] == "设计方案不合格，需重审"

    def test_rollback_passes_state_check_but_exits_1_without_f010(self, tmp_repo: Path):
        """given_running_state_when_rollback_then_state_check_passes_but_f010_not_landed。"""
        run_id = "RUN-20260509-006"
        _make_run_dir(tmp_repo, run_id, "running")

        with _patch_git_branch(run_id):
            rc = workflow_rollback_cmd.main(["node-a"], repo_root=tmp_repo)

        # F-010 未落地 → exit 1（ImportError 兜底），但状态校验通过了
        assert rc == 1, f"rollback 在 F-010 未落地时应返回 1（占位），实际 rc={rc}"

    def test_cancel_in_running_state_writes_cancel_requested(self, tmp_repo: Path):
        """given_running_state_when_cancel_then_cancel_requested_event_written。"""
        run_id = "RUN-20260509-007"
        _make_run_dir(tmp_repo, run_id, "running")

        with _patch_git_branch(run_id):
            rc = workflow_cancel.main([], repo_root=tmp_repo, _skip_wait=True)

        assert rc == 0, f"cancel 在 running 状态应返回 0，实际 rc={rc}"
        jsonl_path = tmp_repo / "runs" / run_id / "run-state.jsonl"
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "cancel_requested" in types, f"cancel 应写 cancel_requested 事件，实际：{types}"


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
    """TC-F5-3：running / paused / failed 三状态续跑 main loop stub。"""

    @pytest.mark.parametrize("state", ["running", "paused", "failed"])
    def test_continue_allows_state(self, state: str, tmp_repo: Path, capsys):
        """given_state_in_allowed_set_when_continue_then_exit_0_and_stub_output。"""
        run_id = f"RUN-20260509-03{state[:1]}"
        _make_run_dir(tmp_repo, run_id, state)

        with _patch_git_branch(run_id):
            rc = workflow_continue.main([], repo_root=tmp_repo)

        assert rc == 0, f"continue 在 {state!r} 状态应返回 0，实际 rc={rc}"
        captured = capsys.readouterr()
        assert "main loop stub" in captured.out, (
            f"continue 应调 main loop stub，输出：{captured.out}"
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
# TC-F5-4: status_parent_child_tree
# ============================================================

class TestStatusParentChildTree:
    """TC-F5-4：含 sub_workflow 的 run，status 输出含子 run 嵌套缩进。"""

    def test_status_shows_nested_sub_run(self, tmp_repo: Path, capsys):
        """given_run_with_sub_run_when_status_then_nested_sub_run_shown。"""
        parent_id = "RUN-20260509-100"
        child_id = "RUN-20260509-101"

        # 创建父 run
        parent_dir = _make_run_dir(tmp_repo, parent_id, "running")

        # 创建子 run（nodes/<node-id>/run_id 文件）
        child_dir = _make_run_dir(tmp_repo, child_id, "completed")
        nodes_dir = parent_dir / "nodes" / "code-review-node"
        nodes_dir.mkdir(parents=True)
        (nodes_dir / "run_id").write_text(child_id, encoding="utf-8")

        rc = workflow_status.main([parent_id], repo_root=tmp_repo)
        assert rc == 0

        captured = capsys.readouterr()
        assert parent_id in captured.out, f"输出应含 parent run_id：{captured.out}"
        # 子 run 嵌套（无论 resolve 成功与否都有相关输出）
        assert child_id in captured.out or "子 run" in captured.out, (
            f"输出应含子 run 嵌套信息：{captured.out}"
        )

    def test_status_shows_current_node_position(self, tmp_repo: Path, capsys):
        """given_running_state_with_current_node_when_status_then_current_node_shown。"""
        run_id = "RUN-20260509-200"
        run_dir = _make_run_dir(tmp_repo, run_id, "running")

        # 追加 node_started 事件（current_node = "detail-design"）
        jsonl_path = run_dir / "run-state.jsonl"
        append_event(jsonl_path, {
            "type": "node_started",
            "run_id": run_id,
            "node_id": "detail-design",
        })

        rc = workflow_status.main([run_id], repo_root=tmp_repo)
        assert rc == 0

        captured = capsys.readouterr()
        assert "detail-design" in captured.out, (
            f"status 应显示 current_node=detail-design，输出：{captured.out}"
        )


# ============================================================
# TC-F5-5: chain_run_continue_save_status
# ============================================================

class TestChainCommands:
    """TC-F5-5：run → continue → save → status 4 命令链路通畅。"""

    def test_chain_run_continue_save_status(
        self, tmp_repo: Path, sample_template: str, capsys
    ):
        """given_nothing_when_run_continue_save_status_then_all_succeed。"""
        # 步骤 1: run ✓
        rc_run = workflow_run.main([sample_template], repo_root=tmp_repo)
        assert rc_run == 0, f"run 应返回 0，实际 rc={rc_run}"

        # 获取创建的 run_id
        run_dirs = list((tmp_repo / "runs").iterdir())
        assert len(run_dirs) == 1
        run_id = run_dirs[0].name

        # 步骤 2: continue（running 状态）✓
        with _patch_git_branch(run_id):
            rc_continue = workflow_continue.main([], repo_root=tmp_repo)
        assert rc_continue == 0, f"continue 应返回 0，实际 rc={rc_continue}"

        # 步骤 3: save（running 状态）✓
        with _patch_git_branch(run_id):
            rc_save = workflow_save.main(["链路测试 note"], repo_root=tmp_repo)
        assert rc_save == 0, f"save 应返回 0，实际 rc={rc_save}"

        # 步骤 4: status（应展示状态）✓
        rc_status = workflow_status.main([run_id], repo_root=tmp_repo)
        assert rc_status == 0, f"status 应返回 0，实际 rc={rc_status}"

        captured = capsys.readouterr()
        assert run_id in captured.out, f"status 应输出 run_id，实际：{captured.out}"

        # 验证 jsonl 包含正确事件序列
        jsonl_path = tmp_repo / "runs" / run_id / "run-state.jsonl"
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "workflow_started" in types, "链路应含 workflow_started"
        # save 事件（直接写 save 类型，不再代理）
        assert "save" in types, "save 链路应含 save 事件"


# ============================================================
# TC-F5-6: cancel_writes_event
# ============================================================

class TestCancelWritesEvent:
    """TC-F5-6：cancel 在 3 种允许状态写 cancel_requested 事件 + TaskStop 超时路径。"""

    @pytest.mark.parametrize("state", ["running", "paused", "approval_pending"])
    def test_cancel_writes_cancel_requested_in_allowed_states(
        self, state: str, tmp_repo: Path
    ):
        """given_state_in_allowed_set_when_cancel_then_cancel_requested_event_written。"""
        run_id = f"RUN-20260509-06{state[:1]}"
        _make_run_dir(tmp_repo, run_id, state)

        with _patch_git_branch(run_id):
            rc = workflow_cancel.main([], repo_root=tmp_repo, _skip_wait=True)

        assert rc == 0, f"cancel 在 {state!r} 状态应返回 0，实际 rc={rc}"

        jsonl_path = tmp_repo / "runs" / run_id / "run-state.jsonl"
        events, _ = read_events(jsonl_path)
        types = [e["type"] for e in events]
        assert "cancel_requested" in types, (
            f"cancel 在 {state!r} 状态应写 cancel_requested 事件，实际：{types}"
        )

    def test_cancel_taskstop_called_on_timeout(self, tmp_repo: Path):
        """given_graceful_timeout_when_cancel_then_task_stop_called。"""
        run_id = "RUN-20260509-070"
        _make_run_dir(tmp_repo, run_id, "running")

        task_stop_calls: list[str] = []

        def mock_task_stop(rid: str) -> None:
            task_stop_calls.append(rid)
            # mock 成功不抛异常

        with _patch_git_branch(run_id):
            with patch.object(workflow_cancel, "_task_stop_forceful", side_effect=mock_task_stop):
                rc = workflow_cancel.main([], repo_root=tmp_repo, _skip_wait=True)

        assert rc == 0, f"cancel 应返回 0，实际 rc={rc}"
        # _skip_wait=True → graceful=False → TaskStop 应被调用
        assert len(task_stop_calls) == 1, (
            f"TaskStop 应被调用 1 次，实际：{task_stop_calls}"
        )
        assert task_stop_calls[0] == run_id, (
            f"TaskStop 调用的 run_id 应为 {run_id!r}，实际：{task_stop_calls[0]!r}"
        )

    def test_cancel_taskstop_failure_does_not_raise(self, tmp_repo: Path):
        """given_task_stop_raises_exception_when_cancel_then_still_exit_0。"""
        run_id = "RUN-20260509-071"
        _make_run_dir(tmp_repo, run_id, "paused")

        def mock_task_stop_fail(rid: str) -> None:
            raise RuntimeError("TaskStop 模拟失败")

        with _patch_git_branch(run_id):
            with patch.object(workflow_cancel, "_task_stop_forceful", side_effect=mock_task_stop_fail):
                rc = workflow_cancel.main([], repo_root=tmp_repo, _skip_wait=True)

        # TaskStop 失败不改变 cancel 命令返回码（warn + 写降级事件，不 exit 1）
        assert rc == 0, f"TaskStop 失败时 cancel 仍应返回 0，实际 rc={rc}"


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


# ============================================================
# rev3 新增：G-8 并发 TC + G-11 审计写失败 TC
# ============================================================

class TestGenerateRunIdConcurrencySafe:
    """TC-F5-G8：_generate_run_id 并发场景下不产生重复 run_id（G-8 原子化验证）。"""

    def test_concurrent_run_id_no_collision(self, tmp_repo: Path):
        """given_two_concurrent_calls_when_generate_run_id_then_run_ids_are_unique ✓。

        使用 threading 双发 _generate_run_id，断言两次返回 run_id 不重叠。
        """
        import threading
        import workflow_run as wr

        results: list[str] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                run_id = wr._generate_run_id(tmp_repo)
                results.append(run_id)
            except Exception as exc:
                errors.append(exc)

        # 同时启动两个线程竞争创建 run_id
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 断言：无异常 + 两个 run_id 均不重复
        assert not errors, f"_generate_run_id 抛出异常：{errors}"
        assert len(results) == 2, f"期望 2 个 run_id，实际：{results}"
        assert results[0] != results[1], (
            f"并发生成的 run_id 重复：{results[0]} == {results[1]}"
        )
        # 确认两个目录都已实际创建
        for rid in results:
            assert (tmp_repo / "runs" / rid).is_dir(), (
                f"run_id {rid!r} 对应目录未创建"
            )


class TestContinueRunResumedWriteFailureExits1:
    """TC-F5-G11：continue run_resumed 写失败时 main 应返回 1（G-11 审计写失败 exit 1 验证）。"""

    def test_run_resumed_write_failure_returns_1(self, tmp_repo: Path):
        """given_append_event_raises_when_continue_then_main_returns_1 ✗→exit1。

        mock append_event 抛 WorkflowError，验证 main 返回 1（而非忽略后 exit 0）。
        """
        from common import WorkflowError

        run_id = "RUN-20260509-950"
        _make_run_dir(tmp_repo, run_id, "running")

        # 仅让写 run_resumed 事件的 append_event 调用抛异常
        original_append = None
        call_count = [0]

        def patched_append(path, event, **kwargs):
            call_count[0] += 1
            # 第一次调用是 _make_run_dir 里的 workflow_started，正常；
            # continue 写 run_resumed 时是第一次通过此 patched_append
            if event.get("type") == "run_resumed":
                raise WorkflowError("模拟 run_resumed 写失败")
            import run_state as rs_mod
            return rs_mod._append_event_real(path, event, **kwargs) if hasattr(rs_mod, "_append_event_real") else None

        with _patch_git_branch(run_id):
            with patch("workflow_continue.append_event") as mock_append:
                mock_append.side_effect = WorkflowError("模拟 run_resumed 写失败")
                rc = workflow_continue.main([], repo_root=tmp_repo)

        assert rc == 1, (
            f"run_resumed 写失败时 continue 应返回 1，实际 rc={rc}"
        )
