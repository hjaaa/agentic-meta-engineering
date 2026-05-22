"""archive_runner F-001 / F-002 单元测试。

覆盖 13 TC：
  TC-F1-1 ~ TC-F1-5：_commit_archive_metadata / _push_feat_branch
  TC-F2-1 ~ TC-F2-8：_create_archive_pr / _write_archive_pr_number / PR body 渲染

外部依赖（subprocess gh / git）全 mock，不触网络、不动真 git。
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import archive_runner  # noqa: E402
from archive_runner import (  # noqa: E402
    ArchiveResult,
    _commit_archive_metadata,
    _create_archive_pr,
    _push_feat_branch,
    _write_archive_pr_number,
    _render_archive_pr_body,
)


# ---------- fixture 辅助函数 ----------


def _make_meta(
    tmp_path: Path,
    *,
    req_id: str = "REQ-2099-001",
    phase: str = "testing",
    pr_number: int = 42,
    branch: str = "feat/req-2099-001",
    base_branch: str = "develop",
    archive_pr_number: int = 0,
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
        "archived_at": "",
        "created_at": "2026-05-04 19:00:00",
        "project": "agentic-meta-engineering",
        "lessons_extracted": lessons_extracted,
    }
    if archive_pr_number:
        meta["archive_pr_number"] = archive_pr_number
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    (req_dir / "process.txt").write_text(
        f"2026-05-04 19:00:00 [phase-transition] bootstrap → {phase}\n",
        encoding="utf-8",
    )
    return req_dir


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 archive_runner 的 REQUIREMENTS_DIR / REPO_ROOT 重定向到 tmp_path。

    避免真动到仓库内 requirements/ 目录。stub resolve_main_repo_root 防 rebind
    把 monkeypatch 的 REPO_ROOT 覆盖回真实仓库根。
    """
    monkeypatch.setattr(archive_runner, "REQUIREMENTS_DIR", tmp_path)
    monkeypatch.setattr(archive_runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sys.modules["worktree_manager"],
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
    # 在 tmp_path 下创建模板路径（供 _render_archive_pr_body 读取）
    tmpl_dir = (
        tmp_path
        / ".claude"
        / "skills"
        / "managing-requirement-lifecycle"
        / "templates"
    )
    tmpl_dir.mkdir(parents=True)
    (tmpl_dir / "archive-pr-body.md.tmpl").write_text(
        "req=__REQ_ID__ pr=__PR_NUMBER__ branch=__BRANCH__",
        encoding="utf-8",
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


# ---------- TC-F1-1: _commit_archive_metadata 幂等 ----------


def test_commit_archive_metadata_idempotent(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F1-1: HEAD commit message 含 archive(<id>): metadata 时函数提前 return。"""
    req_id = "REQ-2099-001"
    _make_meta(fake_repo, req_id=req_id)

    commit_subject = f"archive({req_id}): metadata"
    git_add_called = []

    plan = {
        ("git", "log", "-1"): _ok(stdout=commit_subject),
    }
    orig_run = _make_run_stub(plan)

    def tracking_run(cmd, *, cwd=None):
        if "add" in cmd:
            git_add_called.append(cmd)
        return orig_run(cmd, cwd=cwd)

    monkeypatch.setattr(archive_runner, "_run", tracking_run)

    result = ArchiveResult(req_id=req_id)
    _commit_archive_metadata(req_id, result)

    assert not git_add_called, "idempotent: git add should not be called"


# ---------- TC-F1-2: _commit_archive_metadata 白名单 ----------


def test_commit_archive_metadata_whitelist(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F1-2: 仅 requirements/<id>/ + context/team/experience/ 改动正常 commit。"""
    req_id = "REQ-2099-001"
    _make_meta(fake_repo, req_id=req_id)

    # 非 archive commit subject
    plan = {
        ("git", "log", "-1"): _ok(stdout="some other commit"),
        ("git", "status", "--porcelain"): _ok(
            stdout=f" M requirements/{req_id}/meta.yaml\n M context/team/experience/foo.md\n"
        ),
    }
    git_commit_called = []

    def tracking_run(cmd, *, cwd=None):
        if "commit" in cmd and "-m" in cmd:
            git_commit_called.append(cmd)
        for key, res in plan.items():
            if tuple(cmd[: len(key)]) == key:
                return res
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", tracking_run)

    result = ArchiveResult(req_id=req_id)
    _commit_archive_metadata(req_id, result)

    assert git_commit_called, "commit should be called for whitelist-only changes"
    commit_msg_arg = git_commit_called[0][-1]
    assert commit_msg_arg == f"archive({req_id}): metadata", (
        f"commit message must be 'archive({req_id}): metadata', got {commit_msg_arg!r}"
    )


# ---------- TC-F1-3: _commit_archive_metadata 非白名单 ----------


def test_commit_archive_metadata_non_whitelist_dirty(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F1-3: scripts/lib/foo.py dirty → SystemExit(1) + stderr 含 R-ARCHIVE-CONTEXT-DIRTY。"""
    req_id = "REQ-2099-001"
    _make_meta(fake_repo, req_id=req_id)

    plan = {
        ("git", "log", "-1"): _ok(stdout="some other commit"),
        ("git", "status", "--porcelain"): _ok(stdout=" M scripts/lib/foo.py\n"),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = ArchiveResult(req_id=req_id)
    with pytest.raises(SystemExit) as excinfo:
        _commit_archive_metadata(req_id, result)

    assert excinfo.value.code == 1, "should exit 1 for non-whitelist dirty files"
    err = capsys.readouterr().err
    assert "R-ARCHIVE-CONTEXT-DIRTY" in err, (
        f"stderr should contain R-ARCHIVE-CONTEXT-DIRTY, got: {err!r}"
    )


# ---------- TC-F1-4: _push_feat_branch 幂等 ----------


def test_push_feat_branch_idempotent(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F1-4: HEAD == origin/feat/<id> 时不调 git push。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id, branch="feat/req-2099-001")

    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))

    sha = "abc123"
    push_called = []

    plan = {
        ("git", "rev-parse", "HEAD"): _ok(stdout=sha),
        ("git", "rev-parse", "origin/feat/req-2099-001"): _ok(stdout=sha),
    }

    def tracking_run(cmd, *, cwd=None):
        if tuple(cmd[:2]) == ("git", "push"):
            push_called.append(cmd)
        for key, res in plan.items():
            if tuple(cmd[: len(key)]) == key:
                return res
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", tracking_run)

    result = ArchiveResult(req_id=req_id)
    _push_feat_branch(meta, req_id, result)

    assert not push_called, "idempotent: git push should not be called when HEAD == origin"


# ---------- TC-F1-5: _push_feat_branch 首次推送 ----------


def test_push_feat_branch_first_push(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F1-5: origin 无该分支时 git push origin <branch> 成功。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id, branch="feat/req-2099-001")
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))

    local_sha = "abc123"
    push_called = []

    plan = {
        ("git", "rev-parse", "HEAD"): _ok(stdout=local_sha),
        # origin/<branch> 不存在 → rev-parse 返回非零
        ("git", "rev-parse", "origin/feat/req-2099-001"): _fail("not found", returncode=128),
    }

    def tracking_run(cmd, *, cwd=None):
        if tuple(cmd[:3]) == ("git", "push", "origin"):
            push_called.append(cmd)
            return _ok()
        for key, res in plan.items():
            if tuple(cmd[: len(key)]) == key:
                return res
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", tracking_run)

    result = ArchiveResult(req_id=req_id)
    _push_feat_branch(meta, req_id, result)

    assert push_called, "git push should be called when origin does not have the branch"
    assert "feat/req-2099-001" in push_called[0], (
        "push command should include the branch name"
    )


# ---------- TC-F2-1: _create_archive_pr 幂等 OPEN ----------


def test_create_archive_pr_idempotent_open(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F2-1: gh pr list 返回 OPEN PR → reuse；不调 gh pr create。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id)
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))

    existing_pr = [{"number": 55, "state": "OPEN", "url": "https://github.com/org/repo/pull/55"}]
    pr_create_called = []

    plan = {
        ("gh", "pr", "list"): _ok(stdout=json.dumps(existing_pr)),
    }

    def tracking_run(cmd, *, cwd=None):
        if tuple(cmd[:3]) == ("gh", "pr", "create"):
            pr_create_called.append(cmd)
        for key, res in plan.items():
            if tuple(cmd[: len(key)]) == key:
                return res
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", tracking_run)

    result = ArchiveResult(req_id=req_id)
    pr_number = _create_archive_pr(meta, req_id, result)

    assert pr_number == 55, f"should reuse existing OPEN PR number=55, got {pr_number}"
    assert result.archive_pr_action == "reused", (
        f"archive_pr_action should be 'reused', got {result.archive_pr_action!r}"
    )
    assert not pr_create_called, "gh pr create should not be called for OPEN PR reuse"


# ---------- TC-F2-2: _create_archive_pr MERGED meta=0 ----------


def test_create_archive_pr_idempotent_merged(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F2-2: gh pr list 返回 MERGED PR 但 meta.archive_pr_number=0 → SystemExit(1) + R-ARCHIVE-PR-ALREADY-MERGED。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id)
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))
    meta["archive_pr_number"] = 0

    merged_pr = [{"number": 55, "state": "MERGED", "url": "https://github.com/org/repo/pull/55"}]
    plan = {("gh", "pr", "list"): _ok(stdout=json.dumps(merged_pr))}
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = ArchiveResult(req_id=req_id)
    with pytest.raises(SystemExit) as excinfo:
        _create_archive_pr(meta, req_id, result)

    assert excinfo.value.code == 1, "should exit 1 for MERGED PR with archive_pr_number=0"
    err = capsys.readouterr().err
    assert "R-ARCHIVE-PR-ALREADY-MERGED" in err, (
        f"stderr should contain R-ARCHIVE-PR-ALREADY-MERGED, got: {err!r}"
    )


# ---------- TC-F2-3: _create_archive_pr CLOSED ----------


def test_create_archive_pr_idempotent_closed(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F2-3: gh pr list 返回 CLOSED PR → SystemExit(1) + R-ARCHIVE-PR-CLOSED。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id)
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))

    closed_pr = [{"number": 55, "state": "CLOSED", "url": "https://github.com/org/repo/pull/55"}]
    plan = {("gh", "pr", "list"): _ok(stdout=json.dumps(closed_pr))}
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = ArchiveResult(req_id=req_id)
    with pytest.raises(SystemExit) as excinfo:
        _create_archive_pr(meta, req_id, result)

    assert excinfo.value.code == 1, "should exit 1 for CLOSED PR"
    err = capsys.readouterr().err
    assert "R-ARCHIVE-PR-CLOSED" in err, (
        f"stderr should contain R-ARCHIVE-PR-CLOSED, got: {err!r}"
    )


# ---------- TC-F2-4: _create_archive_pr 冲突 ----------


def test_create_archive_pr_number_mismatch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """TC-F2-4: meta.archive_pr_number=42 但 gh 返回 number=99 → SystemExit(1) + R-ARCHIVE-PR-NUMBER-MISMATCH。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id, archive_pr_number=42)
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))

    existing_pr = [{"number": 99, "state": "OPEN", "url": "https://github.com/org/repo/pull/99"}]
    plan = {("gh", "pr", "list"): _ok(stdout=json.dumps(existing_pr))}
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = ArchiveResult(req_id=req_id)
    with pytest.raises(SystemExit) as excinfo:
        _create_archive_pr(meta, req_id, result)

    assert excinfo.value.code == 1, "should exit 1 for PR number mismatch"
    err = capsys.readouterr().err
    assert "R-ARCHIVE-PR-NUMBER-MISMATCH" in err, (
        f"stderr should contain R-ARCHIVE-PR-NUMBER-MISMATCH, got: {err!r}"
    )


# ---------- TC-F2-5: _create_archive_pr 正常创建 ----------


def test_create_archive_pr_creates_new(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F2-5: gh pr list 空 → gh pr create 调用一次；返回新 PR number；archive_pr_action='created'。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id)
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))

    pr_create_calls = []

    plan = {
        ("gh", "pr", "list"): _ok(stdout="[]"),
    }

    def tracking_run(cmd, *, cwd=None):
        if tuple(cmd[:3]) == ("gh", "pr", "create"):
            pr_create_calls.append(cmd)
            return _ok(stdout="https://github.com/org/repo/pull/77\n")
        for key, res in plan.items():
            if tuple(cmd[: len(key)]) == key:
                return res
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", tracking_run)

    result = ArchiveResult(req_id=req_id)
    pr_number = _create_archive_pr(meta, req_id, result)

    assert len(pr_create_calls) == 1, "gh pr create should be called exactly once"
    assert pr_number == 77, f"should return new PR number=77, got {pr_number}"
    assert result.archive_pr_action == "created", (
        f"archive_pr_action should be 'created', got {result.archive_pr_action!r}"
    )


# ---------- TC-F2-6: _write_archive_pr_number 幂等 ----------


def test_write_archive_pr_number_idempotent(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-F2-6: meta.archive_pr_number 已等于目标 → 不调 _atomic_write_meta。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id, archive_pr_number=42)
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))

    write_called = []
    orig_write = archive_runner._atomic_write_meta

    def tracking_write(*args, **kwargs):
        write_called.append(args)
        return orig_write(*args, **kwargs)

    monkeypatch.setattr(archive_runner, "_atomic_write_meta", tracking_write)

    _write_archive_pr_number(req_id, meta, 42)

    assert not write_called, "idempotent: _atomic_write_meta should not be called when pr_number unchanged"


# ---------- TC-F2-7: _write_archive_pr_number 写入 ----------


def test_write_archive_pr_number_writes(
    fake_repo: Path,
) -> None:
    """TC-F2-7: meta.archive_pr_number=0 → 42 原子更新且其余字段不变。"""
    req_id = "REQ-2099-001"
    req_dir = _make_meta(fake_repo, req_id=req_id)
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))

    assert meta.get("archive_pr_number", 0) == 0

    # 保存修改前其余字段快照
    original_title = meta["title"]
    original_phase = meta["phase"]

    _write_archive_pr_number(req_id, meta, 42)

    updated = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))
    assert updated["archive_pr_number"] == 42, (
        f"archive_pr_number should be 42 after write, got {updated['archive_pr_number']}"
    )
    assert updated["title"] == original_title, "title should be unchanged after write"
    assert updated["phase"] == original_phase, "phase should be unchanged after write"


# ---------- TC-F2-8: PR body 渲染 ----------


def test_render_archive_pr_body_placeholders(
    fake_repo: Path,
) -> None:
    """TC-F2-8: 模板含 __REQ_ID__ / __PR_NUMBER__ / __BRANCH__ 三占位符替换正确。"""
    req_id = "REQ-2099-001"

    # fake_repo fixture 已写测试模板到 tmp_path/.claude/.../archive-pr-body.md.tmpl
    body = _render_archive_pr_body(req_id, 42, "feat/req-2099-001")

    assert req_id in body, f"REQ_ID should be in rendered body, got: {body!r}"
    assert "42" in body, f"PR_NUMBER should be in rendered body, got: {body!r}"
    assert "feat/req-2099-001" in body, f"BRANCH should be in rendered body, got: {body!r}"
    assert "__REQ_ID__" not in body, "placeholder __REQ_ID__ should be replaced"
    assert "__PR_NUMBER__" not in body, "placeholder __PR_NUMBER__ should be replaced"
    assert "__BRANCH__" not in body, "placeholder __BRANCH__ should be replaced"
