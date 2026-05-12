"""F-005 · /workflow:* 命令单测（happy path + 命令链路）。

覆盖范围：
  TC-F5-1  happy_path：9 命令各取矩阵 ✓ 状态，验证 jsonl 事件正确写入
  TC-F5-5  chain_run_continue_save_status：run → continue → save → status 4 命令链路

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

from run_state import read_events  # noqa: E402
import workflow_run  # noqa: E402
import workflow_continue  # noqa: E402
import workflow_save  # noqa: E402
import workflow_status  # noqa: E402
import workflow_list  # noqa: E402
import workflow_approve  # noqa: E402
import workflow_reject  # noqa: E402
import workflow_rollback_cmd  # noqa: E402
import workflow_cancel  # noqa: E402

# ---------- 共享辅助（从 conftest 导入）----------

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

    def test_continue_in_running_state_calls_main_loop(self, tmp_repo: Path):
        """given_run_state_running_when_continue_then_main_loop_called_returns_0。

        F-007 用真实 _main_loop 替换了原 stub；本用例 mock _load_workflow_for_run 返回
        最小 workflow dict、mock _main_loop 避免实际派发，只验证 main() 正确编排并返回 0。
        """
        run_id = "RUN-20260509-001"
        _make_run_dir(tmp_repo, run_id, "running")

        _fake_workflow = {"id": "fake", "nodes": []}
        with _patch_git_branch(run_id), \
                patch("workflow_continue._load_workflow_for_run", return_value=_fake_workflow), \
                patch("workflow_continue._main_loop") as mock_loop:
            rc = workflow_continue.main([], repo_root=tmp_repo)

        assert rc == 0, f"continue 在 running 状态应返回 0，实际 rc={rc}"
        assert mock_loop.call_count == 1, "main() 应调用 _main_loop 一次"

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
        # mock _main_loop 避免加载真实 workflow 文件（链路测试关注事件序列，不验证派发）
        _fake_workflow = {"id": "fake", "nodes": []}
        with _patch_git_branch(run_id), \
                patch("workflow_continue._load_workflow_for_run", return_value=_fake_workflow), \
                patch("workflow_continue._main_loop"):
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
