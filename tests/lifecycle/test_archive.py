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
import shutil
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
    lessons_extracted: bool = True,
) -> Path:
    """构造临时 requirements/<req>/meta.yaml；返回 req 目录路径。

    lessons_extracted 默认 True：archive 预检 5（R-ARCHIVE-LESSONS-NOT-EXTRACTED）
    要求该字段为 True 才能继续，绝大多数 fixture 走"已沉淀"路径。需测预检 5
    失败行为时显式传 False。
    """
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
        "lessons_extracted": lessons_extracted,
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

    codex P1 F-1 / F-3 修复后 archive_requirement 入口会调 `_rebind_to_main_repo`
    重新 resolve 主仓——若不 stub `resolve_main_repo_root`，会覆盖本 fixture 的
    monkeypatch 跳回真实仓库根。这里 stub 它直接返 tmp_path（既符合"主仓 = 测试
    fixture root"的测试语义，又不破坏 rebind 逻辑本身的覆盖）。
    """
    monkeypatch.setattr(archive_runner, "REQUIREMENTS_DIR", tmp_path)
    monkeypatch.setattr(archive_runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sys.modules["worktree_manager"],
        "resolve_main_repo_root",
        lambda _cwd: tmp_path,
    )
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


# ---------- 新预检 5: lessons_extracted ----------


def test_precheck_lessons_not_extracted_blocks(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """lessons_extracted=False → exit 1 + stderr 含 R-ARCHIVE-LESSONS-NOT-EXTRACTED。

    用户反馈 2026-05-07：归档时强制要求经验已沉淀；--force 不豁免。
    """
    _make_meta(fake_repo, lessons_extracted=False)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        archive_requirement("REQ-2099-007")
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "R-ARCHIVE-LESSONS-NOT-EXTRACTED" in err
    assert "/knowledge:extract-experience" in err
    assert "mark_lessons_extracted" in err


def test_precheck_lessons_not_extracted_force_does_not_bypass(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """--force 仅豁免预检 4 (PR-merged)，不豁免预检 5 (lessons_extracted)。"""
    _make_meta(fake_repo, lessons_extracted=False)
    plan = {("git", "status", "--porcelain"): _ok()}
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        archive_requirement("REQ-2099-007", force=True)
    assert excinfo.value.code == 1
    assert "R-ARCHIVE-LESSONS-NOT-EXTRACTED" in capsys.readouterr().err


def test_precheck_lessons_extracted_missing_field_treated_as_false(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """meta.yaml 完全缺 lessons_extracted 字段 → 视同 False，预检 5 fail。"""
    req_dir = _make_meta(fake_repo, lessons_extracted=True)
    # 手工把 lessons_extracted 字段从 yaml 里删掉
    meta_path = req_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text())
    del meta["lessons_extracted"]
    meta_path.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False))

    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    with pytest.raises(SystemExit) as excinfo:
        archive_requirement("REQ-2099-007")
    assert excinfo.value.code == 1
    assert "R-ARCHIVE-LESSONS-NOT-EXTRACTED" in capsys.readouterr().err


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
    # 三个 prompt kind 都被问到（2026-05-12 spec 修订：先远程后本地，让本地删成为
    # archive 的最后一步——本地删需要先 git switch 切走 feat，放最后才能让前面所有
    # bookkeeping 操作都在 feat 分支完成）
    kinds = [p.kind for p in callback_calls]
    assert kinds == ["experience", "remote_branch", "local_branch"]
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


@pytest.mark.parametrize("protected", ["main", "master", "develop"])
def test_protected_branch_blocked_even_when_base_branch_empty(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected: str,
) -> None:
    """codex F-10 (P1) 回归：base_branch 为空 / 漂移时，本地+远程删除仍要拦下
    main/master/develop 等保护分支——白名单兜底，不依赖 base_branch 配置正确。
    """
    _make_meta(fake_repo, branch=protected, base_branch="")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("git", "branch", "-d"): RuntimeError("不应被调用——保护分支白名单必须拦下"),
        ("git", "push", "origin", "--delete"): RuntimeError("不应被调用——远程保护分支白名单必须拦下"),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=True,
        keep_branch=False,
    )
    assert result.local_branch == "failed", f"{protected} 本地保护应失败"
    assert result.remote_branch == "failed", f"{protected} 远程保护应失败"
    joined = " | ".join(result.error_messages)
    assert "受保护" in joined or "protected" in joined.lower(), (
        f"错误文案应说明保护语义，实际：{joined}"
    )


def test_refuse_to_delete_remote_base_branch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex F-8 (P1) 回归：远程删除路径必须与本地对称——meta.branch == base_branch
    且用户显式 yes_remote_branch=True 时，仍拒绝调 `git push origin --delete`。
    """
    _make_meta(fake_repo, branch="develop", base_branch="develop")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("git", "branch", "-d"): RuntimeError("不应被调用"),
        # 关键：本测试断言这条命令不应被调用；命中即测试失败
        ("git", "push", "origin", "--delete"): RuntimeError(
            "不应被调用——base_branch 远程引用必须 fail-closed 拦下"
        ),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=True,    # 显式同意删远程，仍应被前置检测拦下
        keep_branch=False,
    )
    assert result.remote_branch == "failed", f"远程 base_branch 删除应失败，实际 {result.remote_branch}"
    joined = " | ".join(result.error_messages)
    assert "base_branch" in joined, f"错误文案应含 base_branch，实际：{joined}"


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


# ---------- F-17（CI gate fail）：archive 必须写 outcome + completed_at ----------


def test_archive_writes_outcome_and_completed_at(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-17 回归：phase=completed 时 GATE-META-SCHEMA conditional_required 强校验
    outcome / completed_at 非空，archive 必须同时写这两个字段。
    """
    req_dir = _make_meta(fake_repo)
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
    meta = yaml.safe_load((req_dir / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["outcome"] == "shipped", f"默认 outcome 应为 shipped，实际 {meta.get('outcome')!r}"
    assert meta["completed_at"], f"completed_at 必须非空，实际 {meta.get('completed_at')!r}"
    # 同一动作内 archive 与 phase 转 completed 同时发生 → completed_at == archived_at
    assert meta["completed_at"] == result.archived_at, (
        f"completed_at({meta['completed_at']}) 应等于 archived_at({result.archived_at})"
    )


def test_archive_outcome_override_via_kwarg(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-17：--outcome 可覆盖默认 shipped（--force 路径下场景）。"""
    _make_meta(fake_repo, phase="testing")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        keep_branch=True,
        outcome="abandoned",
    )
    meta = yaml.safe_load((fake_repo / "REQ-2099-007" / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["outcome"] == "abandoned"


def test_archive_outcome_invalid_value_aborts(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-17：非法 outcome 值（不在 schema enum 内）应在 archive 入口前 abort。"""
    _make_meta(fake_repo)

    with pytest.raises(SystemExit) as exc:
        archive_requirement(
            "REQ-2099-007",
            no_experience=True,
            keep_branch=True,
            outcome="invalid-value",
        )
    assert exc.value.code == 1


def test_archive_preserves_existing_outcome_and_completed_at(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-17：重跑场景下 outcome / completed_at 已非空时保留旧值（首次结论不被覆盖）。"""
    req_dir = _make_meta(
        fake_repo,
        phase="completed",
        archived_at="2026-05-04 19:00:00",
    )
    # 手工写入历史 outcome / completed_at（模拟某个外部流程已经设过）
    meta_path = req_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["outcome"] = "rolled-back"
    meta["completed_at"] = "2026-05-03 18:00:00"
    meta_path.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")

    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        keep_branch=True,
        outcome="shipped",  # 即便传入 shipped，也不该覆盖既有 rolled-back
    )

    meta_after = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    assert meta_after["outcome"] == "rolled-back", "重跑不该覆盖既有 outcome"
    assert meta_after["completed_at"] == "2026-05-03 18:00:00", "重跑不该覆盖既有 completed_at"


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


def test_local_branch_delete_auto_switches_when_head_on_target(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-05-12 spec 修订：HEAD 当前在目标 branch 时，archive_runner 应内部自动跑
    `git switch <base_branch>` 然后 `git branch -d <feat>`，用户不需要分两次跑命令。

    旧行为（codex F-7）：报错让用户手动切走 + 重跑 archive；
    新行为：所有 archive bookkeeping 操作在 feat 分支完成 + 删本地分支自动切走作为最后一步。
    """
    _make_meta(fake_repo, branch="feat/req-2099-007", base_branch="develop")
    switch_calls: list[tuple] = []
    delete_calls: list[tuple] = []

    def _stub(cmd, **kwargs):
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return _ok(stdout="feat/req-2099-007\n")
        if cmd[:2] == ["git", "switch"]:
            switch_calls.append(tuple(cmd))
            return _ok()
        if cmd[:3] == ["git", "branch", "-d"]:
            delete_calls.append(tuple(cmd))
            return _ok()
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return _ok()
        if cmd[:3] == ["gh", "pr", "view"]:
            return _ok(stdout=json.dumps({"state": "MERGED"}))
        return _ok()

    monkeypatch.setattr(archive_runner, "_run", _stub)

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=False,
        keep_branch=False,
    )

    assert result.local_branch == "deleted", (
        f"HEAD 在目标分支时 archive_runner 应自动切 base 后删，实际 outcome={result.local_branch}"
    )
    # 自动切 base 被调用且参数正确
    assert switch_calls == [("git", "switch", "develop")], (
        f"应自动跑 `git switch develop`，实际：{switch_calls}"
    )
    # 删除命令最后被调用
    assert delete_calls == [("git", "branch", "-d", "feat/req-2099-007")], (
        f"应跑 `git branch -d feat/req-2099-007`，实际：{delete_calls}"
    )


def test_local_branch_delete_fails_when_auto_switch_fails(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-05-12 spec 修订：自动 `git switch <base>` 失败（base 缺失 / detached 等）时
    fail-soft，outcome=failed，archive 仍 exit 0；**不**自动 `-D` 强删。
    """
    _make_meta(fake_repo, branch="feat/req-2099-007", base_branch="develop")

    def _stub(cmd, **kwargs):
        if cmd[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return _ok(stdout="feat/req-2099-007\n")
        if cmd[:2] == ["git", "switch"]:
            # 模拟 base_branch 本地缺失
            return _ok(returncode=1, stderr="fatal: invalid reference: develop\n")
        if cmd[:3] == ["git", "branch", "-d"]:
            pytest.fail("auto-switch 失败时不应继续调 `git branch -d`")
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return _ok()
        if cmd[:3] == ["gh", "pr", "view"]:
            return _ok(stdout=json.dumps({"state": "MERGED"}))
        return _ok()

    monkeypatch.setattr(archive_runner, "_run", _stub)

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=False,
        keep_branch=False,
    )

    assert result.local_branch == "failed", f"自动切失败应 outcome=failed，实际 {result.local_branch}"
    joined = " | ".join(result.error_messages)
    assert "invalid reference" in joined or "自动切" in joined, (
        f"错误消息应包含自动切失败原因，实际：{joined}"
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


# ---------- codex P1 F-1 / F-3 回归：archive from inside linked worktree ----------


def test_archive_from_inside_worktree_writes_bookkeeping_to_main_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex P1 F-1 / F-3 回归：archive 从 linked worktree 内启动时，bookkeeping
    必须写到主仓 requirements/<id>/ 而非被删的 worktree 副本。

    场景：
      1. 主仓 main_repo/ + worktree main_repo/.worktrees/wt/ 并存
      2. F-004 改造后 bootstrap 把 requirements/<id>/ 写在 worktree 内；PR merged 后
         主仓 develop 也含相同副本（git pull 同步）
      3. archive 从 worktree cwd 启动 → Python import scripts.lib.archive_runner 时
         __file__ 指向 worktree 内副本 → module-level REPO_ROOT/REQUIREMENTS_DIR 锁
         向 worktree
      4. _cleanup_worktree_before_archive 删 worktree → 后续 _atomic_write_meta /
         _append_process_event 仍按 worktree 副本路径解析，写入失败 / 写到已删路径

    断言：archive 完成后，**主仓**的 meta.yaml.phase=completed + archived_at 非空，
    **主仓**的 process.txt 含 `[archived]` 行。
    """
    main_repo = tmp_path / "main_repo"
    worktree_root = main_repo / ".worktrees" / "wt"
    req_id = "REQ-2099-W01"

    # 主仓与 worktree 各自创建 requirements/<req_id>/
    for root in (main_repo, worktree_root):
        req_dir = root / "requirements" / req_id
        req_dir.mkdir(parents=True)
        meta = {
            "id": req_id,
            "title": "测试需求 worktree-archive",
            "phase": "testing",
            "branch": "feat/req-2099-w01",
            "base_branch": "develop",
            "pr_number": 42,
            "archived_at": "",
            "created_at": "2026-05-04 19:00:00",
            "project": "agentic-meta-engineering",
            "lessons_extracted": True,
            "worktree": {
                "owner": "workflow",
                "path": ".worktrees/wt",
                "location": ".worktrees",
            },
        }
        with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
        (req_dir / "process.txt").write_text(
            "2026-05-04 19:00:00 [phase-transition] bootstrap → testing\n",
            encoding="utf-8",
        )

    # 模拟「从 worktree import archive_runner」：module-level 常量指向 worktree
    monkeypatch.setattr(archive_runner, "REPO_ROOT", worktree_root)
    monkeypatch.setattr(
        archive_runner, "REQUIREMENTS_DIR", worktree_root / "requirements"
    )

    # mock worktree_manager 的两个入口：resolve 返主仓；cleanup 实际删 worktree 树
    fake_worktree_manager = sys.modules["worktree_manager"]

    def fake_resolve(_cwd: Path) -> Path:
        return main_repo

    def fake_cleanup(_meta: dict, _main_root: Path):
        shutil.rmtree(worktree_root)
        from worktree_manager import CleanupResult

        return CleanupResult(
            action="removed",
            reason="workflow_ok",
            removed_path=worktree_root,
        )

    monkeypatch.setattr(fake_worktree_manager, "resolve_main_repo_root", fake_resolve)
    monkeypatch.setattr(
        fake_worktree_manager, "cleanup_worktree_if_owned", fake_cleanup
    )

    # 普通 stub：git status clean / PR merged / branch 删除均成功
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("git", "branch", "-d"): _ok(),
        ("git", "push", "origin", "--delete"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))
    # archive 完成后会切到 main_repo cwd（cleanup 内 os.chdir）；改回 tmp_path 让后续
    # 测试无副作用
    monkeypatch.chdir(tmp_path)

    result = archive_requirement(req_id, no_experience=True, yes_local_branch=True)

    # —— 断言：bookkeeping 写到主仓副本，而非已删的 worktree ——
    main_meta = yaml.safe_load(
        (main_repo / "requirements" / req_id / "meta.yaml").read_text(encoding="utf-8")
    )
    assert main_meta["phase"] == "completed", "主仓 meta.yaml.phase 应被更新为 completed"
    assert main_meta["archived_at"], "主仓 meta.yaml.archived_at 应非空"
    assert main_meta["outcome"] == "shipped"

    main_process = (main_repo / "requirements" / req_id / "process.txt").read_text(
        encoding="utf-8"
    )
    assert "[archived]" in main_process, "主仓 process.txt 应含 [archived] 行"

    # worktree 副本已被 cleanup 删除
    assert not worktree_root.exists(), "worktree 应被 cleanup 删除"

    assert result.phase == "completed"
    assert result.archived_at


def test_archive_dirty_worktree_fails_before_rebind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex P1 round-3 F-4 回归：从 dirty linked worktree 启动 archive 时，
    _precheck_dirty 必须在 _rebind_to_main_repo 之前跑——否则 rebind 把
    REPO_ROOT 切到 clean 主仓，dirty 检查误判通过 → cleanup 失败仅 log warning
    不阻塞 → meta.yaml 被 mark completed 但 worktree 残留 uncommitted 改动。

    设计：worktree git status 返非空（dirty），主仓 git status 返空（clean）。
    预期：archive 在 _precheck_dirty 阶段 SystemExit(1)，绝不进入 cleanup /
    bookkeeping；主仓 meta.yaml 保持 phase=testing 不变。
    """
    main_repo = tmp_path / "main_repo"
    worktree_root = main_repo / ".worktrees" / "wt"
    req_id = "REQ-2099-W02"

    for root in (main_repo, worktree_root):
        req_dir = root / "requirements" / req_id
        req_dir.mkdir(parents=True)
        meta = {
            "id": req_id,
            "title": "dirty worktree archive test",
            "phase": "testing",
            "branch": "feat/req-2099-w02",
            "base_branch": "develop",
            "pr_number": 42,
            "archived_at": "",
            "created_at": "2026-05-04 19:00:00",
            "project": "agentic-meta-engineering",
            "lessons_extracted": True,
            "worktree": {
                "owner": "workflow",
                "path": ".worktrees/wt",
                "location": ".worktrees",
            },
        }
        with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
        (req_dir / "process.txt").write_text(
            "2026-05-04 19:00:00 [phase-transition] bootstrap → testing\n",
            encoding="utf-8",
        )

    # archive_runner 启动状态：REPO_ROOT 锁向 worktree（模拟从 worktree import）
    monkeypatch.setattr(archive_runner, "REPO_ROOT", worktree_root)
    monkeypatch.setattr(
        archive_runner, "REQUIREMENTS_DIR", worktree_root / "requirements"
    )

    fake_worktree_manager = sys.modules["worktree_manager"]
    monkeypatch.setattr(
        fake_worktree_manager,
        "resolve_main_repo_root",
        lambda _cwd: main_repo,
    )

    # _run stub: 用 cwd 路径区分两个仓库的 git status 结果
    captured_cwds: list[Path | None] = []

    def cwd_aware_run(cmd, *, cwd=None):
        captured_cwds.append(cwd)
        if tuple(cmd[:3]) == ("git", "status", "--porcelain"):
            stdout = " M some_file.py\n" if cwd == worktree_root else ""
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", cwd_aware_run)
    monkeypatch.chdir(worktree_root)

    with pytest.raises(SystemExit) as exc_info:
        archive_requirement(req_id, no_experience=True, yes_local_branch=True)
    assert exc_info.value.code == 1, "dirty worktree archive 应 SystemExit(1)"

    # git status 应在 worktree cwd（rebind 前）跑过
    assert worktree_root in captured_cwds, (
        f"_precheck_dirty 应在 worktree cwd 跑 git status，实际 cwds={captured_cwds!r}"
    )

    # 主仓 meta.yaml 未被 mark completed
    main_meta = yaml.safe_load(
        (main_repo / "requirements" / req_id / "meta.yaml").read_text(encoding="utf-8")
    )
    assert main_meta["phase"] == "testing", "dirty fail-fast 后主仓 meta 不应被 mutate"
    assert main_meta["archived_at"] == "", "dirty fail-fast 后 archived_at 应保持空"

    # worktree 副本仍存在（没进 cleanup）
    assert worktree_root.exists(), "dirty fail-fast 后 worktree 不应被删"


def test_archive_loads_meta_from_main_repo_after_rebind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex P1 round-4 F-5 回归：archive 从 linked worktree 启动时，meta 必须在
    rebind 之后从主仓加载，避免 stale worktree 副本覆盖主仓较新 metadata。

    场景：主仓 meta（phase=testing / lessons_extracted=true）vs worktree meta
    （phase=development / lessons_extracted=false，stale）。
    - 如用 worktree meta：_precheck_phase 抛 R-ARCHIVE-PHASE 拒绝（development 不允许 archive）
    - 如用主仓 meta（修复后）：phase=testing 通过 → archive 成功

    断言：archive 成功完成；主仓 meta.yaml.phase=completed，且仍含主仓原本的
    title（"MAIN")，证明 archive 走的是主仓 meta dict 而非 worktree 副本。
    """
    main_repo = tmp_path / "main_repo"
    worktree_root = main_repo / ".worktrees" / "wt"
    req_id = "REQ-2099-W03"

    main_req_dir = main_repo / "requirements" / req_id
    main_req_dir.mkdir(parents=True)
    main_meta = {
        "id": req_id,
        "title": "MAIN canonical",  # ← 主仓权威值
        "phase": "testing",         # ← 主仓允许 archive
        "branch": "feat/req-2099-w03",
        "base_branch": "develop",
        "pr_number": 42,
        "archived_at": "",
        "created_at": "2026-05-04 19:00:00",
        "project": "agentic-meta-engineering",
        "lessons_extracted": True,
        "worktree": {
            "owner": "workflow",
            "path": ".worktrees/wt",
            "location": ".worktrees",
        },
    }
    with (main_req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(main_meta, f, allow_unicode=True, sort_keys=False)
    (main_req_dir / "process.txt").write_text(
        "2026-05-04 19:00:00 [phase-transition] bootstrap → testing\n",
        encoding="utf-8",
    )

    wt_req_dir = worktree_root / "requirements" / req_id
    wt_req_dir.mkdir(parents=True)
    stale_meta = dict(main_meta)
    stale_meta["title"] = "WORKTREE stale"
    stale_meta["phase"] = "development"  # ← stale，会被 _precheck_phase 拒绝
    stale_meta["lessons_extracted"] = False
    with (wt_req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(stale_meta, f, allow_unicode=True, sort_keys=False)
    (wt_req_dir / "process.txt").write_text(
        "2026-05-04 19:00:00 [phase-transition] bootstrap → development\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(archive_runner, "REPO_ROOT", worktree_root)
    monkeypatch.setattr(
        archive_runner, "REQUIREMENTS_DIR", worktree_root / "requirements"
    )

    fake_worktree_manager = sys.modules["worktree_manager"]
    monkeypatch.setattr(
        fake_worktree_manager, "resolve_main_repo_root", lambda _cwd: main_repo
    )

    def fake_cleanup(_meta: dict, _main_root: Path):
        shutil.rmtree(worktree_root)
        from worktree_manager import CleanupResult

        return CleanupResult(
            action="removed", reason="workflow_ok", removed_path=worktree_root
        )

    monkeypatch.setattr(
        fake_worktree_manager, "cleanup_worktree_if_owned", fake_cleanup
    )

    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("git", "branch", "-d"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))
    monkeypatch.chdir(worktree_root)

    # 用主仓 meta（testing）走通；用 worktree meta（development）会 SystemExit
    result = archive_requirement(req_id, no_experience=True, yes_local_branch=True)
    assert result.phase == "completed"

    # 主仓 meta 应保留 "MAIN canonical" title，证明 archive 用主仓 meta dict
    final_meta = yaml.safe_load(
        (main_repo / "requirements" / req_id / "meta.yaml").read_text(encoding="utf-8")
    )
    assert final_meta["title"] == "MAIN canonical", (
        "archive 应使用主仓 meta dict 写回，title 不应被 worktree stale 覆盖；"
        f"实际 title={final_meta['title']!r}"
    )
    assert final_meta["phase"] == "completed"
    assert final_meta["lessons_extracted"] is True  # 主仓权威值，非 worktree 的 False


def test_archive_from_main_repo_dirty_worktree_fails_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codex P1 round-5 F-6 回归（F-4 对称场景）：archive 从**主仓** cwd 启动，
    但 meta.worktree.owner=workflow 且 worktree path 下有 uncommitted 改动时，
    _precheck_dirty 必须检查 worktree path（而非仅主仓）→ fail-fast。

    旧实现：REPO_ROOT 已经 = 主仓 → git status cwd=主仓 clean → 通过 → cleanup
    `git worktree remove` 因 worktree dirty 失败但 fail-soft → meta 仍被 mark
    completed，状态不一致。
    """
    main_repo = tmp_path / "main_repo"
    worktree_root = main_repo / ".worktrees" / "wt"
    req_id = "REQ-2099-W04"

    main_req_dir = main_repo / "requirements" / req_id
    main_req_dir.mkdir(parents=True)
    meta = {
        "id": req_id,
        "title": "from main repo dirty wt",
        "phase": "testing",
        "branch": "feat/req-2099-w04",
        "base_branch": "develop",
        "pr_number": 42,
        "archived_at": "",
        "created_at": "2026-05-04 19:00:00",
        "project": "agentic-meta-engineering",
        "lessons_extracted": True,
        "worktree": {
            "owner": "workflow",
            "path": ".worktrees/wt",
            "location": ".worktrees",
        },
    }
    with (main_req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    (main_req_dir / "process.txt").write_text(
        "2026-05-04 19:00:00 [phase-transition] bootstrap → testing\n",
        encoding="utf-8",
    )
    # 主仓 worktree 路径必须存在，否则 _precheck_dirty 会跳过检查
    worktree_root.mkdir(parents=True)

    # 从主仓启动：REPO_ROOT = 主仓
    monkeypatch.setattr(archive_runner, "REPO_ROOT", main_repo)
    monkeypatch.setattr(
        archive_runner, "REQUIREMENTS_DIR", main_repo / "requirements"
    )

    fake_worktree_manager = sys.modules["worktree_manager"]
    # 从主仓启动时 resolve_main_repo_root 应返主仓本身（同当前 REPO_ROOT）
    monkeypatch.setattr(
        fake_worktree_manager, "resolve_main_repo_root", lambda _cwd: main_repo
    )

    # _run stub：主仓 git status 干净；worktree git status 报 dirty
    def cwd_aware_run(cmd, *, cwd=None):
        if tuple(cmd[:3]) == ("git", "status", "--porcelain"):
            cwd_resolved = Path(cwd).resolve() if cwd else None
            wt_resolved = worktree_root.resolve()
            stdout = " M dirty_file.py\n" if cwd_resolved == wt_resolved else ""
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(archive_runner, "_run", cwd_aware_run)
    monkeypatch.chdir(main_repo)

    with pytest.raises(SystemExit) as exc_info:
        archive_requirement(req_id, no_experience=True, yes_local_branch=True)
    assert exc_info.value.code == 1, "F-6: dirty worktree 应 fail-fast"

    # 主仓 meta 未被 mark completed
    final_meta = yaml.safe_load(
        (main_req_dir / "meta.yaml").read_text(encoding="utf-8")
    )
    assert final_meta["phase"] == "testing", (
        f"dirty fail-fast 后主仓 meta 不应被 mutate; 实际 phase={final_meta['phase']!r}"
    )
    assert final_meta["archived_at"] == ""

    # worktree 目录仍存在（cleanup 没跑）
    assert worktree_root.exists()
