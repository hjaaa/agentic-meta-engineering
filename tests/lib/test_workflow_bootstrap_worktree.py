"""F-004 · workflow_bootstrap.py worktree-first 改造测试（10 用例）。

覆盖详细设计 §3.4 测试骨架：
  1. _setup_worktree_or_branch auto 路径 → create_worktree
  2. _setup_worktree_or_branch current + linked → bind owner='external'
  3. _setup_worktree_or_branch current + 普通 repo → fail-closed
  4. _setup_worktree_or_branch never → fallback _checkout_feature_branch
  5. _bootstrap_requirement 成功路径 artifacts 落 worktree path（R1）
  6. _bootstrap_requirement baseline required=true rc!=0 → retain_worktree=True 不进 rollback
  7. _bootstrap_requirement baseline required=false rc!=0 → warning + 继续
  8. _bootstrap_rollback worktree remove 严格先于 branch -D
  9. _bootstrap_rollback 主仓根 + worktree path 双扫 rmtree
 10. _bootstrap_rollback 部分状态（仅 worktree / 仅 branch）幂等

实现策略：mock worktree_manager 各 helper 避免真起 worktree；保留
_checkout_feature_branch 走真 git 路径（已被 tests/skills/test_workflow_bootstrap.py
覆盖，本测试集仅 mock 外圈用 case 4 验证 fallback 调用）。
"""
from __future__ import annotations

import logging as logging_mod
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------- 路径注入 ----------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import workflow_bootstrap as wb  # noqa: E402
import worktree_manager  # noqa: E402
from worktree_manager import (  # noqa: E402
    SetupResult,
    WorktreeBootstrapError,
    WorktreeInfo,
    WorktreeState,
)


# ============================================================================
# 工具：构造 WorktreeState / fake repo
# ============================================================================

def _fake_state(
    *,
    is_linked: bool,
    repo_root: Path,
    branch: str = "develop",
    is_git_repo: bool = True,
    is_detached: bool = False,
) -> WorktreeState:
    """构造一个合法 WorktreeState；linked 时 git_dir != git_common_dir。"""
    git_common = repo_root / ".git"
    git_dir = git_common / "worktrees" / "fake" if is_linked else git_common
    return WorktreeState(
        is_git_repo=is_git_repo,
        is_linked_worktree=is_linked,
        is_submodule=False,
        is_detached=is_detached,
        branch=branch if not is_detached else "",
        worktree_path=repo_root,
        git_dir=git_dir,
        git_common_dir=git_common,
    )


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """轻量假 repo：仅建 .gitignore + .git/ 占位，让 ensure_worktree_dir_ignored 通过。"""
    (tmp_path / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
    return tmp_path


# ============================================================================
# Case 1：_setup_worktree_or_branch auto 路径 → create_worktree
# ============================================================================

def test_setup_worktree_or_branch_auto_creates(fake_repo: Path):
    """auto + 非 linked worktree → 调 create_worktree 返回 WorktreeInfo(owner='workflow')。"""
    req_id = "20260518-test-auto"
    expected_location = fake_repo / ".worktrees" / f"feat-req-{req_id}"
    expected_info = WorktreeInfo(
        path=expected_location,
        branch=f"feat/req-{req_id}",
        base_branch="develop",
        owner="workflow",
        created=True,
    )

    with patch.object(worktree_manager, "detect_worktree_state",
                      return_value=_fake_state(is_linked=False, repo_root=fake_repo)), \
         patch.object(worktree_manager, "ensure_worktree_dir_ignored") as mock_ensure, \
         patch.object(worktree_manager, "create_worktree", return_value=expected_info) as mock_create:
        info = wb._setup_worktree_or_branch(
            req_id, fake_repo, "develop",
            worktree_policy="auto", yaml_worktree_cfg={},
        )

    assert info is expected_info
    assert info.owner == "workflow"
    assert info.created is True
    mock_ensure.assert_called_once()
    mock_create.assert_called_once()
    # create_worktree 调用参数校验：branch 应来自 branch_for_requirement_key
    call_kwargs = mock_create.call_args
    assert call_kwargs.args[1] == f"feat/req-{req_id}", "branch 应为 feat/req-<key>"


# ============================================================================
# Case 2：current + linked → bind owner='external'
# ============================================================================

def test_setup_worktree_or_branch_current_in_linked_binds(fake_repo: Path):
    """current + linked worktree → 不调 create_worktree，bind 复用当前。"""
    req_id = "20260518-test-bind"
    state = _fake_state(is_linked=True, repo_root=fake_repo, branch="feat/req-other")

    with patch.object(worktree_manager, "detect_worktree_state", return_value=state), \
         patch.object(worktree_manager, "create_worktree") as mock_create:
        info = wb._setup_worktree_or_branch(
            req_id, fake_repo, "develop",
            worktree_policy="current", yaml_worktree_cfg={},
        )

    assert info.owner == "external"
    assert info.created is False
    assert info.path == fake_repo
    assert info.branch == "feat/req-other"
    mock_create.assert_not_called()


# ============================================================================
# Case 3：current + 普通 repo → BootstrapError(reason='policy_current_in_normal_repo')
# ============================================================================

def test_setup_worktree_or_branch_current_in_normal_repo_aborts(fake_repo: Path):
    """policy=current 但当前不在 linked worktree → fail-closed BootstrapError。"""
    req_id = "20260518-test-abort"
    with patch.object(worktree_manager, "detect_worktree_state",
                      return_value=_fake_state(is_linked=False, repo_root=fake_repo)), \
         patch.object(worktree_manager, "create_worktree") as mock_create:
        with pytest.raises(wb.BootstrapError) as exc:
            wb._setup_worktree_or_branch(
                req_id, fake_repo, "develop",
                worktree_policy="current", yaml_worktree_cfg={},
            )

    assert exc.value.reason == "policy_current_in_normal_repo"
    assert "policy=current" in str(exc.value)
    # 文案应包含详细设计 §2.2 提示
    assert "linked worktree" in str(exc.value)
    assert "cd 到" in str(exc.value)
    mock_create.assert_not_called()


# ============================================================================
# Case 4：never → fallback _checkout_feature_branch
# ============================================================================

def test_setup_worktree_or_branch_never_falls_back_to_checkout(fake_repo: Path):
    """policy=never + 非 linked → 走 _checkout_feature_branch 老路径，owner='none'。"""
    req_id = "20260518-test-never"
    with patch.object(worktree_manager, "detect_worktree_state",
                      return_value=_fake_state(is_linked=False, repo_root=fake_repo)), \
         patch.object(worktree_manager, "create_worktree") as mock_create, \
         patch.object(wb, "_checkout_feature_branch", return_value=f"feat/req-{req_id}") as mock_co:
        info = wb._setup_worktree_or_branch(
            req_id, fake_repo, "develop",
            worktree_policy="never", yaml_worktree_cfg={},
        )

    assert info.owner == "none"
    assert info.created is False
    assert info.path == fake_repo
    assert info.branch == f"feat/req-{req_id}"
    mock_co.assert_called_once_with(req_id, fake_repo, base_branch="develop")
    mock_create.assert_not_called()


# ============================================================================
# Case 5：_bootstrap_requirement 成功路径，artifacts 落 worktree path（R1）
# ============================================================================

def test_bootstrap_requirement_artifacts_land_in_worktree(fake_repo: Path):
    """artifacts 必须落 worktree path 下，主仓根 requirements/<key>/ 不被创建。"""
    req_id = "20260518-test-r1"
    worktree_path = fake_repo / ".worktrees" / f"feat-req-{req_id}"
    worktree_path.mkdir(parents=True, exist_ok=True)
    info = WorktreeInfo(
        path=worktree_path,
        branch=f"feat/req-{req_id}",
        base_branch="develop",
        owner="workflow",
        created=True,
    )
    baseline_ok = SetupResult(status="passed", rc=0, duration_ms=10, log_tail="")

    with patch.object(wb, "_setup_worktree_or_branch", return_value=info), \
         patch.object(worktree_manager, "run_worktree_setup", return_value=baseline_ok), \
         patch("workflow_bootstrap.REPO_ROOT", _REPO_ROOT):
        req_dir = wb._bootstrap_requirement(
            req_id, "R1 测试需求", "standard-8phase",
            _REPO_ROOT / ".claude/workflows/requirement/standard-8phase.yaml",
            "", fake_repo,
        )

    # 落点：worktree path 下
    assert req_dir == worktree_path / "requirements" / req_id
    assert (req_dir / "artifacts").is_dir(), "artifacts/ 应建在 worktree path 下"
    assert (req_dir / "meta.yaml").is_file()
    assert (req_dir / "plan.md").is_file()
    assert (req_dir / "process.txt").is_file()
    assert (req_dir / "run-state.jsonl").is_file()

    # 主仓根 requirements/<key>/ 不应被创建
    main_req_dir = fake_repo / "requirements" / req_id
    assert not main_req_dir.exists(), (
        f"主仓根 requirements/{req_id}/ 不应在 bootstrap 全程被创建（R1）"
    )

    # meta.yaml 含 worktree 段实际值（不是占位符）
    meta_text = (req_dir / "meta.yaml").read_text(encoding="utf-8")
    assert "enabled: true" in meta_text, "worktree.enabled 应为 true"
    assert "owner: workflow" in meta_text


# ============================================================================
# Case 6：baseline required=true + rc!=0 → 保留现场，不进 rollback
# ============================================================================

def test_bootstrap_requirement_baseline_required_failure_retains_worktree(fake_repo: Path):
    """required=true + baseline 失败 → BootstrapError(retain_worktree=True)，
    worktree + branch + requirements 全保留，meta.baseline.status=failed。
    """
    req_id = "20260518-test-bl"
    worktree_path = fake_repo / ".worktrees" / f"feat-req-{req_id}"
    worktree_path.mkdir(parents=True, exist_ok=True)
    info = WorktreeInfo(
        path=worktree_path,
        branch=f"feat/req-{req_id}",
        base_branch="develop",
        owner="workflow",
        created=True,
    )
    baseline_failed = SetupResult(
        status="failed", rc=1, duration_ms=42, log_tail="lint error: foo.py:5",
    )
    yaml_cfg = {"setup": {"baseline": {"required": True}}}

    with patch.object(wb, "_load_yaml_worktree_cfg", return_value=yaml_cfg), \
         patch.object(wb, "_setup_worktree_or_branch", return_value=info), \
         patch.object(worktree_manager, "run_worktree_setup", return_value=baseline_failed), \
         patch.object(wb, "_bootstrap_rollback") as mock_rollback, \
         patch("workflow_bootstrap.REPO_ROOT", _REPO_ROOT):
        with pytest.raises(wb.BootstrapError) as exc:
            wb._bootstrap_requirement(
                req_id, "BL 测试需求", "standard-8phase",
                _REPO_ROOT / ".claude/workflows/requirement/standard-8phase.yaml",
                "", fake_repo,
            )

    # rollback 不应被 _bootstrap_requirement 内部调用（caller 侧根据 retain_worktree 决定）
    mock_rollback.assert_not_called()
    assert exc.value.reason == "baseline_failed_required"
    assert exc.value.retain_worktree is True
    assert exc.value.artifacts_created is True
    assert exc.value.branch_created is True

    # worktree path 下保留 meta.yaml + baseline.status=failed
    req_dir = worktree_path / "requirements" / req_id
    assert req_dir.exists(), "worktree path 下需求目录应保留（retain_worktree=True）"
    meta_text = (req_dir / "meta.yaml").read_text(encoding="utf-8")
    assert "status: failed" in meta_text, "baseline.status 应为 failed"


# ============================================================================
# Case 7：baseline required=false + rc!=0 → warning + 继续完成
# ============================================================================

def test_bootstrap_requirement_baseline_required_false_warns_continues(
    fake_repo: Path, caplog,
):
    """required=false + baseline 失败 → 继续走完 bootstrap，meta.baseline.status=failed。"""
    req_id = "20260518-test-warn"
    worktree_path = fake_repo / ".worktrees" / f"feat-req-{req_id}"
    worktree_path.mkdir(parents=True, exist_ok=True)
    info = WorktreeInfo(
        path=worktree_path,
        branch=f"feat/req-{req_id}",
        base_branch="develop",
        owner="workflow",
        created=True,
    )
    baseline_failed = SetupResult(
        status="failed", rc=2, duration_ms=15, log_tail="non-fatal lint warn",
    )
    yaml_cfg = {"setup": {"baseline": {"required": False}}}

    caplog.set_level(logging_mod.WARNING)
    with patch.object(wb, "_load_yaml_worktree_cfg", return_value=yaml_cfg), \
         patch.object(wb, "_setup_worktree_or_branch", return_value=info), \
         patch.object(worktree_manager, "run_worktree_setup", return_value=baseline_failed), \
         patch("workflow_bootstrap.REPO_ROOT", _REPO_ROOT):
        req_dir = wb._bootstrap_requirement(
            req_id, "Warn 测试需求", "standard-8phase",
            _REPO_ROOT / ".claude/workflows/requirement/standard-8phase.yaml",
            "", fake_repo,
        )

    # 已完成 bootstrap（req_dir 返回）
    assert req_dir == worktree_path / "requirements" / req_id
    assert (req_dir / "meta.yaml").is_file()
    # meta.baseline.status=failed
    meta_text = (req_dir / "meta.yaml").read_text(encoding="utf-8")
    assert "status: failed" in meta_text
    # warning 日志
    warn_msgs = [r.message for r in caplog.records if r.levelno == logging_mod.WARNING]
    assert any("baseline failed but required=false" in m for m in warn_msgs), (
        f"应有 baseline warning 日志，实际：{warn_msgs}"
    )


# ============================================================================
# Case 8：_bootstrap_rollback worktree remove 严格先于 branch -D
# ============================================================================

def test_bootstrap_rollback_worktree_remove_before_branch_delete(fake_repo: Path):
    """rollback 调用顺序：worktree remove + prune → checkout previous → branch -D。"""
    req_id = "20260518-test-order"
    worktree_path = fake_repo / ".worktrees" / f"feat-req-{req_id}"
    worktree_path.mkdir(parents=True, exist_ok=True)
    info = WorktreeInfo(
        path=worktree_path,
        branch=f"feat/req-{req_id}",
        base_branch="develop",
        owner="workflow",
        created=True,
    )

    call_order: list[str] = []

    def _fake_run(cmd, *args, **kwargs):
        # 提取关键 cmd token 排序记录
        if "worktree" in cmd and "remove" in cmd:
            call_order.append("worktree_remove")
        elif "worktree" in cmd and "prune" in cmd:
            call_order.append("worktree_prune")
        elif "checkout" in cmd:
            call_order.append("checkout")
        elif "branch" in cmd and "-D" in cmd:
            call_order.append("branch_delete")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("workflow_bootstrap.subprocess.run", side_effect=_fake_run):
        wb._bootstrap_rollback(
            req_id, fake_repo, "develop",
            artifacts_created=False, branch_created=True,
            worktree_info=info,
        )

    # 至少包含 worktree_remove → branch_delete 的相对顺序
    idx_remove = call_order.index("worktree_remove")
    idx_branch = call_order.index("branch_delete")
    assert idx_remove < idx_branch, (
        f"worktree remove 必须严格先于 branch -D，实际顺序：{call_order}"
    )


# ============================================================================
# Case 9：_bootstrap_rollback 双扫主仓根 + worktree path
# ============================================================================

def test_bootstrap_rollback_double_sweep_artifacts(fake_repo: Path):
    """artifacts_created=True 时，主仓根 + worktree path 下 requirements/<key>/ 都被 rmtree。"""
    req_id = "20260518-test-sweep"
    worktree_path = fake_repo / ".worktrees" / f"feat-req-{req_id}"
    worktree_path.mkdir(parents=True, exist_ok=True)
    info = WorktreeInfo(
        path=worktree_path,
        branch=f"feat/req-{req_id}",
        base_branch="develop",
        owner="workflow",
        created=True,
    )

    # 在两个候选位置都放一份产物（模拟历史残留 / 中间态）
    main_dir = fake_repo / "requirements" / req_id
    wt_dir = worktree_path / "requirements" / req_id
    main_dir.mkdir(parents=True, exist_ok=True)
    (main_dir / "stale.txt").write_text("stale\n", encoding="utf-8")
    wt_dir.mkdir(parents=True, exist_ok=True)
    (wt_dir / "live.txt").write_text("live\n", encoding="utf-8")

    # mock git 子进程避免真跑（worktree remove 会因不是真 git repo 失败）
    with patch("workflow_bootstrap.subprocess.run",
               return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")):
        wb._bootstrap_rollback(
            req_id, fake_repo, "develop",
            artifacts_created=True, branch_created=False,
            worktree_info=info,
        )

    assert not main_dir.exists(), "主仓根 requirements/<key>/ 应被 rmtree"
    assert not wt_dir.exists(), "worktree path 下 requirements/<key>/ 应被 rmtree"


# ============================================================================
# Case 10：_bootstrap_rollback 部分状态（仅 worktree / 仅 branch）幂等
# ============================================================================

def test_bootstrap_rollback_idempotent_on_partial_state(fake_repo: Path):
    """部分状态下 rollback 不抛：worktree_info=None / artifacts 不存在 / 分支已删都安全。"""
    req_id = "20260518-test-partial"

    # 仅 branch_created，无 worktree_info（policy=never 兜底场景）
    with patch("workflow_bootstrap.subprocess.run",
               return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")):
        # 第一次调：正常清理
        wb._bootstrap_rollback(
            req_id, fake_repo, "develop",
            artifacts_created=True, branch_created=True,
            worktree_info=None,
        )
        # 第二次调：目录已不存在，应静默不抛（幂等）
        wb._bootstrap_rollback(
            req_id, fake_repo, "develop",
            artifacts_created=True, branch_created=True,
            worktree_info=None,
        )

    # 仅 worktree_info、未建 artifacts（worktree 已建但 mkdir artifacts 失败前）
    worktree_path = fake_repo / ".worktrees" / f"feat-req-{req_id}-only-wt"
    worktree_path.mkdir(parents=True, exist_ok=True)
    info_only_wt = WorktreeInfo(
        path=worktree_path,
        branch=f"feat/req-{req_id}",
        base_branch="develop",
        owner="workflow",
        created=True,
    )
    with patch("workflow_bootstrap.subprocess.run",
               return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")):
        wb._bootstrap_rollback(
            req_id, fake_repo, "develop",
            artifacts_created=False, branch_created=False,
            worktree_info=info_only_wt,
        )
    # 不抛即视作通过
