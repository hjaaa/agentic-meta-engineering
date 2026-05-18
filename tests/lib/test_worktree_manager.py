"""worktree_manager.py 单测（F-002）。

覆盖（≥17 用例；含 P1-2 / P1-3 修复落点）：
  - detect_worktree_state：normal / linked / submodule / detached 四类
  - ensure_worktree_dir_ignored：present / missing → BootstrapError
  - create_worktree：happy / rc!=0 wrap / path or branch already exists（reason='path_or_branch_exists'）
  - run_worktree_setup：owner=external 短路 / owner=workflow required=true rc!=0 failed
                         / owner=workflow required=false rc!=0 failed
  - resolve_main_repo_root：main worktree 自指 / linked worktree 返回主仓根
                            / porcelain 输出畸形 → BootstrapError(reason='porcelain_malformed')
  - cleanup_worktree_if_owned：workflow removed / external skipped / self-remove guard
                                / path 不在白名单 aborted / 缺 worktree 字段 legacy_no_worktree_field

外部 subprocess 失败 / 畸形输出走 mock；正常 git 拓扑用 tmp_path 真 git init。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# 注入 scripts/lib 到 sys.path（与其他 tests/lib/ 下的测试一致）
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from worktree_manager import (  # noqa: E402
    WorktreeBootstrapError,
    cleanup_worktree_if_owned,
    create_worktree,
    detect_worktree_state,
    ensure_worktree_dir_ignored,
    resolve_main_repo_root,
    run_worktree_setup,
    select_worktree_location,
)
from workflow_bootstrap import BootstrapError  # noqa: E402


# ============================================================================
# fixtures
# ============================================================================

def _git(args, cwd, **kwargs):
    """tmp git 操作小工具：失败时 check=True 抛错，方便测试编排定位。"""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """tmp_path 下初始化空 git repo + 首次 commit；返回 repo root。"""
    _git(["init", "--initial-branch=main"], cwd=tmp_path)
    _git(["config", "user.email", "test@example.com"], cwd=tmp_path)
    _git(["config", "user.name", "Test User"], cwd=tmp_path)
    # 首 commit：无父 commit 时分支处于 unborn，detect 易混淆
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=tmp_path)
    _git(["commit", "-m", "seed"], cwd=tmp_path)
    return tmp_path


@pytest.fixture
def tmp_git_repo_with_worktree(tmp_git_repo: Path) -> tuple[Path, Path]:
    """在 tmp_git_repo 下挂一个 linked worktree（feat/req-test 分支）；
    返回 (main_root, worktree_path)。

    worktree 路径放在 tmp_git_repo 内的 .worktrees/ 下（pytest tmp_path 唯一即可），
    避开 tmp_path.parent 跨测共享导致的命名冲突。
    """
    worktree_path = tmp_git_repo / ".worktrees" / "feat-req-test"
    _git(
        ["worktree", "add", str(worktree_path), "-b", "feat/req-test"],
        cwd=tmp_git_repo,
    )
    return tmp_git_repo, worktree_path


# ============================================================================
# detect_worktree_state（4 例）
# ============================================================================

def test_detect_worktree_state_normal_repo(tmp_git_repo: Path) -> None:
    state = detect_worktree_state(tmp_git_repo)
    assert state.is_git_repo is True
    assert state.is_linked_worktree is False
    assert state.is_submodule is False
    assert state.is_detached is False
    assert state.branch == "main"
    # normal repo：git_dir == git_common_dir
    assert state.git_dir == state.git_common_dir


def test_detect_worktree_state_linked_worktree(
    tmp_git_repo_with_worktree: tuple[Path, Path],
) -> None:
    _, worktree_path = tmp_git_repo_with_worktree
    state = detect_worktree_state(worktree_path)
    assert state.is_git_repo is True
    assert state.is_linked_worktree is True
    assert state.is_submodule is False
    assert state.is_detached is False
    assert state.branch == "feat/req-test"
    # linked worktree：git_dir != git_common_dir
    assert state.git_dir != state.git_common_dir
    # git_dir 不应含 /modules/（这是 submodule 标记）
    assert "/modules/" not in str(state.git_dir)


def test_detect_worktree_state_submodule(tmp_git_repo: Path) -> None:
    """模拟 submodule：构造 git_dir 含 '/modules/' 的拓扑。

    真实 submodule 集成成本高（需要另一个上游 repo），这里走 mock：
    覆盖 _run_git 让 --git-dir 返回 .git/modules/<name> 形态。
    """
    fake_git_dir = tmp_git_repo / ".git" / "modules" / "subm"
    fake_git_dir.mkdir(parents=True, exist_ok=True)

    def fake_run_git(args, *, cwd, timeout=30):
        if args == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(
                args, 0, stdout=str(fake_git_dir) + "\n", stderr="",
            )
        if args == ["rev-parse", "--git-common-dir"]:
            # submodule 的 common-dir 通常指向 superproject .git
            return subprocess.CompletedProcess(
                args, 0, stdout=str(tmp_git_repo / ".git") + "\n", stderr="",
            )
        if args == ["symbolic-ref", "--short", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
        if args == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(
                args, 0, stdout=str(tmp_git_repo) + "\n", stderr="",
            )
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="not stubbed")

    with patch("worktree_manager._run_git", side_effect=fake_run_git):
        state = detect_worktree_state(tmp_git_repo)

    assert state.is_submodule is True
    # submodule 时不应同时标 linked_worktree（互斥）
    assert state.is_linked_worktree is False


def test_detect_worktree_state_detached_head(tmp_git_repo: Path) -> None:
    # 切到 HEAD~0 让分支 detached
    head_sha = _git(["rev-parse", "HEAD"], cwd=tmp_git_repo).stdout.strip()
    _git(["checkout", "--detach", head_sha], cwd=tmp_git_repo)
    state = detect_worktree_state(tmp_git_repo)
    assert state.is_detached is True
    assert state.branch == ""


# ============================================================================
# select_worktree_location（1 例）
# ============================================================================

def test_select_worktree_location_replaces_slash(tmp_path: Path) -> None:
    loc = select_worktree_location(tmp_path, "feat/req-20260518-foo")
    assert loc == tmp_path / ".worktrees" / "feat-req-20260518-foo"


# ============================================================================
# ensure_worktree_dir_ignored（2 例）
# ============================================================================

def test_ensure_worktree_dir_ignored_present(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".worktrees/\n*.pyc\n", encoding="utf-8")
    loc = tmp_path / ".worktrees" / "feat-req-test"
    # 不抛即视为通过
    ensure_worktree_dir_ignored(tmp_path, loc)


def test_ensure_worktree_dir_ignored_missing_raises(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    loc = tmp_path / ".worktrees" / "feat-req-test"
    with pytest.raises(WorktreeBootstrapError) as ei:
        ensure_worktree_dir_ignored(tmp_path, loc)
    assert ei.value.reason == "gitignore_missing"
    # 父类兜底也应命中
    assert isinstance(ei.value, BootstrapError)


def test_ensure_worktree_dir_ignored_no_gitignore_file_raises(tmp_path: Path) -> None:
    loc = tmp_path / ".worktrees" / "feat-req-test"
    with pytest.raises(WorktreeBootstrapError) as ei:
        ensure_worktree_dir_ignored(tmp_path, loc)
    assert ei.value.reason == "gitignore_missing"


# ============================================================================
# create_worktree（3 例）
# ============================================================================

def test_create_worktree_happy(tmp_git_repo: Path) -> None:
    location = tmp_git_repo / ".worktrees" / "feat-req-happy"
    info = create_worktree(tmp_git_repo, "feat/req-happy", "main", location)
    assert info.path == location
    assert info.branch == "feat/req-happy"
    assert info.base_branch == "main"
    assert info.owner == "workflow"
    assert info.created is True
    assert location.is_dir()


def test_create_worktree_failure_wraps_bootstrap_error(tmp_git_repo: Path) -> None:
    # 用一个不存在的 base_branch 触发 git rc!=0
    location = tmp_git_repo / ".worktrees" / "feat-req-fail"
    with pytest.raises(WorktreeBootstrapError) as ei:
        create_worktree(
            tmp_git_repo, "feat/req-x", "does-not-exist-branch", location,
        )
    # base 不存在时 git 的 stderr 通常不含 'already exists'，故 reason='other'
    assert ei.value.reason in {"other", "path_or_branch_exists"}
    assert isinstance(ei.value, BootstrapError)


def test_create_worktree_path_already_exists_signals_retry(
    tmp_git_repo_with_worktree: tuple[Path, Path],
) -> None:
    """P1-2：path 或 branch 已存在 → reason='path_or_branch_exists'。"""
    main_root, existing_path = tmp_git_repo_with_worktree
    # 重复用同一 path + branch 触发已存在
    with pytest.raises(WorktreeBootstrapError) as ei:
        create_worktree(
            main_root, "feat/req-test", "main", existing_path,
        )
    assert ei.value.reason == "path_or_branch_exists"


def test_create_worktree_other_exists_text_not_misclassified(
    tmp_git_repo: Path,
) -> None:
    """F-1 rev2：stderr 含 'already exists' 但非 git 'fatal:' 前缀
    （如 pre-commit hook 噪音）→ reason='other'，避免 retry 死循环。"""
    location = tmp_git_repo / ".worktrees" / "feat-req-noisy"
    fake_proc = subprocess.CompletedProcess(
        args=["git", "worktree", "add", str(location), "-b", "feat/req-x", "main"],
        returncode=1,
        stdout="",
        stderr="pre-commit hook: lockfile already exists; aborting\n",
    )
    with patch("worktree_manager._run_git", return_value=fake_proc):
        with pytest.raises(WorktreeBootstrapError) as ei:
            create_worktree(
                tmp_git_repo, "feat/req-x", "main", location,
            )
    assert ei.value.reason == "other"


# ============================================================================
# detect_worktree_state · F-4 fail-fast（1 例）
# ============================================================================


def test_detect_worktree_state_common_dir_failure_raises(
    tmp_git_repo: Path,
) -> None:
    """F-4 rev2：`git rev-parse --git-common-dir` rc!=0 不允许静默 fallback，
    抛 WorktreeBootstrapError(reason='other') 避免 worktree 拓扑误判。"""

    def fake_run_git(args, *, cwd, timeout=30):
        if args == ["rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(
                args, 0, stdout=str(tmp_git_repo / ".git") + "\n", stderr="",
            )
        if args == ["rev-parse", "--git-common-dir"]:
            return subprocess.CompletedProcess(
                args, 1, stdout="",
                stderr="fatal: corrupt repository / git version mismatch\n",
            )
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="not stubbed")

    with patch("worktree_manager._run_git", side_effect=fake_run_git):
        with pytest.raises(WorktreeBootstrapError) as ei:
            detect_worktree_state(tmp_git_repo)
    assert ei.value.reason == "other"
    assert "git-common-dir" in str(ei.value)


# ============================================================================
# run_worktree_setup（3 例）
# ============================================================================

def test_run_worktree_setup_owner_external_short_circuits(tmp_path: Path) -> None:
    """OD-4：owner='external' 不读 policy.required 直接返回 skipped。"""
    # 故意把 policy 设成会抛 KeyError 的样子，验证函数确实没访问
    class _ExplodingDict(dict):
        def __getitem__(self, key):  # type: ignore[override]
            raise AssertionError(f"OD-4 违反：external 路径访问了 policy[{key!r}]")

        def get(self, key, default=None):  # type: ignore[override]
            raise AssertionError(f"OD-4 违反：external 路径访问了 policy.get({key!r})")

    result = run_worktree_setup(tmp_path, _ExplodingDict(), owner="external")
    assert result.status == "skipped"
    assert result.rc == 0
    assert result.duration_ms == 0
    assert result.log_tail == ""


def test_run_worktree_setup_owner_workflow_required_true_failure(
    tmp_path: Path,
) -> None:
    """OD-2：owner='workflow' + rc!=0 → status='failed'（required=true）。"""
    fake_proc = subprocess.CompletedProcess(
        args=["make", "gates-validate"],
        returncode=2,
        stdout="",
        stderr="ERR: lint failed at scripts/lib/foo.py:10\n",
    )
    with patch("subprocess.run", return_value=fake_proc) as m:
        result = run_worktree_setup(tmp_path, {"required": True}, owner="workflow")
    assert result.status == "failed"
    assert result.rc == 2
    assert "lint failed" in result.log_tail
    # 验证 subprocess 被调用且 cwd 指向 worktree_path
    _, kwargs = m.call_args
    assert kwargs["cwd"] == str(tmp_path)


def test_run_worktree_setup_owner_workflow_required_false_warning(
    tmp_path: Path,
) -> None:
    """OD-2：required=false 时同样返回 failed（调用方决定 warning vs hard fail）。"""
    fake_proc = subprocess.CompletedProcess(
        args=["make", "gates-validate"],
        returncode=1,
        stdout="",
        stderr="warning: deprecated rule\n",
    )
    with patch("subprocess.run", return_value=fake_proc):
        result = run_worktree_setup(tmp_path, {"required": False}, owner="workflow")
    assert result.status == "failed"
    assert result.rc == 1


def test_run_worktree_setup_owner_workflow_rc0_passed(tmp_path: Path) -> None:
    fake_proc = subprocess.CompletedProcess(
        args=["make", "gates-validate"], returncode=0, stdout="", stderr="",
    )
    with patch("subprocess.run", return_value=fake_proc):
        result = run_worktree_setup(tmp_path, {"required": True}, owner="workflow")
    assert result.status == "passed"
    assert result.rc == 0


# ============================================================================
# resolve_main_repo_root（3 例 / P1-3）
# ============================================================================

def test_resolve_main_repo_root_from_main_worktree_returns_self(
    tmp_git_repo: Path,
) -> None:
    main_root = resolve_main_repo_root(tmp_git_repo)
    assert main_root.resolve() == tmp_git_repo.resolve()


def test_resolve_main_repo_root_from_linked_worktree_returns_main(
    tmp_git_repo_with_worktree: tuple[Path, Path],
) -> None:
    main_root, worktree_path = tmp_git_repo_with_worktree
    resolved = resolve_main_repo_root(worktree_path)
    assert resolved.resolve() == main_root.resolve()


def test_resolve_main_repo_root_porcelain_malformed_raises(tmp_path: Path) -> None:
    fake_proc = subprocess.CompletedProcess(
        args=["git", "worktree", "list", "--porcelain"],
        returncode=0,
        stdout="# garbled output without worktree line\nfoo bar\n",
        stderr="",
    )
    with patch("worktree_manager._run_git", return_value=fake_proc):
        with pytest.raises(WorktreeBootstrapError) as ei:
            resolve_main_repo_root(tmp_path)
    assert ei.value.reason == "porcelain_malformed"


def test_resolve_main_repo_root_main_root_missing(tmp_path: Path) -> None:
    fake_proc = subprocess.CompletedProcess(
        args=["git", "worktree", "list", "--porcelain"],
        returncode=0,
        stdout="worktree /nonexistent/path/that/should/not/exist\nHEAD abc123\n",
        stderr="",
    )
    with patch("worktree_manager._run_git", return_value=fake_proc):
        with pytest.raises(WorktreeBootstrapError) as ei:
            resolve_main_repo_root(tmp_path)
    assert ei.value.reason == "main_root_missing"


# ============================================================================
# cleanup_worktree_if_owned（5 例 / D-008 / D-009 / P1-3）
# ============================================================================

def test_cleanup_worktree_if_owned_workflow_removes(
    tmp_git_repo_with_worktree: tuple[Path, Path],
) -> None:
    main_root, worktree_path = tmp_git_repo_with_worktree
    # path / location 用绝对路径 prefix 比对，保护 2 命中
    meta = {
        "worktree": {
            "owner": "workflow",
            "path": str(worktree_path),
            "location": str(main_root / ".worktrees") + "/",
        },
    }
    result = cleanup_worktree_if_owned(meta, main_root)
    assert result.action == "removed"
    assert result.reason == "workflow_ok"
    assert result.removed_path is not None
    assert not worktree_path.exists()


def test_cleanup_worktree_if_owned_external_skips(tmp_git_repo: Path) -> None:
    meta = {
        "worktree": {
            "owner": "external",
            "path": "/some/external/wt",
            "location": "/some/external/",
        },
    }
    result = cleanup_worktree_if_owned(meta, tmp_git_repo)
    assert result.action == "skipped"
    assert result.reason == "external"
    assert result.removed_path is None


def test_cleanup_worktree_if_owned_main_root_equals_worktree_aborts(
    tmp_git_repo: Path,
) -> None:
    """P1-3 self-remove guard：main_root == worktree path → aborted。"""
    meta = {
        "worktree": {
            "owner": "workflow",
            "path": str(tmp_git_repo),
            # location 设成 path 自身 prefix 让保护 2 过；专测保护 3
            "location": str(tmp_git_repo),
        },
    }
    result = cleanup_worktree_if_owned(meta, tmp_git_repo)
    assert result.action == "aborted"
    assert result.reason == "main_root_equals_worktree"


def test_cleanup_worktree_if_owned_path_not_whitelisted_aborts(
    tmp_git_repo: Path,
) -> None:
    meta = {
        "worktree": {
            "owner": "workflow",
            "path": "/tmp/random/wt",       # 不在 location 之下
            "location": ".worktrees/",
        },
    }
    result = cleanup_worktree_if_owned(meta, tmp_git_repo)
    assert result.action == "aborted"
    assert result.reason == "path_not_in_whitelist"


def test_cleanup_worktree_if_owned_legacy_no_worktree_field(
    tmp_git_repo: Path,
) -> None:
    """meta 完全没 worktree 字段（旧需求迁移前）→ skipped。"""
    meta = {"phase": "implementation"}  # 无 worktree 字段
    result = cleanup_worktree_if_owned(meta, tmp_git_repo)
    assert result.action == "skipped"
    assert result.reason == "legacy_no_worktree_field"


def test_cleanup_worktree_if_owned_git_remove_failure(
    tmp_git_repo: Path,
) -> None:
    """git worktree remove rc!=0 → action='failed', reason='git_failure'（不抛）。"""
    meta = {
        "worktree": {
            "owner": "workflow",
            "path": str(tmp_git_repo / ".worktrees" / "feat-req-x"),
            "location": str(tmp_git_repo / ".worktrees") + "/",
        },
    }
    fake_remove = subprocess.CompletedProcess(
        args=["git", "worktree", "remove", "..."],
        returncode=1,
        stdout="",
        stderr="fatal: not a worktree\n",
    )
    with patch("worktree_manager._run_git", return_value=fake_remove):
        result = cleanup_worktree_if_owned(meta, tmp_git_repo)
    assert result.action == "failed"
    assert result.reason == "git_failure"
    assert result.removed_path is None


def test_cleanup_worktree_if_owned_path_traversal_aborts(
    tmp_git_repo: Path,
) -> None:
    """F-3 rev2：'.worktrees/../etc/passwd' 反向遍历 startswith 成立但实际
    逃出容器；规范化对比 + is_relative_to 应识别为 aborted/path_not_in_whitelist。"""
    meta = {
        "worktree": {
            "owner": "workflow",
            "path": ".worktrees/../etc/passwd",
            "location": ".worktrees/",
        },
    }
    result = cleanup_worktree_if_owned(meta, tmp_git_repo)
    assert result.action == "aborted"
    assert result.reason == "path_not_in_whitelist"


def test_cleanup_worktree_if_owned_git_binary_missing(
    tmp_git_repo: Path,
) -> None:
    """F-2 rev2：_run_git 抛 WorktreeBootstrapError（git 二进制丢失）→
    CleanupResult(action='failed', reason='git_failure')，不向上抛，
    archive 主流程不受影响。"""
    meta = {
        "worktree": {
            "owner": "workflow",
            "path": str(tmp_git_repo / ".worktrees" / "feat-req-x"),
            "location": str(tmp_git_repo / ".worktrees") + "/",
        },
    }

    def fake_run_git(args, *, cwd, timeout=30):
        raise WorktreeBootstrapError(
            "git binary not found: simulated", reason="other",
        )

    with patch("worktree_manager._run_git", side_effect=fake_run_git):
        result = cleanup_worktree_if_owned(meta, tmp_git_repo)

    assert result.action == "failed"
    assert result.reason == "git_failure"
    assert result.removed_path is None


# ============================================================================
# Sanity：异常继承关系
# ============================================================================

def test_worktree_bootstrap_error_is_bootstrap_error() -> None:
    """子类化兼容：调用方 `except BootstrapError` 仍能兜底。"""
    err = WorktreeBootstrapError("boom", reason="path_or_branch_exists",
                                 branch_created=True, retain_worktree=True)
    assert isinstance(err, BootstrapError)
    assert err.reason == "path_or_branch_exists"
    assert err.branch_created is True
    assert err.retain_worktree is True
    assert err.artifacts_created is False  # 默认值保留
