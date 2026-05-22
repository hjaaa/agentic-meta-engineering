"""archive_runner finalize_requirement e2e 测试。

覆盖 18 TC：TC-F3-1 ~ TC-F3-18（F-003 + F-007）

外部依赖（subprocess gh / git）全 mock，不触网络、不动真 git。
cwd 三路径（TC-F3-8/9/10）用真实 os.chdir + tmp_path 实测。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import archive_runner  # noqa: E402
import worktree_manager  # noqa: E402
from archive_runner import (  # noqa: E402
    ArchivePrompt,
    _FINALIZE_WARN_FORCE_ONLY,
    _FINALIZE_WARN_FORCE_AND_YES,
    finalize_requirement,
)


# ---------- fixture 辅助函数 ----------


def _make_meta(
    tmp_path: Path,
    *,
    req_id: str = "REQ-2099-002",
    phase: str = "completed",
    pr_number: int = 42,
    branch: str = "feat/req-2099-002",
    base_branch: str = "develop",
    archive_pr_number: int = 55,
    archived_at: str = "2026-05-10 10:00:00",
    lessons_extracted: bool = True,
) -> Path:
    """构造临时 requirements/<req>/meta.yaml；返回 req 目录路径。"""
    req_dir = tmp_path / req_id
    req_dir.mkdir(parents=True)
    meta: dict[str, Any] = {
        "id": req_id,
        "title": f"测试需求 {req_id}",
        "phase": phase,
        "branch": branch,
        "base_branch": base_branch,
        "pr_number": pr_number,
        "archive_pr_number": archive_pr_number,
        "archived_at": archived_at,
        "created_at": "2026-05-04 19:00:00",
        "outcome": "shipped",
        "completed_at": "2026-05-10 10:00:00",
        "project": "agentic-meta-engineering",
        "lessons_extracted": lessons_extracted,
    }
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    (req_dir / "process.txt").write_text(
        "2026-05-04 19:00:00 [phase-transition] bootstrap → testing\n"
        "2026-05-10 10:00:00 [archived] (PR #42 merged at 2026-05-10 10:00:00)\n",
        encoding="utf-8",
    )
    return req_dir


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 archive_runner 的 REQUIREMENTS_DIR / REPO_ROOT 重定向到 tmp_path。

    stub resolve_main_repo_root 防 rebind 覆盖。
    stub cleanup_worktree_if_owned 返回 skipped（避免真实 worktree 操作）。
    """
    monkeypatch.setattr(archive_runner, "REQUIREMENTS_DIR", tmp_path)
    monkeypatch.setattr(archive_runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sys.modules["worktree_manager"],
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
    monkeypatch.setattr(
        worktree_manager,
        "cleanup_worktree_if_owned",
        lambda meta, root: types.SimpleNamespace(action="removed", removed_path="/fake/worktree", reason=""),
    )
    return tmp_path


def _make_run_stub(plan: dict[tuple, Any]):
    """构造 archive_runner._run 的替身（前缀匹配）。"""

    def _stub(cmd, *, cwd=None):
        for key, result in plan.items():
            if tuple(cmd[: len(key)]) == key:
                if isinstance(result, BaseException):
                    raise result
                return result
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    return _stub


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0):
    """构造成功 subprocess 结果存根。"""
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "error", returncode: int = 1):
    """构造失败 subprocess 结果存根。"""
    return types.SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)


def _merged_pr_json(number: int = 55) -> str:
    """构造 gh pr view 返回的 MERGED 状态 JSON 字符串。"""
    return json.dumps({"state": "MERGED", "number": number})


def _make_happy_path_plan(archive_pr_number: int = 55, branch: str = "feat/req-2099-002"):
    """构造 finalize happy path 的 _run stub plan。"""
    return {
        ("gh", "pr", "view"): _ok(stdout=_merged_pr_json(archive_pr_number)),
        ("git", "pull"): _ok(),
        ("git", "branch", "-d"): _ok(),
        ("git", "push", "origin", "--delete"): _ok(),
        ("git", "rev-parse", "--abbrev-ref"): _ok(stdout="develop"),
        ("git", "switch"): _ok(),
    }


# ---------- TC-F3-1: finalize 正常路径 ----------


def test_finalize_happy_path(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F3-1: archive PR MERGED + user Y → local/remote 删 + worktree removed。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = _make_happy_path_plan()
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = finalize_requirement(
        req_id,
        yes_finalize=True,
        prompts_callback=None,
    )

    assert result.worktree_removed == "removed", (
        f"worktree should be 'removed' in happy path, got {result.worktree_removed!r}"
    )
    assert result.local_branch in ("deleted", "skipped", "failed"), (
        "local_branch should be processed"
    )
    assert result.remote_branch in ("deleted", "skipped", "already-deleted", "failed"), (
        "remote_branch should be processed"
    )
    assert result.experience != "aborted by user", (
        "should not be aborted in happy path"
    )


# ---------- TC-F3-2: finalize 预检 MISSING ----------


def test_finalize_precheck_archive_pr_missing(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-2: meta.archive_pr_number=0 → SystemExit(1) + R-FINALIZE-ARCHIVE-PR-MISSING。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=0)

    monkeypatch.setattr(archive_runner, "_run", _make_run_stub({}))

    with pytest.raises(SystemExit) as excinfo:
        finalize_requirement(req_id, yes_finalize=True)

    assert excinfo.value.code == 1, "should exit 1 when archive_pr_number=0"
    err = capsys.readouterr().err
    assert "R-FINALIZE-ARCHIVE-PR-MISSING" in err, (
        f"stderr should contain R-FINALIZE-ARCHIVE-PR-MISSING, got: {err!r}"
    )


# ---------- TC-F3-3: finalize 预检 FETCH-FAILED ----------


def test_finalize_precheck_fetch_failed(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-3: gh pr view 返回 1 → SystemExit(1) + R-FINALIZE-ARCHIVE-PR-FETCH-FAILED。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = {("gh", "pr", "view"): _fail("gh error", returncode=1)}
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        finalize_requirement(req_id, yes_finalize=True)

    assert excinfo.value.code == 1, "should exit 1 when gh pr view fails"
    err = capsys.readouterr().err
    assert "R-FINALIZE-ARCHIVE-PR-FETCH-FAILED" in err, (
        f"stderr should contain R-FINALIZE-ARCHIVE-PR-FETCH-FAILED, got: {err!r}"
    )


# ---------- TC-F3-4: finalize 预检 NOT-MERGED ----------


def test_finalize_precheck_not_merged(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-4: gh 返回 state=OPEN → SystemExit(1) + R-FINALIZE-ARCHIVE-PR-NOT-MERGED。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = {("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "OPEN"}))}
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        finalize_requirement(req_id, yes_finalize=True)

    assert excinfo.value.code == 1, "should exit 1 when PR not merged"
    err = capsys.readouterr().err
    assert "R-FINALIZE-ARCHIVE-PR-NOT-MERGED" in err, (
        f"stderr should contain R-FINALIZE-ARCHIVE-PR-NOT-MERGED, got: {err!r}"
    )


# ---------- TC-F3-5: finalize --force 跳预检 ----------


def test_finalize_force_skip_precheck_warns(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-5: finalize --force 跳预检 + 警告文案（§3.4 行 1）；不调 gh pr view。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    gh_view_called = []

    plan = {
        ("git", "pull"): _ok(),
        ("git", "branch", "-d"): _ok(),
        ("git", "push", "origin", "--delete"): _ok(),
        ("git", "rev-parse", "--abbrev-ref"): _ok(stdout="develop"),
        ("git", "switch"): _ok(),
    }

    def tracking_run(cmd, *, cwd=None):
        if tuple(cmd[:3]) == ("gh", "pr", "view"):
            gh_view_called.append(cmd)
        for key, res in plan.items():
            if tuple(cmd[: len(key)]) == key:
                return res
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", tracking_run)

    # callback 答 Y 让 force-only 二次确认通过
    def callback(prompt: ArchivePrompt) -> bool:
        return True

    finalize_requirement(
        req_id,
        force=True,
        yes_finalize=False,
        prompts_callback=callback,
    )

    err = capsys.readouterr().err
    assert _FINALIZE_WARN_FORCE_ONLY in err, (
        f"stderr should contain §3.4 行 1 force-only warning text, got: {err!r}"
    )
    assert not gh_view_called, "gh pr view should NOT be called when --force is set"


# ---------- TC-F3-6: finalize --force + --yes-finalize ----------


def test_finalize_force_and_yes_finalize_warns(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-6: finalize --force + --yes-finalize 双重警告文案（§3.4 行 3）；不问 callback。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    callback_called = []

    plan = {
        ("git", "pull"): _ok(),
        ("git", "branch", "-d"): _ok(),
        ("git", "push", "origin", "--delete"): _ok(),
        ("git", "rev-parse", "--abbrev-ref"): _ok(stdout="develop"),
        ("git", "switch"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    def callback(prompt: ArchivePrompt) -> bool:
        callback_called.append(prompt.kind)
        return True

    finalize_requirement(
        req_id,
        force=True,
        yes_finalize=True,
        prompts_callback=callback,
    )

    err = capsys.readouterr().err
    assert _FINALIZE_WARN_FORCE_AND_YES in err, (
        f"stderr should contain §3.4 行 3 force+yes warning text, got: {err!r}"
    )
    assert "finalize" not in callback_called, (
        "callback should NOT be called for finalize kind when --force + --yes-finalize"
    )


# ---------- TC-F3-7: finalize 合并问询 N ----------


def test_finalize_user_answers_no(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F3-7: 合并问询 user 答 N → result.experience='aborted by user' + exit 0；无删除动作。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = {("gh", "pr", "view"): _ok(stdout=_merged_pr_json(55))}
    delete_called = []

    def tracking_run(cmd, *, cwd=None):
        if "delete" in cmd or ("-d" in cmd and "branch" in cmd):
            delete_called.append(cmd)
        for key, res in plan.items():
            if tuple(cmd[: len(key)]) == key:
                return res
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", tracking_run)

    # callback answers N for finalize prompt
    def callback(prompt: ArchivePrompt) -> bool:
        if prompt.kind == "finalize":
            return False
        return True

    result = finalize_requirement(req_id, yes_finalize=False, prompts_callback=callback)

    assert result.experience == "aborted by user", (  # type: ignore[comparison-overlap]
        f"result.experience should be 'aborted by user', got {result.experience!r}"
    )
    assert not delete_called, "no delete operations should happen when user answers N"


# ---------- TC-F3-8: finalize cwd 在主仓 ----------


def test_finalize_cwd_in_main_repo(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TC-F3-8: cwd 在主仓时流程正常完成。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = _make_happy_path_plan()
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    original_cwd = Path.cwd()
    try:
        os.chdir(fake_repo)
        result = finalize_requirement(req_id, yes_finalize=True)
    finally:
        os.chdir(original_cwd)

    assert result.experience != "aborted by user", "should complete normally when cwd is main repo"


# ---------- TC-F3-9: finalize cwd 在 linked worktree ----------


def test_finalize_cwd_in_linked_worktree(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TC-F3-9: cwd 在 linked worktree 时 _rebind + chdir 到主仓后流程正常。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    # linked worktree 目录
    linked_wt = tmp_path / "linked-worktree"
    linked_wt.mkdir()

    # resolve_main_repo_root 从 linked_wt 出发也返回 fake_repo（主仓）
    monkeypatch.setattr(
        sys.modules["worktree_manager"],
        "resolve_main_repo_root",
        lambda _cwd: fake_repo,
    )

    plan = _make_happy_path_plan()
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    original_cwd = Path.cwd()
    try:
        os.chdir(linked_wt)
        result = finalize_requirement(req_id, yes_finalize=True)
    finally:
        os.chdir(original_cwd)

    assert result.experience != "aborted by user", "should complete normally when cwd is linked worktree"


# ---------- TC-F3-10: finalize cwd 删的 worktree 之外的目录 ----------


def test_finalize_cwd_outside_worktree_oserror(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """TC-F3-10: chdir 失败时 OSError 兜底 → R-FINALIZE-CWD-FAILED fail-closed。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    # resolve_main_repo_root 返回一个不存在的路径（导致 chdir OSError）
    nonexistent = tmp_path / "nonexistent-dir"

    monkeypatch.setattr(
        sys.modules["worktree_manager"],
        "resolve_main_repo_root",
        lambda _cwd: nonexistent,
    )
    # 同时更新 archive_runner 模块中的 worktree_manager 引用
    monkeypatch.setattr(
        worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: nonexistent,
    )

    plan = {("gh", "pr", "view"): _ok(stdout=_merged_pr_json(55))}
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        finalize_requirement(req_id, yes_finalize=True)

    assert excinfo.value.code == 1, "should fail-closed when chdir fails"


# ---------- TC-F3-11: finalize git pull --ff develop 失败 ----------


def test_finalize_pull_failed(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-11: git pull --ff develop 失败（非 fast-forward）→ SystemExit(1) + R-FINALIZE-PULL-FAILED。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = {
        ("gh", "pr", "view"): _ok(stdout=_merged_pr_json(55)),
        ("git", "pull"): _fail("fatal: Not possible to fast-forward, aborting.", returncode=1),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        finalize_requirement(req_id, yes_finalize=True)

    assert excinfo.value.code == 1, "should exit 1 when pull fails"
    err = capsys.readouterr().err
    assert "R-FINALIZE-PULL-FAILED" in err, (
        f"stderr should contain R-FINALIZE-PULL-FAILED, got: {err!r}"
    )


# ---------- TC-F3-12: finalize --keep-worktree ----------


def test_finalize_keep_worktree(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F3-12: --keep-worktree → worktree 保留；local/remote 仍删；process.txt 含 (--keep-worktree)。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = _make_happy_path_plan()
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = finalize_requirement(req_id, yes_finalize=True, keep_worktree=True)

    assert result.worktree_removed == "kept", (
        f"worktree should be 'kept' with --keep-worktree, got {result.worktree_removed!r}"
    )

    process_content = (fake_repo / req_id / "process.txt").read_text(encoding="utf-8")
    assert "(--keep-worktree)" in process_content, (
        f"process.txt should contain (--keep-worktree), got:\n{process_content}"
    )


# ---------- TC-F3-13: finalize --keep-local-branch ----------


def test_finalize_keep_local_branch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F3-13: --keep-local-branch → local 保留；remote/worktree 仍处理。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = _make_happy_path_plan()
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = finalize_requirement(req_id, yes_finalize=True, keep_local_branch=True)

    assert result.local_branch == "skipped", (
        f"local_branch should be 'skipped' with --keep-local-branch, got {result.local_branch!r}"
    )

    process_content = (fake_repo / req_id / "process.txt").read_text(encoding="utf-8")
    assert "(--keep-local-branch)" in process_content, (
        f"process.txt should contain (--keep-local-branch), got:\n{process_content}"
    )


# ---------- TC-F3-14: finalize --keep-remote-branch ----------


def test_finalize_keep_remote_branch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F3-14: --keep-remote-branch → remote 保留；local/worktree 仍处理。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = _make_happy_path_plan()
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = finalize_requirement(req_id, yes_finalize=True, keep_remote_branch=True)

    assert result.remote_branch == "skipped", (
        f"remote_branch should be 'skipped' with --keep-remote-branch, got {result.remote_branch!r}"
    )

    process_content = (fake_repo / req_id / "process.txt").read_text(encoding="utf-8")
    assert "(--keep-remote-branch)" in process_content, (
        f"process.txt should contain (--keep-remote-branch), got:\n{process_content}"
    )


# ---------- TC-F3-15: finalize 三 keep 全开 ----------


def test_finalize_all_keep_flags(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F3-15: 三 keep 全开 → 三件套全 skipped；process.txt 含三 flag 后缀。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = {
        ("gh", "pr", "view"): _ok(stdout=_merged_pr_json(55)),
        ("git", "pull"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = finalize_requirement(
        req_id,
        yes_finalize=True,
        keep_worktree=True,
        keep_local_branch=True,
        keep_remote_branch=True,
    )

    assert result.worktree_removed == "kept", (
        f"worktree should be 'kept', got {result.worktree_removed!r}"
    )
    assert result.local_branch == "skipped", (
        f"local_branch should be 'skipped', got {result.local_branch!r}"
    )
    assert result.remote_branch == "skipped", (
        f"remote_branch should be 'skipped', got {result.remote_branch!r}"
    )

    process_content = (fake_repo / req_id / "process.txt").read_text(encoding="utf-8")
    # _log_finalize_event 三 flag 合并为单括号后缀（archive_runner._finalize_collect_keep_flags + _log_finalize_event）
    assert "(--keep-worktree --keep-local-branch --keep-remote-branch)" in process_content, (
        f"process.txt should contain '(--keep-worktree --keep-local-branch --keep-remote-branch)', got:\n{process_content}"
    )


# ---------- TC-F3-16: finalize --legacy-resurrect-remote remote 不存在 ----------


def test_finalize_legacy_resurrect_remote_already_deleted(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F3-16: --legacy-resurrect-remote + remote 不存在 → result.remote_branch='already-deleted'；不写 error_messages。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    plan = {
        ("gh", "pr", "view"): _ok(stdout=_merged_pr_json(55)),
        ("git", "pull"): _ok(),
        ("git", "branch", "-d"): _ok(),
        ("git", "rev-parse", "--abbrev-ref"): _ok(stdout="develop"),
        ("git", "switch"): _ok(),
        # remote push --delete → stderr 含 "not found" (legacy keyword)
        ("git", "push", "origin", "--delete"): types.SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="error: remote ref not found",
        ),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = finalize_requirement(
        req_id,
        yes_finalize=True,
        legacy_resurrect_remote=True,
    )

    assert result.remote_branch == "already-deleted", (
        f"remote_branch should be 'already-deleted' with legacy_resurrect, got {result.remote_branch!r}"
    )
    remote_errors = [m for m in result.error_messages if "remote" in m.lower()]
    assert not remote_errors, (
        f"error_messages should not contain remote error when already-deleted, got: {result.error_messages}"
    )


# ---------- TC-F3-17: finalize remote network 失败 fail-soft ----------


def test_finalize_remote_network_fail_soft(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F3-17: remote network 失败 → result.remote_branch='failed'；manual_recovery_commands 含 git push origin --delete <branch>。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55, branch="feat/req-2099-002")

    plan = {
        ("gh", "pr", "view"): _ok(stdout=_merged_pr_json(55)),
        ("git", "pull"): _ok(),
        ("git", "branch", "-d"): _ok(),
        ("git", "rev-parse", "--abbrev-ref"): _ok(stdout="develop"),
        ("git", "switch"): _ok(),
        ("git", "push", "origin", "--delete"): _fail("Connection refused", returncode=1),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = finalize_requirement(
        req_id,
        yes_finalize=True,
        legacy_resurrect_remote=True,  # legacy mode to get manual_recovery_commands
    )

    assert result.remote_branch == "failed", (
        f"remote_branch should be 'failed' on network failure, got {result.remote_branch!r}"
    )
    recovery_cmds = " ".join(result.manual_recovery_commands)
    assert "git push origin --delete" in recovery_cmds, (
        f"manual_recovery_commands should contain 'git push origin --delete', got: {result.manual_recovery_commands}"
    )
    assert "feat/req-2099-002" in recovery_cmds, (
        f"manual_recovery_commands should contain branch name, got: {result.manual_recovery_commands}"
    )


# ---------- TC-F3-18: _delete_local_branch strict=True squash merge 不能删 ----------


def test_finalize_delete_local_branch_strict_squash_merge(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-18: _delete_local_branch strict=True — squash merge 不能删 → SystemExit(1) + transport stderr。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    squash_error = "error: The branch 'feat/req-2099-002' is not fully merged."
    plan = {
        ("gh", "pr", "view"): _ok(stdout=_merged_pr_json(55)),
        ("git", "pull"): _ok(),
        ("git", "rev-parse", "--abbrev-ref"): _ok(stdout="develop"),
        ("git", "switch"): _ok(),
        ("git", "branch", "-d"): _fail(squash_error, returncode=1),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        finalize_requirement(req_id, yes_finalize=True)

    assert excinfo.value.code == 1, "should exit 1 when branch -d fails with strict=True"
    err = capsys.readouterr().err
    # strict=True 路径：R-* 错误码必须出现（fail-closed 强制断言 features.json:138）
    assert "R-FINALIZE-LOCAL-BRANCH-FAILED" in err, (
        f"stderr must contain R-FINALIZE-LOCAL-BRANCH-FAILED (fail-closed 强制), got: {err!r}"
    )


# ---------- TC-F3-19: finalize 预检 subprocess.TimeoutExpired ----------


def test_finalize_precheck_subprocess_timeout(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-19: gh pr view 抛 TimeoutExpired → SystemExit(1) + R-FINALIZE-ARCHIVE-PR-FETCH-FAILED。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    # _make_run_stub 支持 isinstance(result, BaseException) → raise result
    plan = {
        ("gh", "pr", "view"): subprocess.TimeoutExpired(cmd=["gh"], timeout=30),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        finalize_requirement(req_id, yes_finalize=True)

    assert excinfo.value.code == 1, "should exit 1 on TimeoutExpired"
    err = capsys.readouterr().err
    assert "R-FINALIZE-ARCHIVE-PR-FETCH-FAILED" in err, (
        f"stderr must contain R-FINALIZE-ARCHIVE-PR-FETCH-FAILED on timeout, got: {err!r}"
    )


# ---------- TC-F3-20: finalize 预检 FileNotFoundError ----------


def test_finalize_precheck_subprocess_file_not_found(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F3-20: gh pr view 抛 FileNotFoundError → SystemExit(1) + R-FINALIZE-ARCHIVE-PR-FETCH-FAILED。"""
    req_id = "REQ-2099-002"
    _make_meta(fake_repo, req_id=req_id, archive_pr_number=55)

    # FileNotFoundError = gh 二进制不在 PATH 中
    plan = {
        ("gh", "pr", "view"): FileNotFoundError("gh: command not found"),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        finalize_requirement(req_id, yes_finalize=True)

    assert excinfo.value.code == 1, "should exit 1 on FileNotFoundError"
    err = capsys.readouterr().err
    assert "R-FINALIZE-ARCHIVE-PR-FETCH-FAILED" in err, (
        f"stderr must contain R-FINALIZE-ARCHIVE-PR-FETCH-FAILED on FileNotFoundError, got: {err!r}"
    )
