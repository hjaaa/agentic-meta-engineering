"""archive_runner.archive_requirement 单元测试。

覆盖 features.json acceptance TC-F3-1 ~ TC-F3-7：
  - TC-F3-1: phase 预检失败
  - TC-F3-2: dirty 预检失败
  - TC-F3-3: pr_number 预检失败
  - TC-F3-4: pr-merged 预检 OPEN / --force 跳过
  - TC-F3-5: 三问全 y 路径
  - TC-F3-6: 三问全 N 路径（meta + process.txt 仍写）
  - TC-F3-7: 副作用降级矩阵（experience failed / 本地 -d 拒绝 / 远程 already-deleted）

外部依赖（subprocess gh / git / claude）全 mock，不触网络、不动真 git。
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

# 让 archive_runner 的 import 能找到 scripts/lib
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import archive_runner  # noqa: E402
from archive_runner import (  # noqa: E402
    ArchivePrompt,
    archive_requirement,
)


# ---------- 基础 fixture ----------


def _make_meta(
    tmp_path: Path,
    *,
    req_id: str = "REQ-2099-007",
    phase: str = "testing",
    pr_number: int = 42,
    branch: str = "feat/req-2099-007",
    base_branch: str = "develop",
    archived_at: str = "",
) -> Path:
    """构造临时 requirements/<req>/meta.yaml；返回 req 目录路径。"""
    req_dir = tmp_path / req_id
    req_dir.mkdir(parents=True)
    meta = {
        "id": req_id,
        "title": f"测试需求 {req_id}",
        "phase": phase,
        "branch": branch,
        "base_branch": base_branch,
        "pr_number": pr_number,
        "archived_at": archived_at,
        "created_at": "2026-05-04 19:00:00",
        "project": "agentic-meta-engineering",
    }
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    # 预创建 process.txt（archive 不会自己 mkdir）
    (req_dir / "process.txt").write_text(
        f"2026-05-04 19:00:00 [phase-transition] bootstrap → {phase}\n",
        encoding="utf-8",
    )
    return req_dir


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 archive_runner 的 REQUIREMENTS_DIR / REPO_ROOT 重定向到 tmp_path。

    避免真动到仓库内 requirements/ 目录。
    """
    monkeypatch.setattr(archive_runner, "REQUIREMENTS_DIR", tmp_path)
    monkeypatch.setattr(archive_runner, "REPO_ROOT", tmp_path)
    return tmp_path


def _make_run_stub(plan: dict[tuple, Any]):
    """构造 archive_runner._run 的替身。

    plan: 形如 {("git", "status", "--porcelain"): SimpleNamespace(returncode=0, stdout="", stderr="")}
    匹配方式：tuple(cmd[: len(key)]) == key（前缀匹配，便于忽略尾部参数差异）。
    未命中默认返回 returncode=0 / stdout="" / stderr=""。
    """

    def _stub(cmd, *, cwd=None):  # 匹配 archive_runner._run 签名
        for key, result in plan.items():
            if tuple(cmd[: len(key)]) == key:
                if isinstance(result, BaseException):
                    raise result
                return result
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    return _stub


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ---------- TC-F3-1: phase 预检 ----------


def test_precheck_phase_invalid(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """phase=development → exit 1 + stderr 含 R-ARCHIVE-PHASE。"""
    _make_meta(fake_repo, phase="development")
    # _run 不会被调用（phase 是第 1 项预检）；放个空 stub 防意外
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub({}))

    with pytest.raises(SystemExit) as excinfo:
        archive_requirement("REQ-2099-007")
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "R-ARCHIVE-PHASE" in err
    assert "development" in err


# ---------- TC-F3-2: dirty 预检 ----------


def test_precheck_dirty(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """git status 非空 → R-ARCHIVE-DIRTY。"""
    _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(stdout=" M some/file.py\n"),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        archive_requirement("REQ-2099-007")
    assert excinfo.value.code == 1
    assert "R-ARCHIVE-DIRTY" in capsys.readouterr().err


# ---------- TC-F3-3: pr_number 预检 ----------


def test_precheck_no_pr(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """meta.pr_number=0 → R-ARCHIVE-NO-PR。"""
    _make_meta(fake_repo, pr_number=0)
    plan = {("git", "status", "--porcelain"): _ok()}
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        archive_requirement("REQ-2099-007")
    assert excinfo.value.code == 1
    assert "R-ARCHIVE-NO-PR" in capsys.readouterr().err


# ---------- TC-F3-4: pr-merged 预检 + --force ----------


def test_precheck_pr_not_merged(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """gh pr view state=OPEN → R-ARCHIVE-PR-NOT-MERGED。"""
    _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "OPEN"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        archive_requirement("REQ-2099-007")
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "R-ARCHIVE-PR-NOT-MERGED" in err
    assert "OPEN" in err


def test_force_skips_pr_merged_check(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--force 跳过 pr-merged 预检 → exit 0（即使 PR 状态 OPEN）。"""
    _make_meta(fake_repo)
    # gh pr view 不应被调用；放一个会抛错的 stub 验证未被调用
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): RuntimeError("gh pr view 不应被调用"),
        ("git", "branch", "-d"): _ok(),
        ("git", "push", "origin", "--delete"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        force=True,
        no_experience=True,
        keep_branch=True,
    )
    assert result.phase == "completed"
    assert result.archived_at  # 已写时间戳


# ---------- TC-F3-5: 三问全 y ----------


def test_three_prompts_yes_path(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三问全 y → experience=yes / local=deleted / remote=deleted。"""
    req_dir = _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("claude", "/knowledge:extract-experience"): _ok(),
        ("git", "branch", "-d"): _ok(),
        ("git", "push", "origin", "--delete"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    callback_calls: list[ArchivePrompt] = []

    def callback(prompt: ArchivePrompt) -> bool:
        callback_calls.append(prompt)
        return True  # 三问全 y

    result = archive_requirement("REQ-2099-007", prompts_callback=callback)

    assert result.experience == "yes"
    assert result.local_branch == "deleted"
    assert result.remote_branch == "deleted"
    assert result.phase == "completed"
    assert result.archived_at  # 非空
    # 三个 prompt kind 都被问到
    kinds = [p.kind for p in callback_calls]
    assert kinds == ["experience", "local_branch", "remote_branch"]
    # process.txt 写入了 [archived]
    process = (req_dir / "process.txt").read_text(encoding="utf-8")
    assert "[archived]" in process


# ---------- TC-F3-6: 三问全 N ----------


def test_three_prompts_no_path(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三问全 N → outcome=no/kept/kept；meta + process.txt 仍写。"""
    req_dir = _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        # claude / git branch / git push 不会被调用——回答 N 直接跳过
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    def callback(prompt: ArchivePrompt) -> bool:
        return False

    result = archive_requirement("REQ-2099-007", prompts_callback=callback)

    assert result.experience == "no"
    assert result.local_branch == "kept"
    assert result.remote_branch == "kept"
    # meta.yaml 已写 phase=completed + archived_at
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["phase"] == "completed"
    assert meta["archived_at"]
    # process.txt 含 [archived] 一行
    assert "[archived]" in (req_dir / "process.txt").read_text(encoding="utf-8")


def test_archived_event_idempotent(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重跑 archive：process.txt [archived] 行只追加一次（detail-design §4.3 幂等）。"""
    req_dir = _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        keep_branch=True,
    )
    archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        keep_branch=True,
    )
    process = (req_dir / "process.txt").read_text(encoding="utf-8")
    assert process.count("[archived]") == 1


# ---------- TC-F3-7: 副作用降级矩阵 ----------


def test_experience_failure_does_not_break_archive(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """经验沉淀 raise → outcome=failed + archive 仍 exit 0。"""
    _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("claude", "/knowledge:extract-experience"): FileNotFoundError(
            "claude not found"
        ),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        yes_experience=True,
        keep_branch=True,
    )
    assert result.experience == "failed"
    assert any("experience" in m for m in result.error_messages)
    # archive 主流程仍走通
    assert result.phase == "completed"


def test_local_branch_delete_rejected(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """git branch -d 拒绝（squash merge 模拟） → outcome=failed 透传 git error。"""
    _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("git", "branch", "-d"): _ok(
            returncode=1,
            stderr=(
                "error: the branch 'feat/req-2099-007' is not fully merged.\n"
                "If you are sure you want to delete it, run 'git branch -D'.\n"
            ),
        ),
        ("git", "push", "origin", "--delete"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=True,
    )
    assert result.local_branch == "failed"
    # 透传原始 git error
    assert any("not fully merged" in m for m in result.error_messages)
    assert result.remote_branch == "deleted"


def test_remote_branch_already_deleted(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """远程已删（GitHub auto-delete）→ outcome=already-deleted，不报错。"""
    _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("git", "branch", "-d"): _ok(),
        ("git", "push", "origin", "--delete"): _ok(
            returncode=1,
            stderr="error: unable to delete 'feat/req-2099-007': remote ref does not exist\n",
        ),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=True,
    )
    assert result.remote_branch == "already-deleted"
    # 不进 error_messages（已折叠为正常态）
    assert not any("remote_branch" in m for m in result.error_messages)
    assert result.local_branch == "deleted"


# ---------- 额外：base_branch 防误删 ----------


def test_refuse_to_delete_base_branch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """meta.branch == meta.base_branch → 拒绝调 git branch -d，记 failed。"""
    _make_meta(fake_repo, branch="develop", base_branch="develop")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("git", "branch", "-d"): RuntimeError("不应被调用"),
        ("git", "push", "origin", "--delete"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        keep_branch=False,
        yes_remote_branch=False,
    )
    assert result.local_branch == "failed"
    assert any("base_branch" in m for m in result.error_messages)


# ---------- 额外：archived_at 重跑保留旧值 ----------


def test_archived_at_preserved_on_rerun(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重跑时 archived_at 已非空 → 保留旧值（首次归档时间不被覆盖）。"""
    old_ts = "2026-05-04 19:00:00"
    req_dir = _make_meta(
        fake_repo,
        phase="completed",
        archived_at=old_ts,
    )
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        keep_branch=True,
    )
    assert result.archived_at == old_ts
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["archived_at"] == old_ts


# ---------- codex round-2 P2 finding F-5 回归 ----------


def test_archived_event_concurrent_append_is_atomic(fake_repo: Path) -> None:
    """codex F-5 (P2) 回归：两个并发线程同时调 _append_process_event，
    LOCK_EX 必须把 read+append 包成临界区，最终 process.txt 仅含一行 [archived]。

    旧实现非原子（path.exists → read → append 之间有窗口），并发下都能跳过去重；
    新实现用 fcntl.flock 串行化（POSIX 平台），不抛 OSError。
    """
    import threading

    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _worker(pr_num: int) -> None:
        try:
            barrier.wait()  # 强制两线程几乎同时进入临界区
            archive_runner._append_process_event(
                req_id,
                pr_number=pr_num,
                archived_at="2026-05-05 17:30:00",
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_worker, args=(42,))
    t2 = threading.Thread(target=_worker, args=(42,))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, f"并发调用不应抛异常：{errors}"
    process = (fake_repo / req_id / "process.txt").read_text(encoding="utf-8")
    archived_count = process.count("[archived]")
    assert archived_count == 1, (
        f"并发场景仅允许一行 [archived]，实际 {archived_count} 行：\n{process}"
    )


def test_append_process_event_creates_file_when_missing(fake_repo: Path) -> None:
    """codex F-5 修复后必须保留原"文件不存在则创建"语义（'a+' 模式）。"""
    req_id = "REQ-2099-007"
    _make_meta(fake_repo, req_id=req_id)
    process_path = fake_repo / req_id / "process.txt"
    if process_path.exists():
        process_path.unlink()  # 故意删掉，模拟首次写

    archive_runner._append_process_event(
        req_id,
        pr_number=42,
        archived_at="2026-05-05 17:30:00",
    )
    assert process_path.exists()
    assert "[archived]" in process_path.read_text(encoding="utf-8")


# ---------- codex round-3 P2 finding F-7 回归 ----------


def test_local_branch_delete_refused_when_head_on_target(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex F-7 (P2) 回归：HEAD 当前在目标 branch 时，archive 必须先报错让用户切走，
    不应直接跑 `git branch -d` 撞上 'used by worktree'。
    """
    req_dir = _make_meta(fake_repo, branch="feat/req-2099-007", base_branch="develop")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        # 故意命中 _current_branch 的命令，返回与 meta.branch 同名
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): _ok(stdout="feat/req-2099-007\n"),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,    # 显式同意删，但应被前置检测拦下
        keep_branch=False,
    )

    assert result.local_branch == "failed", f"HEAD 在目标分支应失败，实际 {result.local_branch}"
    joined = " | ".join(result.error_messages)
    assert "used by worktree" in joined or "git switch develop" in joined, (
        f"错误文案应提示用户先切 base_branch，实际：{joined}"
    )


def test_local_branch_delete_proceeds_when_head_elsewhere(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex F-7 反向：HEAD 在 develop 时，archive 跑得通（不被前置检测错杀）。"""
    _make_meta(fake_repo, branch="feat/req-2099-007", base_branch="develop")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("git", "rev-parse", "--abbrev-ref", "HEAD"): _ok(stdout="develop\n"),
        ("git", "branch", "-d"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        keep_branch=False,
    )

    assert result.local_branch == "deleted", f"HEAD 在 develop 应正常删除，实际 {result.local_branch}"
