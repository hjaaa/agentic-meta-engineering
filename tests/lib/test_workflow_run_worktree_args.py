"""F-003 · workflow_run.py worktree 参数解析 + bootstrap retry 骨架 单元测试。

覆盖：
- TC-F03-1：_parse_args --slug 空格形式
- TC-F03-2：_parse_args --slug=value 等号形式
- TC-F03-3：_parse_args --worktree-policy 空格形式
- TC-F03-4：_parse_args --worktree-policy=value 等号形式
- TC-F03-5：_parse_args --no-worktree 单独 flag
- TC-F03-6：_parse_args --slug 后接 -- 选项（fail-closed）
- TC-F03-7：_parse_args 未知选项（fail-closed）
- TC-F03-8：_run_requirement 中文标题无 slug → exit 1
- TC-F03-9：_run_requirement ASCII 标题自动派生 slug
- TC-F03-10：_run_requirement 显式 slug 覆盖自动派生
- TC-F03-11：_run_requirement bootstrap retry（path_or_branch_exists 重试，第二次成功）
- TC-F03-12：_run_requirement bootstrap 其他 reason 不重试，异常透传 + rollback 触发

测试运行：
    python3 -m pytest tests/lib/test_workflow_run_worktree_args.py -v
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "lib"))

from workflow_run import (  # noqa: E402
    RunArgs,
    _parse_args,
    _run_requirement,
)
from workflow_bootstrap import BootstrapError  # noqa: E402
from worktree_manager import WorktreeBootstrapError  # noqa: E402
from workflow_run import WorkflowError  # noqa: E402



# ============================================================================
# TC-F03-1：--slug 空格形式
# ============================================================================

def test_parse_args_slug_space_form() -> None:
    """--slug value（空格形式）正确解析到 RunArgs.slug。"""
    result = _parse_args(["standard-8phase", "My Title", "--slug", "my-slug"])
    assert isinstance(result, RunArgs)
    assert result.slug == "my-slug"
    assert result.template_id == "standard-8phase"
    assert result.title == "My Title"
    assert result.no_worktree is False
    assert result.worktree_policy is None


# ============================================================================
# TC-F03-2：--slug=value 等号形式
# ============================================================================

def test_parse_args_slug_equal_form() -> None:
    """--slug=value（等号形式）正确解析到 RunArgs.slug。"""
    result = _parse_args(["standard-8phase", "My Title", "--slug=my-slug"])
    assert result.slug == "my-slug"
    assert result.template_id == "standard-8phase"
    assert result.title == "My Title"


# ============================================================================
# TC-F03-3：--worktree-policy 空格形式
# ============================================================================

def test_parse_args_worktree_policy_space_form() -> None:
    """--worktree-policy value（空格形式）正确解析到 RunArgs.worktree_policy。"""
    result = _parse_args(["tmpl", "Title", "--worktree-policy", "auto"])
    assert result.worktree_policy == "auto"
    assert result.template_id == "tmpl"
    assert result.slug is None
    assert result.no_worktree is False


# ============================================================================
# TC-F03-4：--worktree-policy=value 等号形式
# ============================================================================

def test_parse_args_worktree_policy_equal_form() -> None:
    """--worktree-policy=value（等号形式）正确解析到 RunArgs.worktree_policy。"""
    result = _parse_args(["tmpl", "Title", "--worktree-policy=current"])
    assert result.worktree_policy == "current"
    assert result.template_id == "tmpl"


# ============================================================================
# TC-F03-5：--no-worktree 单独 flag
# ============================================================================

def test_parse_args_no_worktree_flag() -> None:
    """--no-worktree flag 正确设置 RunArgs.no_worktree=True。"""
    result = _parse_args(["tmpl", "My Title", "--no-worktree"])
    assert result.no_worktree is True
    assert result.slug is None
    assert result.worktree_policy is None
    assert result.title == "My Title"


# ============================================================================
# TC-F03-6：--slug 后接 -- 选项（fail-closed）
# ============================================================================

def test_parse_args_slug_space_missing_value_fail_closed() -> None:
    """--slug 后紧接 --next-opt（无值）应抛 WorkflowError。"""
    with pytest.raises(WorkflowError, match="缺少值"):
        _parse_args(["tmpl", "Title", "--slug", "--no-worktree"])


# ============================================================================
# TC-F03-7：未知选项（fail-closed）
# ============================================================================

def test_parse_args_unknown_option_fail_closed() -> None:
    """遇到未知 -- 选项时应抛 WorkflowError。"""
    with pytest.raises(WorkflowError, match="未知选项"):
        _parse_args(["tmpl", "Title", "--unknown-opt", "value"])


# ============================================================================
# TC-F03-8：中文标题 + 无 --slug → exit 1，stderr 含关键提示
# ============================================================================

def test_run_requirement_chinese_title_without_slug_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """中文标题且未传 --slug 时，_run_requirement 返回 1，stderr 含 '中文标题需显式 --slug'。"""
    args = RunArgs(
        template_id="standard-8phase",
        template_args="",
        title="中文需求标题",
        slug=None,
        no_worktree=False,
        worktree_policy=None,
    )
    result = _run_requirement(args, Path("/fake/template.yaml"), tmp_path)
    assert result == 1
    captured = capsys.readouterr()
    assert "中文标题需显式 --slug" in captured.err


# ============================================================================
# TC-F03-9：ASCII 标题自动派生 slug
# ============================================================================

def test_run_requirement_ascii_title_auto_derive_slug(
    tmp_path: Path,
) -> None:
    """ASCII 标题时自动派生 slug（无需显式 --slug），bootstrap 正常调用。"""
    args = RunArgs(
        template_id="standard-8phase",
        template_args="",
        title="My Feature Title",
        slug=None,
        no_worktree=False,
        worktree_policy=None,
    )
    # mock _bootstrap_requirement 返回成功（req_dir）
    fake_req_dir = tmp_path / "requirements" / "20260518-my-feature-title"
    fake_req_dir.mkdir(parents=True, exist_ok=True)

    with patch("workflow_run._bootstrap_requirement", return_value=fake_req_dir) as mock_bs, \
         patch("workflow_run._current_branch", return_value="develop"), \
         patch("workflow_run._strip_req_prefix", return_value="20260518-my-feature-title"), \
         patch("workflow_run._scan_existing_requirement_keys", return_value=set()), \
         patch("workflow_run.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 18)
        result = _run_requirement(args, Path("/fake/template.yaml"), tmp_path)

    assert result == 0
    # 验证 bootstrap 被调用，且 req_id 含 ASCII 派生的 slug
    assert mock_bs.called
    req_id_used = mock_bs.call_args[0][0]
    assert "my-feature-title" in req_id_used


# ============================================================================
# TC-F03-10：显式 slug 覆盖自动派生
# ============================================================================

def test_run_requirement_explicit_slug_overrides_derive(
    tmp_path: Path,
) -> None:
    """显式 --slug 时，使用用户提供的 slug 而不是自动派生。"""
    args = RunArgs(
        template_id="standard-8phase",
        template_args="",
        title="Any ASCII Title",
        slug="custom-slug",
        no_worktree=False,
        worktree_policy=None,
    )
    fake_req_dir = tmp_path / "requirements" / "20260518-custom-slug"
    fake_req_dir.mkdir(parents=True, exist_ok=True)

    with patch("workflow_run._bootstrap_requirement", return_value=fake_req_dir) as mock_bs, \
         patch("workflow_run._current_branch", return_value="develop"), \
         patch("workflow_run._strip_req_prefix", return_value="20260518-custom-slug"), \
         patch("workflow_run._scan_existing_requirement_keys", return_value=set()), \
         patch("workflow_run.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 18)
        result = _run_requirement(args, Path("/fake/template.yaml"), tmp_path)

    assert result == 0
    req_id_used = mock_bs.call_args[0][0]
    assert "custom-slug" in req_id_used


# ============================================================================
# TC-F03-11：bootstrap retry（path_or_branch_exists 重试，第二次成功）
# ============================================================================

def test_run_requirement_bootstrap_retry_path_exists(
    tmp_path: Path,
) -> None:
    """第一次 bootstrap 抛 WorktreeBootstrapError(reason='path_or_branch_exists')，
    第二次成功；断言：第二次 req_id 不等于第一次（existing_keys 已 bump）。
    """
    args = RunArgs(
        template_id="standard-8phase",
        template_args="",
        title="Retry Feature",
        slug="retry-feat",
        no_worktree=False,
        worktree_policy=None,
    )

    fixed_date = date(2026, 5, 18)
    # 第一次 req_id 将是 20260518-retry-feat
    # 第二次 req_id 将是 20260518-retry-feat-02（existing_keys 含第一次 key）
    first_req_id = "20260518-retry-feat"
    second_req_id = "20260518-retry-feat-02"

    fake_req_dir_second = tmp_path / "requirements" / second_req_id
    fake_req_dir_second.mkdir(parents=True, exist_ok=True)

    call_count = [0]
    captured_req_ids = []

    def fake_bootstrap(req_id, title, template_id, template_path, template_args, root, **kwargs):
        captured_req_ids.append(req_id)
        call_count[0] += 1
        if call_count[0] == 1:
            raise WorktreeBootstrapError(
                "path or branch already exists",
                reason="path_or_branch_exists",
                artifacts_created=False,
                branch_created=False,
            )
        # 第二次成功
        return fake_req_dir_second

    with patch("workflow_run._bootstrap_requirement", side_effect=fake_bootstrap), \
         patch("workflow_run._current_branch", return_value="develop"), \
         patch("workflow_run._strip_req_prefix", side_effect=lambda k: k), \
         patch("workflow_run._scan_existing_requirement_keys", return_value=set()), \
         patch("workflow_run.date") as mock_date:
        mock_date.today.return_value = fixed_date
        result = _run_requirement(args, Path("/fake/template.yaml"), tmp_path)

    assert result == 0
    assert call_count[0] == 2, f"bootstrap 应被调用 2 次，实际 {call_count[0]} 次"
    assert len(captured_req_ids) == 2
    assert captured_req_ids[0] != captured_req_ids[1], (
        f"第二次 req_id 应不同于第一次，实际：{captured_req_ids}"
    )


# ============================================================================
# TC-F03-12：其他 reason 不重试，异常透传 + rollback 触发
# ============================================================================

def test_run_requirement_bootstrap_other_reason_no_retry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """BootstrapError 无 reason（或 reason!='path_or_branch_exists'）：
    - 不重试（bootstrap 只被调用 1 次）
    - rollback 被触发
    - _run_requirement 返回 1，stderr 含 bootstrap 失败信息
    """
    args = RunArgs(
        template_id="standard-8phase",
        template_args="",
        title="Other Failure",
        slug="other-fail",
        no_worktree=False,
        worktree_policy=None,
    )

    call_count = [0]

    def fake_bootstrap(req_id, title, template_id, template_path, template_args, root, **kwargs):
        call_count[0] += 1
        # 无 reason 字段的 BootstrapError（基类）
        raise BootstrapError(
            "some unrecoverable error",
            artifacts_created=True,
            branch_created=False,
        )

    rollback_called = [False]

    def fake_rollback(
        req_id, root, prev_branch, *,
        artifacts_created, branch_created, worktree_info=None,
    ):
        rollback_called[0] = True

    with patch("workflow_run._bootstrap_requirement", side_effect=fake_bootstrap), \
         patch("workflow_run._bootstrap_rollback", side_effect=fake_rollback), \
         patch("workflow_run._current_branch", return_value="develop"), \
         patch("workflow_run._scan_existing_requirement_keys", return_value=set()), \
         patch("workflow_run.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 18)
        result = _run_requirement(args, Path("/fake/template.yaml"), tmp_path)

    assert result == 1
    assert call_count[0] == 1, f"不应重试，bootstrap 应只调用 1 次，实际 {call_count[0]} 次"
    assert rollback_called[0], "rollback 应被触发"
    captured = capsys.readouterr()
    assert "bootstrap 失败" in captured.err


# ============================================================================
# TC-F03-13：--worktree-policy=bogus 等号形式应抛 WorkflowError（F-8 修复 + AC5）
# ============================================================================

def test_parse_args_worktree_policy_invalid_value_equal_form_fail_closed() -> None:
    """--worktree-policy=bogus 等号形式应抛 WorkflowError（F-8 修复 + AC5）。"""
    with pytest.raises(WorkflowError, match="worktree-policy 非法值"):
        _parse_args(["tmpl", "Title", "--worktree-policy=bogus"])


# ============================================================================
# TC-F03-14：--worktree-policy bogus 空格形式应抛 WorkflowError（F-8 修复 + AC5）
# ============================================================================

def test_parse_args_worktree_policy_invalid_value_space_form_fail_closed() -> None:
    """--worktree-policy bogus 空格形式应抛 WorkflowError（F-8 修复 + AC5）。"""
    with pytest.raises(WorkflowError, match="worktree-policy 非法值"):
        _parse_args(["tmpl", "Title", "--worktree-policy", "bogus"])


# ============================================================================
# TC-F03-15（F-004 rev2 F-1）：baseline_failed_required → 不进 rollback，保留现场
# ============================================================================

def test_run_requirement_when_baseline_failed_required_retains_worktree_no_rollback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """BootstrapError(reason='baseline_failed_required', retain_worktree=True, worktree_info=mock_wi)：
    - _bootstrap_rollback **未被调用**（rollback 跳过）
    - stderr 含 "保留现场" 提示
    - 返回 1
    """
    args = RunArgs(
        template_id="standard-8phase",
        template_args="",
        title="Baseline Failed Required",
        slug="baseline-fail",
        no_worktree=False,
        worktree_policy=None,
    )

    # 构造 worktree_info（不依赖真 WorktreeInfo dataclass 的 frozen 约束的复杂字段，
    # 用 MagicMock 即可——_bootstrap_rollback 自身不会被调，路径只走 retain 分支）
    mock_wi = MagicMock()
    mock_wi.path = tmp_path / ".worktrees" / "feat-req-baseline-fail"
    mock_wi.owner = "workflow"
    mock_wi.created = True

    def fake_bootstrap(req_id, title, template_id, template_path, template_args, root, **kwargs):
        raise BootstrapError(
            "baseline failed required=true",
            reason="baseline_failed_required",
            retain_worktree=True,
            branch_created=True,
            artifacts_created=True,
            worktree_info=mock_wi,
        )

    rollback_calls = []

    def spy_rollback(*pos_args, **kwargs):
        rollback_calls.append((pos_args, kwargs))

    with patch("workflow_run._bootstrap_requirement", side_effect=fake_bootstrap), \
         patch("workflow_run._bootstrap_rollback", side_effect=spy_rollback), \
         patch("workflow_run._current_branch", return_value="develop"), \
         patch("workflow_run._scan_existing_requirement_keys", return_value=set()), \
         patch("workflow_run.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 18)
        result = _run_requirement(args, Path("/fake/template.yaml"), tmp_path)

    assert result == 1
    assert len(rollback_calls) == 0, (
        f"retain_worktree=True 时 _bootstrap_rollback 必须 **不** 被调用，"
        f"实际调用 {len(rollback_calls)} 次"
    )
    captured = capsys.readouterr()
    assert "保留现场" in captured.err, (
        f"stderr 应含 '保留现场' 提示，实际：{captured.err!r}"
    )


# ============================================================================
# TC-F03-16（F-004 rev2 F-2）：bootstrap 其它 reason → rollback 收到 worktree_info
# ============================================================================

def test_run_requirement_when_bootstrap_fails_passes_worktree_info_to_rollback(
    tmp_path: Path,
) -> None:
    """BootstrapError(reason='other', worktree_info=mock_wi)：
    - _bootstrap_rollback 被调用
    - worktree_info kwarg 与 mock_wi 一致（避免孤儿 worktree）
    """
    args = RunArgs(
        template_id="standard-8phase",
        template_args="",
        title="Other Failure With Worktree",
        slug="other-with-wt",
        no_worktree=False,
        worktree_policy=None,
    )

    mock_wi = MagicMock()
    mock_wi.path = tmp_path / ".worktrees" / "feat-req-other-with-wt"
    mock_wi.owner = "workflow"
    mock_wi.created = True

    def fake_bootstrap(req_id, title, template_id, template_path, template_args, root, **kwargs):
        raise BootstrapError(
            "some unrecoverable error after worktree created",
            reason="other",
            artifacts_created=True,
            branch_created=True,
            worktree_info=mock_wi,
        )

    captured_kwargs = {}

    def spy_rollback(req_id, root, prev_branch, *, artifacts_created, branch_created,
                     worktree_info=None):
        captured_kwargs["worktree_info"] = worktree_info
        captured_kwargs["artifacts_created"] = artifacts_created
        captured_kwargs["branch_created"] = branch_created

    with patch("workflow_run._bootstrap_requirement", side_effect=fake_bootstrap), \
         patch("workflow_run._bootstrap_rollback", side_effect=spy_rollback), \
         patch("workflow_run._current_branch", return_value="develop"), \
         patch("workflow_run._scan_existing_requirement_keys", return_value=set()), \
         patch("workflow_run.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 18)
        result = _run_requirement(args, Path("/fake/template.yaml"), tmp_path)

    assert result == 1
    assert captured_kwargs.get("worktree_info") is mock_wi, (
        f"_bootstrap_rollback 应收到 worktree_info=mock_wi，实际：{captured_kwargs}"
    )
    assert captured_kwargs.get("artifacts_created") is True
    assert captured_kwargs.get("branch_created") is True
