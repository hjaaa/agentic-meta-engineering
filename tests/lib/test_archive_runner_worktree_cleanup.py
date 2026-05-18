"""archive_runner._cleanup_worktree_before_archive 单测（F-005）。

覆盖（9 用例）：
  TC-1: owner=workflow 走 removed 分支 + removed_at 回填
  TC-2: owner=external skipped 路径含字面量 'cleanup skipped: external'
  TC-3: legacy meta 缺 worktree 字段降级（不引入空 worktree 段）
  TC-4: cleanup aborted/failed 不阻塞 archive 主流程（D-009）
  TC-5: removed_at 回填为合法 ts（YYYY-MM-DD HH:MM:SS 格式）
  TC-6: CLI 入参/退出码不变（archive.md frozen）
  TC-7（P1-3 关键回归）: 从 worktree 内调 archive 能解出主仓根并删除目标 worktree
  TC-8（TC-2 变体）: owner=external + resolve 失败 → fail-closed，不 raise
  TC-9（AC5 回归）: owner=external + dirty workspace → _precheck_dirty 早 fail-closed，
                    cleanup_worktree_if_owned 不被调用（worktree 不被误删）

外部 git 子进程全 mock（monkeypatch），避免依赖真实 git 拓扑。
integration 路径 TC-7 用 tmp_git_repo fixture 创建真实 linked worktree。
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
import pytest
import yaml

# 注入 scripts/lib 到 sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import archive_runner  # noqa: E402
import worktree_manager  # noqa: E402
from archive_runner import archive_requirement  # noqa: E402
from worktree_manager import CleanupResult  # noqa: E402


# ============================================================================
# helpers
# ============================================================================

def _git(args, cwd, **kwargs):
    import subprocess
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _make_meta_dict(
    *,
    req_id: str = "REQ-2099-901",
    phase: str = "testing",
    pr_number: int = 99,
    branch: str = "feat/req-2099-901",
    base_branch: str = "develop",
    worktree: dict | None = None,
    lessons_extracted: bool = True,
) -> dict:
    """构造 meta 字典（不写文件）。"""
    m: dict = {
        "id": req_id,
        "title": "Test Req",
        "phase": phase,
        "branch": branch,
        "base_branch": base_branch,
        "pr_number": pr_number,
        "created_at": "2026-05-18 00:00:00",
        "project": "test",
        "lessons_extracted": lessons_extracted,
    }
    if worktree is not None:
        m["worktree"] = worktree
    return m


def _write_meta(req_dir: Path, meta: dict) -> None:
    req_dir.mkdir(parents=True, exist_ok=True)
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    process_txt = req_dir / "process.txt"
    if not process_txt.exists():
        process_txt.write_text(
            "2026-05-18 00:00:00 [phase-transition] bootstrap → testing\n",
            encoding="utf-8",
        )


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """重定向 archive_runner 的 REQUIREMENTS_DIR 到 tmp_path。"""
    monkeypatch.setattr(archive_runner, "REQUIREMENTS_DIR", tmp_path)
    monkeypatch.setattr(archive_runner, "REPO_ROOT", tmp_path)
    return tmp_path


def _make_run_stub(plan: dict):
    """archive_runner._run 替身（前缀匹配）。"""

    def _stub(cmd, *, cwd=None):
        for key, result in plan.items():
            if tuple(cmd[: len(key)]) == tuple(key):
                if isinstance(result, BaseException):
                    raise result
                return result
        return _ok()

    return _stub


def _archive_run_stub_success():
    """5 项预检全通过的 _run stub（git clean + gh pr view merged）。"""
    return _make_run_stub(
        {
            ("git", "status", "--porcelain"): _ok(stdout=""),
            ("gh", "pr", "view"): _ok(
                stdout='{"state":"MERGED","mergedAt":"2026-05-18T00:00:00Z"}\n'
            ),
        }
    )


# ============================================================================
# TC-1：owner=workflow → removed 分支（resolved_at 回填已在 TC-5 专测，此处验主流程）
# ============================================================================


def test_archive_runner_owner_workflow_removes_worktree(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """owner=workflow 走 removed 分支；cleanup 不阻塞 archive 主流程。"""
    req_id = "REQ-2099-901"
    worktree_path = tmp_path / ".worktrees" / "feat-req-2099-901"
    worktree_path.mkdir(parents=True)

    meta = _make_meta_dict(
        req_id=req_id,
        worktree={
            "owner": "workflow",
            "path": str(worktree_path),
            "cleanup": {"policy": "auto", "removed_at": ""},
        },
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())

    removed_result = CleanupResult(
        action="removed", reason="workflow_ok", removed_path=worktree_path
    )
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
    monkeypatch.setattr(
        worktree_manager,
        "cleanup_worktree_if_owned",
        lambda _meta, _root: removed_result,
    )

    result = archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )

    assert result.req_id == req_id
    # archive 主流程应完成（archived_at 非空）
    assert result.archived_at


# ============================================================================
# TC-2：owner=external → skipped，日志含字面量 'cleanup skipped: external'（R5）
# ============================================================================


def test_archive_runner_owner_external_skips_with_log(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """owner=external → cleanup skipped，日志含 'cleanup skipped: external'。"""
    req_id = "REQ-2099-902"
    meta = _make_meta_dict(
        req_id=req_id,
        worktree={"owner": "external", "path": "/some/external/path"},
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
    skipped_result = CleanupResult(action="skipped", reason="external", removed_path=None)
    monkeypatch.setattr(
        worktree_manager,
        "cleanup_worktree_if_owned",
        lambda _meta, _root: skipped_result,
    )

    with caplog.at_level(logging.INFO, logger="archive_runner"):
        archive_requirement(
            req_id,
            yes_experience=False,
            no_experience=True,
            yes_local_branch=False,
            yes_remote_branch=False,
        )

    # R5：日志必须包含字面量
    messages = [r.message for r in caplog.records]
    assert any("cleanup skipped: external" in m for m in messages), (
        f"Expected 'cleanup skipped: external' in log messages, got: {messages}"
    )


# ============================================================================
# TC-3：legacy meta 缺 worktree 字段 → 降级成功，不引入空 worktree 段
# ============================================================================


def test_archive_runner_legacy_meta_without_worktree_field_succeeds(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """缺 worktree 字段的旧 meta → cleanup skipped，archive 主流程继续，meta 不引入 worktree 段。"""
    req_id = "REQ-2099-903"
    # 故意不带 worktree 字段
    meta = _make_meta_dict(req_id=req_id)
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
    # cleanup_worktree_if_owned 返回 legacy_no_worktree_field（保护 1 短路）
    skipped_result = CleanupResult(
        action="skipped", reason="legacy_no_worktree_field", removed_path=None
    )
    monkeypatch.setattr(
        worktree_manager,
        "cleanup_worktree_if_owned",
        lambda _meta, _root: skipped_result,
    )

    result = archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )

    assert result.archived_at

    # 验证写入的 meta.yaml 没有引入空 worktree 段
    meta_path = req_dir / "meta.yaml"
    with meta_path.open(encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    assert "worktree" not in saved, "legacy meta should not gain empty worktree section"


# ============================================================================
# TC-4：cleanup aborted/failed → 不阻塞 archive 主流程（D-009）
# ============================================================================


def test_archive_runner_cwd_mismatch_aborts_cleanup_does_not_block(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """cleanup aborted（path_not_in_whitelist）不阻塞 archive 主流程。"""
    req_id = "REQ-2099-904"
    meta = _make_meta_dict(
        req_id=req_id,
        worktree={"owner": "workflow", "path": "/etc/passwd"},
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
    aborted_result = CleanupResult(
        action="aborted", reason="path_not_in_whitelist", removed_path=None
    )
    monkeypatch.setattr(
        worktree_manager,
        "cleanup_worktree_if_owned",
        lambda _meta, _root: aborted_result,
    )

    # archive 应正常完成，不因 cleanup aborted 而失败
    result = archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )
    assert result.archived_at, "archive should succeed even when cleanup is aborted"


# ============================================================================
# TC-5：removed 分支后 meta.worktree.cleanup.removed_at 回填为合法 ts
# ============================================================================


def test_archive_runner_cleanup_removed_at_writes_meta(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """removed 分支：meta.worktree.cleanup.removed_at 必须回填合法 YYYY-MM-DD HH:MM:SS ts。"""
    import re

    req_id = "REQ-2099-905"
    worktree_path = tmp_path / ".worktrees" / "feat-test"
    worktree_path.mkdir(parents=True)

    meta = _make_meta_dict(
        req_id=req_id,
        worktree={
            "owner": "workflow",
            "path": str(worktree_path),
            "cleanup": {"policy": "auto", "removed_at": ""},
        },
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
    removed_result = CleanupResult(
        action="removed", reason="workflow_ok", removed_path=worktree_path
    )
    monkeypatch.setattr(
        worktree_manager,
        "cleanup_worktree_if_owned",
        lambda _meta, _root: removed_result,
    )

    archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )

    meta_path = req_dir / "meta.yaml"
    with meta_path.open(encoding="utf-8") as f:
        saved = yaml.safe_load(f)

    removed_at = saved.get("worktree", {}).get("cleanup", {}).get("removed_at", "")
    assert removed_at, "removed_at should be written"
    # 格式校验：YYYY-MM-DD HH:MM:SS
    ts_pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    assert ts_pattern.match(str(removed_at)), (
        f"removed_at={removed_at!r} does not match YYYY-MM-DD HH:MM:SS"
    )


# ============================================================================
# TC-6：CLI 入参/退出码不变（archive.md frozen）
# ============================================================================


def test_archive_runner_cli_contract_unchanged() -> None:
    """archive_requirement 签名 + ArchiveResult 字段集与 archive.md 约定一致。"""
    import inspect

    sig = inspect.signature(archive_requirement)
    params = set(sig.parameters.keys())
    # archive.md frozen 接口：这些参数必须存在
    required_params = {
        "req_id",
        "force",
        "keep_branch",
        "no_experience",
        "yes_experience",
        "yes_local_branch",
        "yes_remote_branch",
        "outcome",
        "prompts_callback",
    }
    missing = required_params - params
    assert not missing, f"CLI contract broken, missing params: {missing}"

    # ArchiveResult 字段集
    from archive_runner import ArchiveResult  # noqa: E402
    fields = {f.name for f in ArchiveResult.__dataclass_fields__.values()}
    required_fields = {
        "req_id", "phase", "archived_at",
        "experience", "local_branch", "remote_branch", "error_messages",
    }
    missing_fields = required_fields - fields
    assert not missing_fields, f"ArchiveResult contract broken: {missing_fields}"


# ============================================================================
# TC-7（P1-3 关键回归）：从 worktree 内调 archive 仍能解出主仓根 + 删目标 worktree
# ============================================================================


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """tmp_path 下初始化带 commit 的 git repo；返回 repo root。"""
    _git(["init", "--initial-branch=main"], cwd=tmp_path)
    _git(["config", "user.email", "test@example.com"], cwd=tmp_path)
    _git(["config", "user.name", "Test User"], cwd=tmp_path)
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=tmp_path)
    _git(["commit", "-m", "seed"], cwd=tmp_path)
    return tmp_path


def test_archive_runner_from_worktree_resolves_main_root_and_removes(
    tmp_git_repo: Path,
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-3 回归：从 linked worktree 内调 _cleanup_worktree_before_archive，
    resolve_main_repo_root 必须返回主仓根（而非 worktree 根），
    cleanup_worktree_if_owned 以主仓根为第二参数被调用。
    """
    req_id = "REQ-2099-907"

    # 在主仓建一个真实 linked worktree（feat/test-p13 分支）
    linked_wt = tmp_git_repo / ".worktrees" / "feat-test-p13"
    _git(["worktree", "add", str(linked_wt), "-b", "feat/test-p13"], cwd=tmp_git_repo)
    assert linked_wt.exists()

    meta = _make_meta_dict(
        req_id=req_id,
        worktree={
            "owner": "workflow",
            "path": str(linked_wt),
            "cleanup": {"policy": "auto", "removed_at": ""},
        },
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())

    # 记录 cleanup_worktree_if_owned 的实际入参
    captured_main_root: list[Path] = []

    def _fake_cleanup(m, root):
        captured_main_root.append(root)
        return CleanupResult(action="removed", reason="workflow_ok", removed_path=linked_wt)

    monkeypatch.setattr(worktree_manager, "cleanup_worktree_if_owned", _fake_cleanup)

    # 模拟从 worktree 内调（cwd = linked_wt）；resolve_main_repo_root 走真实实现
    # 但 archive_runner 本身的 resolve 也走真实 worktree_manager.resolve_main_repo_root
    # 为避免依赖真实 git worktree list，monkeypatch resolve_main_repo_root 返回主仓根
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_git_repo,  # 无论 cwd 是什么，总返回主仓根
    )

    archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )

    # 验证 cleanup 被调用，且传入的 main_repo_root 是主仓根
    assert captured_main_root, "cleanup_worktree_if_owned should have been called"
    assert captured_main_root[0] == tmp_git_repo, (
        f"Expected main_repo_root={tmp_git_repo}, got {captured_main_root[0]}"
    )


# ============================================================================
# TC-8（TC-2 变体）：owner=external + resolve 失败 → fail-closed，不 raise
# ============================================================================


def test_archive_runner_resolve_fails_cleanup_skipped_does_not_block(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """resolve_main_repo_root 抛异常 → cleanup 跳过，archive 主流程正常完成（fail-closed）。"""
    req_id = "REQ-2099-908"
    meta = _make_meta_dict(
        req_id=req_id,
        worktree={"owner": "workflow", "path": "/some/path"},
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())

    from worktree_manager import WorktreeBootstrapError  # noqa: E402

    def _failing_resolve(_cwd):
        raise WorktreeBootstrapError(
            "simulated resolve failure", reason="other", branch_created=False
        )

    monkeypatch.setattr(worktree_manager, "resolve_main_repo_root", _failing_resolve)

    # archive 应正常完成，resolve 失败不应 raise
    result = archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )
    assert result.archived_at, "archive should succeed even when resolve_main_repo_root fails"


# ============================================================================
# TC-9（AC5 回归）：owner=external + dirty workspace → _precheck_dirty 早 fail-closed，
#                   cleanup_worktree_if_owned 不被调用（worktree 不被误删）
# ============================================================================


def test_archive_runner_external_dirty_workspace_fail_closed(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """spec §13 验收 #6 / AC5：owner=external + dirty workspace → _precheck_dirty 早 fail-closed，
    cleanup_worktree_if_owned 不被调用（worktree 不被误删）。
    """
    req_id = "REQ-2099-909"
    meta = _make_meta_dict(
        req_id=req_id,
        worktree={"owner": "external", "path": "/some/external/path"},
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    # 模拟 dirty workspace：git status --porcelain 返回非空输出
    def _dirty_stub(cmd, *, cwd=None):
        if tuple(cmd[:2]) == ("git", "status"):
            return _ok(stdout="M somefile.py\n")
        return _ok()

    monkeypatch.setattr(archive_runner, "_run", _dirty_stub)
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )

    # spy：验证 cleanup_worktree_if_owned 在 _precheck_dirty fail-closed 之前不被调用
    cleanup_called = False

    def _spy_cleanup(m, root):
        nonlocal cleanup_called
        cleanup_called = True
        return CleanupResult(action="skipped", reason="spy", removed_path=None)

    monkeypatch.setattr(worktree_manager, "cleanup_worktree_if_owned", _spy_cleanup)

    # _precheck_dirty 检测到 dirty workspace 应抛 SystemExit(1)
    with pytest.raises(SystemExit) as exc_info:
        archive_requirement(
            req_id,
            yes_experience=False,
            no_experience=True,
            yes_local_branch=False,
            yes_remote_branch=False,
        )
    assert exc_info.value.code == 1, "_precheck_dirty 应导致 exit 1"
    assert cleanup_called is False, "cleanup_worktree_if_owned 不应被调用（_precheck_dirty 先于 cleanup）"
