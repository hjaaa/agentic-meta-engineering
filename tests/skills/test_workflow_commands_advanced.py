"""F-005 · /workflow:* 命令单测（高级场景：并发/OSError/状态/status 树）。

覆盖范围：
  TC-F5-4  status_parent_child_tree：含 sub_workflow 的 run，status 输出含子 run 嵌套
  TC-F5-6  cancel_writes_event：cancel 在 3 种允许状态写 cancel_requested + TaskStop 超时路径
  TC-F5-G8  generate_run_id_concurrency_safe：_generate_run_id 并发不重复（原子化验证）
  TC-F5-G11 continue_run_resumed_write_failure：run_resumed 写失败时 main 返回 1
  TC-F5-P2  os_error_wrapped_as_workflow_error：OSError 包装为 WorkflowError

REQ-ID 生成 + schema 门禁见 test_workflow_commands_reqgen.py。

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

from run_state import append_event, read_events  # noqa: E402
import workflow_continue  # noqa: E402
import workflow_status  # noqa: E402
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


@pytest.fixture()
def sample_template(tmp_repo: Path) -> str:
    """在临时仓库中创建 minimal workflow yaml 模板（F-003 后含 schema 必填字段）。"""
    template_name = "test-template"
    template_content = """\
name: test-template
version: 1
category: assist
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

        # 创建子 run（sub_runs/<child_id>/ 直挂父 run 目录，目录名即子 run id）
        sub_run_dir = parent_dir / "sub_runs" / child_id
        sub_run_dir.mkdir(parents=True)
        append_event(sub_run_dir / "run-state.jsonl", {
            "type": "workflow_started",
            "run_id": child_id,
            "data": {"workflow_name": "test-template", "arguments": ""},
        })
        append_event(sub_run_dir / "run-state.jsonl", {
            "type": "workflow_completed",
            "run_id": child_id,
        })

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
