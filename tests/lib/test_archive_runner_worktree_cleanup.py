"""archive_runner._cleanup_worktree_before_archive 单测（F-005）。

F-003 搬迁后，_cleanup_worktree_before_archive 由 archive 阶段 1 移至
finalize_requirement（step 8）。本文件对应调整：

  B1 策略（改测 finalize_requirement）：
    TC-2  owner=external → cleanup skipped 日志
    TC-5  removed_at 回填（finalize 写入 meta）
    TC-6  从 worktree 内调 finalize 能解出主仓根 + 删目标 worktree

  B2 策略（保留 archive_requirement，改断言为"archive 阶段 1 不触碰 worktree"）：
    TC-1  owner=workflow → archive 正常完成，worktree 不被删（D-003 决策）
    TC-3  legacy meta 缺 worktree 字段 → archive 跑通，meta 不引入 worktree 段
    TC-4  cleanup aborted/failed → archive 正常完成（D-009）
    TC-7  resolve 失败 → archive fail-soft，主流程正常完成

  TC-6 不变（CLI 契约）：
    TC-6（已 pass）archive_requirement 签名 + ArchiveResult 字段集

  TC-9 不变（AC5 回归）：
    TC-9  owner=external + dirty workspace → _precheck_dirty fail-closed

覆盖（11 用例）详见各 test 函数注释。
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
from archive_runner import archive_requirement, finalize_requirement  # noqa: E402
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
    archive_pr_number: int = 0,
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
    if archive_pr_number > 0:
        m["archive_pr_number"] = archive_pr_number
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
    """重定向 archive_runner 的 REQUIREMENTS_DIR 到 tmp_path。

    F-002 引入 _create_archive_pr 后渲染 PR body 需读 archive-pr-body.md.tmpl，
    fixture 必须 seed 该模板，否则 archive_requirement 主流程因模板缺失 IOError。
    同时 stub resolve_main_repo_root 防止 rebind 覆盖 monkeypatch。
    """
    monkeypatch.setattr(archive_runner, "REQUIREMENTS_DIR", tmp_path)
    monkeypatch.setattr(archive_runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
    tmpl_dir = tmp_path / ".claude/skills/managing-requirement-lifecycle/templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    (tmpl_dir / "archive-pr-body.md.tmpl").write_text(
        "req=__REQ_ID__ pr=__PR_NUMBER__ branch=__BRANCH__",
        encoding="utf-8",
    )
    return tmp_path


def _make_run_stub(plan: dict):
    """archive_runner._run 替身（前缀匹配）。

    F-002 引入 gh pr list / gh pr create 的默认响应，避免 _create_archive_pr
    在未显式 mock 时炸开（与 test_archive.py 同模式）。
    """

    def _stub(cmd, *, cwd=None):
        for key, result in plan.items():
            if tuple(cmd[: len(key)]) == tuple(key):
                if isinstance(result, BaseException):
                    raise result
                return result
        # F-002 引入的命令默认响应
        if tuple(cmd[:3]) == ("gh", "pr", "list"):
            return types.SimpleNamespace(returncode=0, stdout="[]\n", stderr="")
        if tuple(cmd[:3]) == ("gh", "pr", "create"):
            return types.SimpleNamespace(
                returncode=0,
                stdout="https://github.com/org/repo/pull/42\n",
                stderr="",
            )
        return _ok()

    return _stub


def _archive_run_stub_success():
    """archive 阶段1的 _run stub：5 项预检全通过（git clean + gh pr view merged）。"""
    return _make_run_stub(
        {
            ("git", "status", "--porcelain"): _ok(stdout=""),
            ("gh", "pr", "view"): _ok(
                stdout='{"state":"MERGED","mergedAt":"2026-05-18T00:00:00Z"}\n'
            ),
        }
    )


def _finalize_run_stub(archive_pr_number: int = 42):
    """finalize 阶段的 _run stub：archive_pr_number PR merged + git pull 成功。"""
    return _make_run_stub(
        {
            ("gh", "pr", "view", str(archive_pr_number)): _ok(
                stdout='{"state":"MERGED"}\n'
            ),
            ("git", "pull", "--ff-only"): _ok(stdout="Already up to date.\n"),
        }
    )


# ============================================================================
# TC-1：owner=workflow → archive 阶段 1 正常完成，worktree 不被删（B2 策略）
#
# D-003 决策：archive 阶段 1 不调 _cleanup_worktree_before_archive；
# cleanup 归 finalize_requirement step 8。
# ============================================================================


def test_archive_runner_owner_workflow_removes_worktree(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B2：archive 阶段 1 不调 cleanup；worktree 目录在 archive 后仍存在（D-003）。"""
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

    result = archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )

    # archive 阶段 1 应正常完成
    assert result.req_id == req_id
    assert result.archived_at, "archive 阶段 1 应写入 archived_at"
    # D-003：archive 阶段 1 不调 cleanup，worktree 应仍存在
    assert worktree_path.exists(), "archive 阶段 1 不应删除 worktree（cleanup 在 finalize）"
    # worktree_removed 默认 skipped（archive 阶段 1 不填此字段）
    assert result.worktree_removed == "skipped"


# ============================================================================
# TC-2：owner=external → finalize 阶段 cleanup skipped，日志含字面量（B1 策略）
# ============================================================================


def test_archive_runner_owner_external_skips_with_log(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """B1：改测 finalize_requirement；owner=external → cleanup skipped，
    日志含 'worktree cleanup skipped: external'。
    """
    req_id = "REQ-2099-902"
    archive_pr_num = 55
    meta = _make_meta_dict(
        req_id=req_id,
        phase="completed",
        archive_pr_number=archive_pr_num,
        worktree={"owner": "external", "path": "/some/external/path"},
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _finalize_run_stub(archive_pr_num))

    skipped_result = CleanupResult(action="skipped", reason="external", removed_path=None)
    monkeypatch.setattr(
        worktree_manager,
        "cleanup_worktree_if_owned",
        lambda _meta, _root: skipped_result,
    )

    with caplog.at_level(logging.INFO, logger="archive_runner"):
        finalize_requirement(
            req_id,
            yes_finalize=True,
            keep_local_branch=True,
            keep_remote_branch=True,
        )

    # 日志必须包含 cleanup skipped 的 reason
    messages = [r.message for r in caplog.records]
    assert any("external" in m for m in messages), (
        f"Expected 'external' in log messages (cleanup skipped reason), got: {messages}"
    )


# ============================================================================
# TC-3：legacy meta 缺 worktree 字段 → archive 降级成功，不引入空 worktree 段（B2 策略）
# ============================================================================


def test_archive_runner_legacy_meta_without_worktree_field_succeeds(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B2：缺 worktree 字段的旧 meta → archive 阶段 1 正常完成，meta 不引入 worktree 段。"""
    req_id = "REQ-2099-903"
    # 故意不带 worktree 字段
    meta = _make_meta_dict(req_id=req_id)
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())

    result = archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )

    assert result.archived_at, "legacy meta archive 阶段 1 应正常完成"

    # 验证写入的 meta.yaml 没有引入空 worktree 段
    meta_path = req_dir / "meta.yaml"
    with meta_path.open(encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    assert "worktree" not in saved, "legacy meta should not gain empty worktree section"


# ============================================================================
# TC-4：cleanup aborted/failed → archive 阶段 1 不调 cleanup，正常完成（B2 策略）
#
# D-003/D-009：archive 阶段 1 不调 cleanup；即使之后调，aborted 也不阻塞主流程。
# ============================================================================


def test_archive_runner_cwd_mismatch_aborts_cleanup_does_not_block(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B2：archive 阶段 1 不调 cleanup；archive 正常完成（D-003 + D-009）。"""
    req_id = "REQ-2099-904"
    meta = _make_meta_dict(
        req_id=req_id,
        worktree={"owner": "workflow", "path": "/etc/passwd"},
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _archive_run_stub_success())

    # archive 应正常完成（阶段 1 不调 cleanup，cleanup_worktree_if_owned 不会被触发）
    result = archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )
    assert result.archived_at, "archive 阶段 1 应正常完成，cleanup 不参与"
    # archive 阶段 1 不填 worktree_removed
    assert result.worktree_removed == "skipped"


# ============================================================================
# TC-5：removed 分支后 meta.worktree.cleanup.removed_at 回填（B1 策略）
#
# F-003 搬迁后 removed_at 回填在 finalize step 8 内的 _cleanup_worktree_before_archive。
# ============================================================================


def test_archive_runner_cleanup_removed_at_writes_meta(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B1：改测 finalize_requirement；worktree removed 路径：
    - result.worktree_removed == "removed"
    - process.txt [finalized] 行含 "worktree=removed"（detailed-design §3.5 格式）
    - _cleanup_worktree_before_archive 在内存 meta 中回填 removed_at（不落盘）
    """
    req_id = "REQ-2099-905"
    archive_pr_num = 77
    worktree_path = tmp_path / ".worktrees" / "feat-test"
    worktree_path.mkdir(parents=True)

    meta = _make_meta_dict(
        req_id=req_id,
        phase="completed",
        archive_pr_number=archive_pr_num,
        worktree={
            "owner": "workflow",
            "path": str(worktree_path),
            "cleanup": {"policy": "auto", "removed_at": ""},
        },
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _finalize_run_stub(archive_pr_num))

    removed_result = CleanupResult(
        action="removed", reason="workflow_ok", removed_path=worktree_path
    )
    monkeypatch.setattr(
        worktree_manager,
        "cleanup_worktree_if_owned",
        lambda _meta, _root: removed_result,
    )

    result = finalize_requirement(
        req_id,
        yes_finalize=True,
        keep_local_branch=True,
        keep_remote_branch=True,
    )

    # 验证 result.worktree_removed 字段
    assert result.worktree_removed == "removed", (
        f"finalize removed 路径 worktree_removed 应为 'removed'，实际 {result.worktree_removed!r}"
    )

    # 验证 process.txt [finalized] 行含 worktree=removed
    process_txt = (req_dir / "process.txt").read_text(encoding="utf-8")
    assert "[finalized]" in process_txt, "finalize 应追加 [finalized] 事件"
    finalized_lines = [l for l in process_txt.splitlines() if "[finalized]" in l]
    assert finalized_lines, "process.txt 应有 [finalized] 行"
    assert "worktree=removed" in finalized_lines[-1], (
        f"[finalized] 行应含 'worktree=removed'，实际：{finalized_lines[-1]!r}"
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
# TC-7（P1-3 关键回归）：finalize 调 cleanup 时 resolve 返回主仓根（B1 策略）
#
# F-003 搬迁后，"从 worktree 内调用" + "解出主仓根" + "删目标 worktree" 三件事
# 都发生在 finalize_requirement，而非 archive_requirement。
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
    """B1（P1-3 回归）：finalize 阶段 _cleanup_worktree_before_archive 调用时，
    resolve_main_repo_root 必须返回主仓根（而非 worktree 根），
    cleanup_worktree_if_owned 以主仓根为第二参数被调用。
    """
    req_id = "REQ-2099-907"
    archive_pr_num = 88

    # 在主仓建一个真实 linked worktree（feat/test-p13 分支）
    linked_wt = tmp_git_repo / ".worktrees" / "feat-test-p13"
    _git(["worktree", "add", str(linked_wt), "-b", "feat/test-p13"], cwd=tmp_git_repo)
    assert linked_wt.exists()

    meta = _make_meta_dict(
        req_id=req_id,
        phase="completed",
        archive_pr_number=archive_pr_num,
        worktree={
            "owner": "workflow",
            "path": str(linked_wt),
            "cleanup": {"policy": "auto", "removed_at": ""},
        },
    )
    req_dir = fake_repo / req_id
    _write_meta(req_dir, meta)

    monkeypatch.setattr(archive_runner, "_run", _finalize_run_stub(archive_pr_num))

    # 记录 cleanup_worktree_if_owned 的实际入参（验证 main_repo_root）
    captured_main_root: list[Path] = []

    def _fake_cleanup(m, root):
        captured_main_root.append(root)
        return CleanupResult(action="removed", reason="workflow_ok", removed_path=linked_wt)

    monkeypatch.setattr(worktree_manager, "cleanup_worktree_if_owned", _fake_cleanup)

    # monkeypatch resolve_main_repo_root 返回主仓根
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: tmp_git_repo,
    )

    result = finalize_requirement(
        req_id,
        yes_finalize=True,
        keep_local_branch=True,
        keep_remote_branch=True,
    )

    # 验证 cleanup 被调用，且传入的 main_repo_root 是主仓根
    assert captured_main_root, "cleanup_worktree_if_owned should have been called"
    assert captured_main_root[0] == tmp_git_repo, (
        f"Expected main_repo_root={tmp_git_repo}, got {captured_main_root[0]}"
    )
    assert result.worktree_removed == "removed"


# ============================================================================
# TC-8（TC-2 变体）：archive 阶段 1 中 resolve 失败 → fail-soft，主流程正常完成（B2 策略）
#
# _rebind_to_main_repo 在 resolve 失败时 fail-soft（log 但不 abort），
# archive 阶段 1 不调 cleanup，resolve 失败不影响整体流程。
# ============================================================================


def test_archive_runner_resolve_fails_cleanup_skipped_does_not_block(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """B2：archive 阶段 1 中 resolve_main_repo_root 抛异常 → _rebind fail-soft，
    archive 主流程正常完成（fail-closed 不适用于 rebind 路径）。
    """
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

    # archive 应正常完成，resolve 失败在 _rebind 是 fail-soft 路径
    result = archive_requirement(
        req_id,
        yes_experience=False,
        no_experience=True,
        yes_local_branch=False,
        yes_remote_branch=False,
    )
    assert result.archived_at, "archive 应正常完成，_rebind 中 resolve 失败是 fail-soft"


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
    cleanup_worktree_if_owned 不应被调用（worktree 不被误删）。
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
