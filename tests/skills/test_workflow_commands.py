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

import sys
from pathlib import Path
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

    def test_rollback_passes_repo_root_into_rollback_run_e2e(self, tmp_repo: Path):
        """given_running_state_when_rollback_then_cmd_layer_drives_rollback_run_with_repo_root。

        回归 Hotfix：早期 workflow_rollback_cmd.py:73 把 run_dir(Path) 当 target_id(str) 传，
        进 workflow_rollback.py:419 re.fullmatch 会 TypeError。本用例验证命令层真调用走到
        rollback_run 内部并成功返回（产物被归档 + jsonl tail 写出），不再是 ImportError 占位。
        """
        import shutil

        run_id = "TEST-CMD-RB-001"
        run_dir = tmp_repo / "runs" / run_id
        run_dir.mkdir(parents=True)

        # 复用 F-007 fixture：4 节点单链 + 完整 node_completed 链路，state ≈ running
        fixture_dir = _REPO_ROOT / "tests" / "lib" / "fixtures" / "rollback" / "R1-single-layer"
        shutil.copy(fixture_dir / "workflow.yaml", run_dir / "workflow.yaml")
        shutil.copy(fixture_dir / "initial-jsonl.txt", run_dir / "run-state.jsonl")
        # 节点产物目录（rollback_run 会按拓扑 mv 到 .archived/）
        for nid in ["node-a", "node-b", "node-c", "node-d"]:
            artifact_dir = run_dir / nid
            artifact_dir.mkdir()
            (artifact_dir / "output.json").write_text('{"ok": true}', encoding="utf-8")

        with _patch_git_branch(run_id):
            rc = workflow_rollback_cmd.main(["node-c"], repo_root=tmp_repo)

        # rc=0 == 命令层真把 repo_root=tmp_repo 透传到 rollback_run，且未触发 TypeError
        assert rc == 0, f"rollback 命令层应返回 0，实际 rc={rc}"
        # node-d 应已被归档（落入 .archived/<ts>/）
        assert not (run_dir / "node-d").exists(), "node-d 产物应已被 rollback 归档"
        archived_root = run_dir / ".archived"
        assert archived_root.is_dir(), "应生成 .archived/ 目录"
        ts_dirs = list(archived_root.iterdir())
        assert ts_dirs and (ts_dirs[0] / "node-d").is_dir(), \
            "node-d 应归档到 .archived/<ts>/node-d/"

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


class TestOSErrorWrappedAsWorkflowError:
    """TC-F5-rev4/P-2：append_event 中 os.open 抛 OSError 应被包装为 WorkflowError。"""

    def test_append_event_os_open_oserror_raises_workflow_error(self, tmp_repo: Path):
        """given_os_open_raises_oserror_when_append_event_then_raises_workflow_error ✗→WorkflowError。

        mock os.open 抛 OSError（模拟磁盘满 / 权限不足），断言 append_event
        抛出 WorkflowError 而非透出原始 OSError（P-2 H-7+H-14 修复验证）。
        """
        import os
        from common import WorkflowError
        from run_state import append_event as _append_event

        jsonl_path = tmp_repo / "runs" / "RUN-20260509-999" / "run-state.jsonl"
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        event = {"type": "workflow_started", "run_id": "RUN-20260509-999"}

        with patch("run_state.os.open", side_effect=OSError("[Errno 28] No space left on device")):
            with pytest.raises(WorkflowError) as exc_info:
                _append_event(jsonl_path, event)

        assert "写 jsonl 失败" in str(exc_info.value), (
            f"WorkflowError 消息应含'写 jsonl 失败'，实际：{exc_info.value}"
        )

    def test_run_meta_write_oserror_returns_1(self, tmp_repo: Path, sample_template: str, capsys):
        """given_meta_open_raises_oserror_when_workflow_run_main_then_returns_1。

        mock _generate_run_id 返回固定 id，mock Path.open 在写 meta.yaml 时抛 OSError
        （模拟磁盘满）。workflow_run.main 将 OSError 包装为 WorkflowError 向上抛出，
        dispatcher.dispatch 在第 67-69 行兜底捕获并返回 1（P-2 meta 写入路径兜底
        链路完整性验证，对应 K-5 覆盖偏窄补全）。
        """
        import workflow_command_dispatcher as dispatcher
        from pathlib import Path as _Path

        fixed_run_id = "RUN-20260509-001"
        # 预先创建 run 目录，让 _generate_run_id mock 返回后 run_dir 实际存在
        run_dir = tmp_repo / "runs" / fixed_run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        original_path_open = _Path.open

        def _path_open_raises_on_meta(self_path, mode="r", **kwargs):
            """仅在写 meta.yaml 时抛 OSError，其他 Path.open 正常透传。"""
            if self_path.name == "meta.yaml" and "w" in mode:
                raise OSError("[Errno 28] No space left on device")
            return original_path_open(self_path, mode, **kwargs)

        # patch workflow_run 模块中的 _generate_run_id 和 REPO_ROOT
        with patch("workflow_run._generate_run_id", return_value=fixed_run_id):
            with patch("workflow_run.REPO_ROOT", tmp_repo):
                with patch.object(_Path, "open", _path_open_raises_on_meta):
                    rc = dispatcher.dispatch("run", [sample_template])

        assert rc == 1, (
            f"meta.yaml 写入 OSError 经 WorkflowError 包装后 dispatcher 应返回 1，实际 rc={rc}"
        )
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err, (
            f"dispatcher 应兜住 traceback 不暴露，实际 stderr：{captured.err}"
        )


# ============================================================
# F-001：_generate_req_id 单测
# ============================================================

class TestGenerateReqId:
    """_generate_req_id 空 requirements/ 时返回 REQ-{当年}-001。"""

    def test_empty_requirements_returns_first_id(self, tmp_repo: Path):
        """given_empty_requirements_when_generate_req_id_then_returns_REQ_YYYY_001。

        tmp_repo/requirements/ 已在 fixture 建好（空目录），
        断言返回 REQ-{当年}-001 且目录已创建。
        """
        import workflow_run as wr
        from datetime import datetime, timezone

        req_id = wr._generate_req_id(tmp_repo)

        year = datetime.now(timezone.utc).strftime("%Y")
        expected = f"REQ-{year}-001"
        assert req_id == expected, (
            f"空 requirements/ 首次调用期望 {expected}，实际：{req_id}"
        )
        assert (tmp_repo / "requirements" / req_id).is_dir(), (
            f"{req_id} 对应顶层目录未创建"
        )


class TestGenerateReqIdConcurrencySafe:
    """_generate_req_id 并发 3 路调用，3 个 REQ-ID 唯一（原子化验证）。"""

    def test_concurrent_req_id_no_collision(self, tmp_repo: Path):
        """given_three_concurrent_calls_when_generate_req_id_then_req_ids_are_unique ✓。

        使用 threading 三发 _generate_req_id，断言 3 个 req_id 互不重叠，
        且每个对应目录均已创建。复刻 TC-F5-G8 并发安全验证模式。
        用 threading 近似进程模型：mkdir(exist_ok=False) 的原子性在跨进程同样适用，
        无需 multiprocessing 提升测试复杂度。
        """
        import threading
        import workflow_run as wr

        results: list[str] = []
        errors: list[Exception] = []
        # Barrier 同步三线程起跑线，强化真并发竞争密度
        barrier = threading.Barrier(3)

        def worker() -> None:
            barrier.wait()  # 等所有线程就位后同步起跑，最大化竞争密度
            try:
                req_id = wr._generate_req_id(tmp_repo)
                results.append(req_id)
            except Exception as exc:
                errors.append(exc)

        # 同时启动三个线程竞争创建 req_id
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 断言：无异常 + 3 个 req_id 均不重复
        assert not errors, f"_generate_req_id 抛出异常：{errors}"
        assert len(results) == 3, f"期望 3 个 req_id，实际：{results}"
        assert len(set(results)) == 3, (
            f"并发生成的 req_id 存在重复：{results}"
        )
        # 确认 3 个目录都已实际创建
        for rid in results:
            assert (tmp_repo / "requirements" / rid).is_dir(), (
                f"req_id {rid!r} 对应顶层目录未创建"
            )


# TC-F1-3: max+1 策略一致（features.json F-001 acceptance[2]）
class TestGenerateReqIdMaxPlusOne:
    """_generate_req_id 存在多个现有目录时，返回 max+1 编号。"""

    def test_picks_max_plus_one_when_existing_dirs(self, tmp_repo: Path):
        """given_existing_dirs_003_and_007_when_generate_req_id_then_returns_008。

        预建 REQ-{当年}-003 和 REQ-{当年}-007，
        调用 _generate_req_id 后期望返回 REQ-{当年}-008，
        验证 max+1 策略与 _generate_run_id 保持一致。
        """
        import workflow_run as wr
        from datetime import datetime, timezone

        year = datetime.now(timezone.utc).strftime("%Y")
        req_dir = tmp_repo / "requirements"

        # 预建两个目录，非连续编号以验证取 max 而非 count
        (req_dir / f"REQ-{year}-003").mkdir()
        (req_dir / f"REQ-{year}-007").mkdir()

        req_id = wr._generate_req_id(tmp_repo)

        expected = f"REQ-{year}-008"
        assert req_id == expected, (
            f"存在 -003、-007 时 max+1 期望 {expected}，实际：{req_id}"
        )
        assert (req_dir / req_id).is_dir(), (
            f"{req_id} 对应顶层目录未创建"
        )


# ============================================================
# F-002：_bootstrap_requirement + _bootstrap_rollback 单测
# ============================================================
#
# 覆盖 features.json F-002 的 5 条 acceptance：
#   AC1 成功路径：4 文件/目录全存在
#   AC2 成功后当前分支 = feat/req-<id>
#   AC3 mkdir 失败时 req_dir 不残留
#   AC4 git checkout 失败时分支与目录全回滚
#   AC5 rollback 自身 IOError 不抛，仅 ERROR 日志
#
# 外部依赖处理策略：
#   - 不 mock 真 git：在 tmp_path 用 subprocess 起真 repo + 建 develop 分支，
#     保证 _checkout_feature_branch / _bootstrap_rollback 切换链路真跑过去
#   - 模板路径走真实 REPO_ROOT/.claude/skills/managing-requirement-lifecycle/templates/
#     （本 feature 不动模板，复用真实文件最简单可靠）
# ============================================================

import subprocess  # noqa: E402  F-002 测试用真 git


def _init_real_git_repo(tmp_path: Path) -> Path:
    """在 tmp_path 起一个真 git repo，配 user.name/email，建 develop 分支。

    F-002 测试基础设施——不 mock subprocess，让 _checkout_feature_branch /
    _bootstrap_rollback 的 git 子进程调用真实落到 tmp_path 上，杜绝 mock 偏离。

    返回：repo_root（与 tmp_path 相同，方便链式调用）。
    """
    # 0. 镜像 tmp_repo fixture：建 requirements/ 等顶层目录
    (tmp_path / "requirements").mkdir(exist_ok=True)
    (tmp_path / "runs").mkdir(exist_ok=True)

    def _run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, cwd=str(tmp_path), capture_output=True, text=True,
            check=check, timeout=10, **kwargs,
        )

    _run(["git", "init", "-q"])
    _run(["git", "config", "user.email", "f002@test.local"])
    _run(["git", "config", "user.name", "F-002 Test"])
    _run(["git", "config", "commit.gpgsign", "false"])
    # 建初始 commit 作为 develop 锚点
    (tmp_path / "README.md").write_text("F-002 test repo\n", encoding="utf-8")
    _run(["git", "add", "README.md"])
    _run(["git", "commit", "-q", "-m", "init"])
    # 切到 develop（rename 当前默认分支即可，避免依赖具体默认分支名）
    _run(["git", "branch", "-M", "develop"])
    return tmp_path


@pytest.fixture()
def real_git_repo(tmp_path: Path) -> Path:
    """真 git repo fixture：F-002 5 条 acceptance 共用。"""
    return _init_real_git_repo(tmp_path)


class TestBootstrapRequirementHappyPath:
    """AC1 + AC2：成功路径——文件/目录齐全 + 分支切到 feat/req-<id>。"""

    def test_bootstrap_requirement_when_success_creates_all_artifacts(
        self, real_git_repo: Path,
    ):
        """given_clean_repo_when_bootstrap_then_all_artifacts_created_and_branch_switched。"""
        import workflow_run as wr

        req_id = wr._generate_req_id(real_git_repo)  # 顶层目录已建
        template_path = real_git_repo / ".claude" / "workflows" / "requirement" / "fake.yaml"

        # patch REPO_ROOT 让 _render_meta_yaml / _render_plan_md 读真实模板
        with patch("workflow_run.REPO_ROOT", _REPO_ROOT):
            req_dir = wr._bootstrap_requirement(
                req_id=req_id,
                title="F-002 测试需求",
                template_id="standard-8phase",
                template_path=template_path,
                arguments="",
                repo_root=real_git_repo,
            )

        # AC1：4 文件/目录全存在
        assert req_dir == real_git_repo / "requirements" / req_id
        assert (req_dir / "artifacts").is_dir(), "artifacts/ 目录应存在"
        assert (req_dir / "meta.yaml").is_file(), "meta.yaml 应存在"
        assert (req_dir / "plan.md").is_file(), "plan.md 应存在"
        assert (req_dir / "process.txt").is_file(), "process.txt 应存在"
        # process.txt 是空（hook 首次触发才填）
        assert (req_dir / "process.txt").read_text(encoding="utf-8") == ""

        # meta.yaml 至少含 req_id + title 渲染结果
        meta_text = (req_dir / "meta.yaml").read_text(encoding="utf-8")
        assert req_id in meta_text, f"meta.yaml 应含 req_id={req_id}"
        assert "F-002 测试需求" in meta_text, "meta.yaml 应含 title"
        # 流程组 base_branch 渲染为 develop（_init_real_git_repo 唯一存在）
        assert "base_branch: develop" in meta_text, "base_branch 应渲染为 develop"

        # plan.md 含 title
        plan_text = (req_dir / "plan.md").read_text(encoding="utf-8")
        assert "F-002 测试需求" in plan_text

        # jsonl workflow_started 写入
        events, _ = read_events(req_dir / "run-state.jsonl")
        types = [e["type"] for e in events]
        assert "workflow_started" in types, f"应写入 workflow_started 事件，实际：{types}"

        # AC2：当前分支 = feat/req-<id>（小写、去 REQ- 前缀）
        expected_branch = f"feat/req-{req_id[len('REQ-'):].lower()}"
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(real_git_repo), capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == expected_branch, (
            f"分支应切到 {expected_branch}，实际：{result.stdout.strip()}"
        )


class TestBootstrapRequirementMkdirFailure:
    """AC3：mkdir artifacts/ 失败 → BootstrapError + rollback 后 req_dir 不残留。"""

    def test_bootstrap_requirement_when_mkdir_fails_then_rollback_leaves_no_residue(
        self, real_git_repo: Path, monkeypatch, caplog,
    ):
        """given_mkdir_raises_when_bootstrap_then_rollback_removes_req_dir。"""
        import workflow_run as wr

        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = wr._current_branch(real_git_repo)
        assert previous_branch == "develop"

        # 仅对 artifacts/ 子目录的 mkdir 抛错（_generate_req_id 已经 mkdir 完顶层目录）
        target_artifacts = real_git_repo / "requirements" / req_id / "artifacts"
        original_mkdir = Path.mkdir

        def fail_on_artifacts(self_path, *args, **kwargs):
            if self_path == target_artifacts:
                raise OSError("E-TEST: 模拟 mkdir 失败")
            return original_mkdir(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", fail_on_artifacts)

        # 触发 bootstrap：应抛 BootstrapError
        with patch("workflow_run.REPO_ROOT", _REPO_ROOT):
            with pytest.raises(wr.BootstrapError) as exc_info:
                wr._bootstrap_requirement(
                    req_id=req_id,
                    title="mkdir 失败用例",
                    template_id="standard-8phase",
                    template_path=real_git_repo / "fake.yaml",
                    arguments="",
                    repo_root=real_git_repo,
                )
        assert exc_info.value.artifacts_created is True
        assert exc_info.value.branch_created is False

        # 还原 mkdir，否则 rollback 自己也 mkdir 会受影响
        monkeypatch.setattr(Path, "mkdir", original_mkdir)

        # 调 rollback：req_dir 应被删干净
        wr._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            exc_info.value.artifacts_created, exc_info.value.branch_created,
        )
        assert not (real_git_repo / "requirements" / req_id).exists(), (
            f"rollback 后 requirements/{req_id}/ 不应残留"
        )

        # 分支应保持 develop（未切换过）
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(real_git_repo), capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == "develop"


class TestBootstrapRequirementCheckoutFailure:
    """AC4：git checkout -b 失败 → BootstrapError + rollback 后分支与目录全恢复。"""

    def test_bootstrap_requirement_when_checkout_fails_then_full_rollback(
        self, real_git_repo: Path, monkeypatch,
    ):
        """given_branch_already_exists_when_bootstrap_then_rollback_restores_state。"""
        import workflow_run as wr

        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = wr._current_branch(real_git_repo)
        # 故意预建同名分支 → git checkout -b 必然失败 rc≠0
        target_branch = f"feat/req-{req_id[len('REQ-'):].lower()}"
        subprocess.run(
            ["git", "branch", target_branch],
            cwd=str(real_git_repo), check=True, capture_output=True,
        )

        with patch("workflow_run.REPO_ROOT", _REPO_ROOT):
            with pytest.raises(wr.BootstrapError) as exc_info:
                wr._bootstrap_requirement(
                    req_id=req_id,
                    title="checkout 失败用例",
                    template_id="standard-8phase",
                    template_path=real_git_repo / "fake.yaml",
                    arguments="",
                    repo_root=real_git_repo,
                )
        # checkout 失败发生在 mkdir/write 之后，artifacts_created=True、branch_created=False
        assert exc_info.value.artifacts_created is True
        assert exc_info.value.branch_created is False

        # 关键回归：rollback 前预建分支还在；rollback 后该分支应被 git branch -D 清掉
        # 但因为 branch_created=False，rollback 不会去删 target_branch——它认为新分支没建成
        # 所以预建分支保留是正确行为；我们关心的是 req_dir 应被清掉
        wr._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            exc_info.value.artifacts_created, exc_info.value.branch_created,
        )

        assert not (real_git_repo / "requirements" / req_id).exists(), (
            "checkout 失败后 rollback 应清掉 req_dir"
        )

        # 当前分支应仍是 develop（_bootstrap_requirement 的 _checkout_feature_branch 失败了，
        # 不会切过去；rollback 也不需要切）
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(real_git_repo), capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == "develop"

    def test_bootstrap_rollback_when_branch_created_then_restores_previous_branch(
        self, real_git_repo: Path,
    ):
        """given_branch_created_true_when_rollback_then_branch_deleted_and_previous_restored。

        模拟 _bootstrap_requirement 已 checkout 到 feat/req-<id>，但后续写 jsonl
        失败的场景——branch_created=True，rollback 应切回 develop + 删 feat 分支。
        """
        import workflow_run as wr

        req_id = wr._generate_req_id(real_git_repo)
        previous_branch = "develop"
        # 手动模拟"分支已切"的中间态
        target_branch = f"feat/req-{req_id[len('REQ-'):].lower()}"
        subprocess.run(
            ["git", "checkout", "-b", target_branch],
            cwd=str(real_git_repo), check=True, capture_output=True,
        )
        # 模拟 artifacts 已建一些文件
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir()
        (real_git_repo / "requirements" / req_id / "meta.yaml").write_text("x", encoding="utf-8")

        wr._bootstrap_rollback(
            req_id, real_git_repo, previous_branch,
            artifacts_created=True, branch_created=True,
        )

        # 当前分支已切回 develop
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(real_git_repo), capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == "develop"
        # 新分支已被删
        branches = subprocess.run(
            ["git", "branch", "--list", target_branch],
            cwd=str(real_git_repo), capture_output=True, text=True, check=True,
        ).stdout
        assert target_branch not in branches, f"feat 分支应被删除，实际：{branches!r}"
        # req_dir 已 rmtree
        assert not (real_git_repo / "requirements" / req_id).exists()


class TestBootstrapRollbackSilentOnIOError:
    """AC5：rollback 自身 IOError 不抛，仅 ERROR 日志。"""

    def test_bootstrap_rollback_when_rmtree_raises_then_no_exception_propagated(
        self, real_git_repo: Path, monkeypatch, caplog,
    ):
        """given_rmtree_raises_oserror_when_rollback_then_logged_not_raised。"""
        import workflow_run as wr
        import logging as logging_mod

        req_id = wr._generate_req_id(real_git_repo)
        # 准备 req_dir 让 rollback 真的尝试 rmtree
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir()

        def fail_rmtree(path):
            raise OSError("E-TEST: 模拟 rmtree 失败（磁盘只读）")

        monkeypatch.setattr("workflow_run.shutil.rmtree", fail_rmtree)
        caplog.set_level(logging_mod.ERROR, logger="root")

        # 不应抛任何异常
        wr._bootstrap_rollback(
            req_id, real_git_repo, "develop",
            artifacts_created=True, branch_created=False,
        )

        # 应有 ERROR 日志
        error_msgs = [r.message for r in caplog.records if r.levelno >= logging_mod.ERROR]
        assert any("rmtree" in m or req_id in m for m in error_msgs), (
            f"rollback 应记录 ERROR 日志，实际：{error_msgs}"
        )

    def test_bootstrap_rollback_when_called_repeatedly_then_idempotent(
        self, real_git_repo: Path,
    ):
        """given_already_rolled_back_when_rollback_again_then_no_raise。

        幂等验证：rollback 已成功清理后，再次调用不应抛 FileNotFoundError。
        """
        import workflow_run as wr

        req_id = wr._generate_req_id(real_git_repo)
        (real_git_repo / "requirements" / req_id / "artifacts").mkdir()

        wr._bootstrap_rollback(req_id, real_git_repo, "develop", True, False)
        # 第二次调用：req_dir 已被删，应静默
        wr._bootstrap_rollback(req_id, real_git_repo, "develop", True, False)


class TestParseArgs:
    """_parse_args 的几个典型切分约定。"""

    def test_parse_args_with_template_and_title(self):
        import workflow_run as wr
        tid, args, title = wr._parse_args(["standard-8phase", "做个登录页"])
        assert tid == "standard-8phase"
        assert title == "做个登录页"
        assert args == "做个登录页"

    def test_parse_args_with_only_template_falls_back_title_to_template_id(self):
        import workflow_run as wr
        tid, args, title = wr._parse_args(["standard-8phase"])
        assert tid == "standard-8phase"
        assert args == ""
        assert title == "standard-8phase"  # fallback 避免 plan.md __TITLE__ 留空

    def test_parse_args_empty_raises_workflow_error(self):
        from common import WorkflowError
        import workflow_run as wr
        with pytest.raises(WorkflowError):
            wr._parse_args([])


class TestIsRequirementTemplate:
    """_is_requirement_template：category 字段优先，路径兜底。"""

    def test_yaml_with_category_requirement_returns_true(self, tmp_path: Path):
        import workflow_run as wr
        yaml_path = tmp_path / "x.yaml"
        yaml_path.write_text("name: t\ncategory: requirement\n", encoding="utf-8")
        assert wr._is_requirement_template(yaml_path) is True

    def test_yaml_with_category_review_returns_false(self, tmp_path: Path):
        import workflow_run as wr
        yaml_path = tmp_path / "x.yaml"
        yaml_path.write_text("name: t\ncategory: review\n", encoding="utf-8")
        assert wr._is_requirement_template(yaml_path) is False

    def test_yaml_without_category_falls_back_to_path_match(self, tmp_path: Path):
        """无 category 字段时按路径兜底 /requirement/ 片段。"""
        import workflow_run as wr
        req_dir = tmp_path / "requirement"
        req_dir.mkdir()
        yaml_path = req_dir / "x.yaml"
        yaml_path.write_text("name: t\n", encoding="utf-8")
        assert wr._is_requirement_template(yaml_path) is True

        other_yaml = tmp_path / "review.yaml"
        other_yaml.write_text("name: t\n", encoding="utf-8")
        assert wr._is_requirement_template(other_yaml) is False
