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
    # F-002 引入 _create_archive_pr 后渲染 PR body 需读 archive-pr-body.md.tmpl；
    # 测试 fixture seed 一份占位符模板，避免 archive_requirement 主流程 IOError
    tmpl_dir = tmp_path / ".claude/skills/managing-requirement-lifecycle/templates"
    tmpl_dir.mkdir(parents=True, exist_ok=True)
    (tmpl_dir / "archive-pr-body.md.tmpl").write_text(
        "req=__REQ_ID__ pr=__PR_NUMBER__ branch=__BRANCH__",
        encoding="utf-8",
    )
    return tmp_path


def _make_run_stub(plan: dict[tuple, Any]):
    """构造 archive_runner._run 的替身。

    plan: 形如 {("git", "status", "--porcelain"): SimpleNamespace(returncode=0, stdout="", stderr="")}
    匹配方式：tuple(cmd[: len(key)]) == key（前缀匹配，便于忽略尾部参数差异）。
    未命中默认：F-002 引入的 `gh pr list` 返回空数组、`gh pr create` 返回 stub URL（PR 42）
    避免存量测试因 F-002 自动 PR 创建路径炸开；其他未命中命令默认 returncode=0 / stdout=""。
    """

    def _stub(cmd, *, cwd=None):  # 匹配 archive_runner._run 签名
        for key, result in plan.items():
            if tuple(cmd[: len(key)]) == key:
                if isinstance(result, BaseException):
                    raise result
                return result
        # F-002 引入的命令默认响应（存量测试未在 plan 显式 mock）
        if tuple(cmd[:3]) == ("gh", "pr", "list"):
            return types.SimpleNamespace(returncode=0, stdout="[]\n", stderr="")
        if tuple(cmd[:3]) == ("gh", "pr", "create"):
            return types.SimpleNamespace(
                returncode=0,
                stdout="https://github.com/org/repo/pull/42\n",
                stderr="",
            )
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
    """三问 experience=yes；local/remote 分支操作已搬迁到 finalize_requirement（双阶段架构）。

    F-001/F-002/F-003 落地后 archive 阶段 1 不再调三件套（删本地/远程/worktree），
    local_branch / remote_branch 结果字段固定为 "skipped"；
    prompts_callback 只会被问到 experience（不会被问 local_branch / remote_branch）。
    """
    req_dir = _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        ("claude", "/knowledge:extract-experience"): _ok(),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    callback_calls: list[ArchivePrompt] = []

    def callback(prompt: ArchivePrompt) -> bool:
        callback_calls.append(prompt)
        return True  # experience 答 y

    result = archive_requirement("REQ-2099-007", prompts_callback=callback)

    assert result.experience == "yes"
    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.local_branch == "skipped"
    assert result.remote_branch == "skipped"
    assert result.phase == "completed"
    assert result.archived_at  # 非空
    # 阶段 1 只问 experience，不问 local_branch / remote_branch
    kinds = [p.kind for p in callback_calls]
    assert kinds == ["experience"]
    # process.txt 写入了 [archived]
    process = (req_dir / "process.txt").read_text(encoding="utf-8")
    assert "[archived]" in process


# ---------- TC-F3-6: 三问全 N ----------


def test_three_prompts_no_path(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """experience 答 N；local/remote 分支操作已搬迁到 finalize_requirement（双阶段架构）。

    F-001/F-002/F-003 落地后 archive 阶段 1 不再调三件套；
    experience=no 时 local_branch / remote_branch 固定为 "skipped"。
    meta + process.txt 仍正常写入。
    """
    req_dir = _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
        # claude / git branch / git push 不会被调用——阶段 1 不走三件套
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    def callback(prompt: ArchivePrompt) -> bool:
        return False

    result = archive_requirement("REQ-2099-007", prompts_callback=callback)

    assert result.experience == "no"
    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.local_branch == "skipped"
    assert result.remote_branch == "skipped"
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
    """process.txt [archived] 行只追加一次（detail-design §4.3 幂等）。

    双阶段架构下 _precheck_phase 在 phase=completed + archive_pr_number>0 时拒绝重跑，
    以防止二次归档覆盖数据。幂等性通过 _append_process_event 内部去重机制保证：
    直接调两次 _append_process_event，断言 [archived] 只写一次。
    """
    req_id = "REQ-2099-007"
    req_dir = _make_meta(fake_repo, req_id=req_id)
    archived_at = "2026-05-22 10:00:00"
    pr_number = 42

    archive_runner._append_process_event(req_id, pr_number=pr_number, archived_at=archived_at)
    archive_runner._append_process_event(req_id, pr_number=pr_number, archived_at=archived_at)

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
    """archive 阶段 1 不再调三件套（F-001 双阶段拆分），local_branch 固定为 skipped。

    原测试验证 git branch -d 拒绝时 outcome=failed——该逻辑已搬迁到
    finalize_requirement（test_finalize.py TC-F3-18 覆盖严格模式拒删场景）。
    此处仅断言 archive 阶段 1 的行为：三件套均 skipped。
    """
    _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=True,
    )
    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.local_branch == "skipped"
    assert result.remote_branch == "skipped"


def test_remote_branch_already_deleted(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """archive 阶段 1 不再调三件套（F-001 双阶段拆分），remote_branch 固定为 skipped。

    原测试验证远程已删时 outcome=already-deleted——该逻辑已搬迁到
    finalize_requirement（test_finalize.py TC-F3-17 覆盖远程失败/手工恢复场景）。
    此处仅断言 archive 阶段 1 的行为：三件套均 skipped。
    """
    _make_meta(fake_repo)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=True,
    )
    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.remote_branch == "skipped"
    assert result.local_branch == "skipped"


# ---------- 额外：base_branch 防误删 ----------


def test_refuse_to_delete_base_branch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """archive 阶段 1 不调三件套（F-001 双阶段拆分），local_branch 固定为 skipped。

    原测试验证 branch==base_branch 时拒绝本地删除——该安全检查已搬迁到
    finalize_requirement（_delete_local_branch / _delete_remote_branch 函数
    保留安全分支白名单逻辑，但由 finalize 入口驱动）。
    archive 阶段 1 不调三件套，不触发 _delete_local_branch 路径。

    注：_push_feat_branch 也对受保护分支做 fail-closed，因此此测试使用
    普通 feat branch（branch != base_branch），仅验证三件套 skipped 行为。
    """
    _make_meta(fake_repo, branch="feat/req-2099-007", base_branch="develop")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        keep_branch=False,
        yes_remote_branch=False,
    )
    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.local_branch == "skipped"
    assert result.remote_branch == "skipped"


@pytest.mark.parametrize("protected", ["main", "master", "develop"])
def test_protected_branch_blocked_even_when_base_branch_empty(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected: str,
) -> None:
    """archive 阶段 1 不调三件套（F-001 双阶段拆分），不触发保护分支删除路径。

    原测试验证 base_branch 为空时白名单兜底拦下 main/master/develop 本地+远程删除——
    该安全检查已搬迁到 finalize_requirement（_delete_local_branch / _delete_remote_branch
    保留白名单逻辑，由 finalize 入口驱动）。

    注：archive 阶段 1 的 _push_feat_branch 对受保护分支做 fail-closed（防止推送），
    因此当 branch 为受保护分支名时 archive 本身也会 SystemExit(1)。
    本测试改为验证：archive 阶段 1 对于普通 feat branch 正常完成，三件套均 skipped。
    保护分支白名单在 finalize 层的覆盖见 test_finalize.py。
    """
    # 使用普通 feat branch，避免 _push_feat_branch 因受保护分支白名单 abort
    _make_meta(fake_repo, branch="feat/req-2099-007", base_branch=protected)
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=True,
        keep_branch=False,
    )
    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.local_branch == "skipped", "archive 阶段 1 不调三件套，local_branch 应 skipped"
    assert result.remote_branch == "skipped", "archive 阶段 1 不调三件套，remote_branch 应 skipped"


def test_refuse_to_delete_remote_base_branch(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """archive 阶段 1 不调三件套（F-001 双阶段拆分），remote_branch 固定为 skipped。

    原测试验证 branch==base_branch 时远程删除被拦下（F-8 回归）——该安全检查已搬迁到
    finalize_requirement（_delete_remote_branch 保留对称性安全检查，由 finalize 驱动）。

    注：archive 阶段 1 的 _push_feat_branch 对受保护分支做 fail-closed，
    因此使用普通 feat branch（branch != base_branch），仅验证三件套 skipped 行为。
    """
    _make_meta(fake_repo, branch="feat/req-2099-007", base_branch="develop")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=True,
        keep_branch=False,
    )
    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.remote_branch == "skipped"
    assert result.local_branch == "skipped"


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
    """archive 阶段 1 不调三件套（F-001 双阶段拆分），不调 git switch / git branch -d。

    原测试验证 HEAD 在 feat 分支时 archive 内部自动 switch + delete——该逻辑已搬迁到
    finalize_requirement（_delete_local_branch 保留 auto-switch 行为，由 finalize 驱动）。
    此处仅断言 archive 阶段 1 的行为：git switch / git branch -d 不被调用，local_branch=skipped。
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
        if tuple(cmd[:3]) == ("gh", "pr", "list"):
            return _ok(stdout="[]\n")
        if tuple(cmd[:3]) == ("gh", "pr", "create"):
            return _ok(stdout="https://github.com/org/repo/pull/42\n")
        return _ok()

    monkeypatch.setattr(archive_runner, "_run", _stub)

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=False,
        keep_branch=False,
    )

    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.local_branch == "skipped", (
        f"archive 阶段 1 不调三件套，local_branch 应 skipped，实际 {result.local_branch}"
    )
    # git switch / git branch -d 不应被调用（archive 阶段 1 不走三件套路径）
    assert switch_calls == [], f"archive 阶段 1 不应调 git switch，实际：{switch_calls}"
    assert delete_calls == [], f"archive 阶段 1 不应调 git branch -d，实际：{delete_calls}"


def test_local_branch_delete_fails_when_auto_switch_fails(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """archive 阶段 1 不调三件套（F-001 双阶段拆分），git switch 不被调用。

    原测试验证 auto-switch 失败时 fail-soft——该逻辑已搬迁到 finalize_requirement。
    此处仅断言 archive 阶段 1 的行为：git switch / git branch -d 不被调用，
    local_branch=skipped（与 auto-switch 失败路径无关）。
    """
    _make_meta(fake_repo, branch="feat/req-2099-007", base_branch="develop")

    def _stub(cmd, **kwargs):
        if cmd[:2] == ["git", "switch"]:
            pytest.fail("archive 阶段 1 不应调 git switch")
        if cmd[:3] == ["git", "branch", "-d"]:
            pytest.fail("archive 阶段 1 不应调 git branch -d")
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return _ok()
        if cmd[:3] == ["gh", "pr", "view"]:
            return _ok(stdout=json.dumps({"state": "MERGED"}))
        if tuple(cmd[:3]) == ("gh", "pr", "list"):
            return _ok(stdout="[]\n")
        if tuple(cmd[:3]) == ("gh", "pr", "create"):
            return _ok(stdout="https://github.com/org/repo/pull/42\n")
        return _ok()

    monkeypatch.setattr(archive_runner, "_run", _stub)

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        yes_remote_branch=False,
        keep_branch=False,
    )

    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.local_branch == "skipped", f"archive 阶段 1 不调三件套，实际 {result.local_branch}"


def test_local_branch_delete_proceeds_when_head_elsewhere(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """archive 阶段 1 不调三件套（F-001 双阶段拆分），local_branch 固定为 skipped。

    原测试验证 HEAD 在 develop 时 archive 正常删本地分支（F-7 反向）——该逻辑已搬迁到
    finalize_requirement。此处仅断言 archive 阶段 1 正常完成，local_branch=skipped。
    """
    _make_meta(fake_repo, branch="feat/req-2099-007", base_branch="develop")
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))

    result = archive_requirement(
        "REQ-2099-007",
        no_experience=True,
        yes_local_branch=True,
        keep_branch=False,
    )

    # 阶段 1 archive 不调三件套，local/remote 永远 skipped
    assert result.local_branch == "skipped", f"archive 阶段 1 不调三件套，实际 {result.local_branch}"


# ---------- codex P1 F-1 / F-3 回归：archive from inside linked worktree ----------


def test_archive_from_inside_worktree_writes_to_worktree_meta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worktree-mode hotfix（2026-05-22）：archive 从 linked worktree cwd 启动时，
    bookkeeping 直接写到 **worktree** requirements/<id>/（即 feat 分支当前检出），
    不再 rebind 到主仓后写主仓副本。

    历史：codex P1 F-1 / F-3 的 _rebind_to_main_repo 设计动机是 cleanup_worktree_before_archive
    即将删 worktree → 必须先 chdir 主仓 + 重绑 REPO_ROOT。F-001 双阶段拆分（D-003）
    把 cleanup 搬到 finalize 后，阶段 1 archive 不再触发删 worktree，rebind 失去原本
    动机。worktree-mode hotfix 删除阶段 1 的 rebind 调用 —— 否则主仓 develop checkout
    没含 feat 分支最新 meta，archive 会 R-ARCHIVE-META-MISSING；即使主仓也含 meta
    （git pull develop 后），commit 会落到 develop 分支污染历史。

    断言：archive 完成后，**worktree** 内的 meta.yaml.phase=completed + archived_at
    非空；主仓 meta 保持不变（因为 archive 不再触碰主仓副本）。
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

    # F-002 引入 _create_archive_pr 后渲染 PR body 需读 archive-pr-body.md.tmpl；
    # _render_archive_pr_body 用 REPO_ROOT（rebind 后 = 主仓），必须在主仓 seed 模板
    for root in (main_repo, worktree_root):
        tmpl_dir = root / ".claude/skills/managing-requirement-lifecycle/templates"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "archive-pr-body.md.tmpl").write_text(
            "req=__REQ_ID__ pr=__PR_NUMBER__ branch=__BRANCH__",
            encoding="utf-8",
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

    # 普通 stub：git status clean / PR merged
    # archive 阶段 1 不再调 git branch -d / git push origin --delete（三件套搬迁到 finalize）
    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))
    # archive 完成后会切到 main_repo cwd（cleanup 内 os.chdir）；改回 tmp_path 让后续
    # 测试无副作用
    monkeypatch.chdir(tmp_path)

    result = archive_requirement(req_id, no_experience=True, yes_local_branch=True)

    # —— 断言：bookkeeping 写到 worktree 副本（hotfix 后 archive 不再 rebind 到主仓） ——
    worktree_meta = yaml.safe_load(
        (worktree_root / "requirements" / req_id / "meta.yaml").read_text(encoding="utf-8")
    )
    assert worktree_meta["phase"] == "completed", "worktree meta.yaml.phase 应被更新为 completed"
    assert worktree_meta["archived_at"], "worktree meta.yaml.archived_at 应非空"
    assert worktree_meta["outcome"] == "shipped"

    worktree_process = (worktree_root / "requirements" / req_id / "process.txt").read_text(
        encoding="utf-8"
    )
    assert "[archived]" in worktree_process, "worktree process.txt 应含 [archived] 行"

    # 主仓 meta 应保持原样（archive 不再 rebind 写主仓）
    main_meta = yaml.safe_load(
        (main_repo / "requirements" / req_id / "meta.yaml").read_text(encoding="utf-8")
    )
    assert main_meta["phase"] == "testing", (
        f"主仓 meta 不应被 archive 触碰（hotfix 行为）；实际 phase={main_meta['phase']!r}"
    )

    # F-001 双阶段拆分：archive 阶段 1 不再调 _cleanup_worktree_before_archive；
    # worktree cleanup 已搬迁到 finalize_requirement。worktree 目录在 archive 后仍存在。
    assert worktree_root.exists(), "archive 阶段 1 不调 cleanup，worktree 应仍存在"

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


def test_archive_uses_cwd_meta_not_main_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """worktree-mode hotfix（2026-05-22）：archive 从 worktree cwd 启动时，
    用 worktree 的 meta（feat 分支视角）而非主仓 develop 的 meta。

    历史：codex P1 round-4 F-5 曾设计「rebind 后从主仓加载 meta」防止 worktree
    stale 覆盖主仓。但实际工作流下该场景不会发生 —— worktree 是 feat 分支唯一
    检出，用户在 worktree 编辑 meta；主仓 develop 上的 meta 仅来自 squash-merge 后
    的「冻结状态」，永远落后于 worktree 的 feat 视角。worktree-mode hotfix 删除
    阶段 1 rebind，让 cwd 成为权威 —— archive 必须在 feat 分支视角操作 commit/push。

    场景：worktree meta（phase=testing，feat 视角的最新状态）vs 主仓 meta
    （phase=testing 但 title 不同，模拟 develop 落后视角）。
    - hotfix 前：rebind 后读主仓 meta → final title=主仓 value
    - hotfix 后：不 rebind → 读 worktree meta → final title=worktree value（且 archive 写到 worktree）
    """
    main_repo = tmp_path / "main_repo"
    worktree_root = main_repo / ".worktrees" / "wt"
    req_id = "REQ-2099-W03"

    main_req_dir = main_repo / "requirements" / req_id
    main_req_dir.mkdir(parents=True)
    main_meta = {
        "id": req_id,
        "title": "MAIN repo view (develop)",  # ← 主仓 develop 视角
        "phase": "testing",
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
    wt_meta = dict(main_meta)
    wt_meta["title"] = "WORKTREE view (feat - canonical)"  # ← worktree 是 feat 视角权威
    with (wt_req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(wt_meta, f, allow_unicode=True, sort_keys=False)
    (wt_req_dir / "process.txt").write_text(
        "2026-05-04 19:00:00 [phase-transition] bootstrap → testing\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(archive_runner, "REPO_ROOT", worktree_root)
    monkeypatch.setattr(
        archive_runner, "REQUIREMENTS_DIR", worktree_root / "requirements"
    )

    for root in (main_repo, worktree_root):
        tmpl_dir = root / ".claude/skills/managing-requirement-lifecycle/templates"
        tmpl_dir.mkdir(parents=True, exist_ok=True)
        (tmpl_dir / "archive-pr-body.md.tmpl").write_text(
            "req=__REQ_ID__ pr=__PR_NUMBER__ branch=__BRANCH__",
            encoding="utf-8",
        )

    fake_worktree_manager = sys.modules["worktree_manager"]
    monkeypatch.setattr(
        fake_worktree_manager, "resolve_main_repo_root", lambda _cwd: main_repo
    )

    plan = {
        ("git", "status", "--porcelain"): _ok(),
        ("gh", "pr", "view"): _ok(stdout=json.dumps({"state": "MERGED"})),
    }
    monkeypatch.setattr(archive_runner, "_run", _make_run_stub(plan))
    monkeypatch.chdir(worktree_root)

    result = archive_requirement(req_id, no_experience=True, yes_local_branch=True)
    assert result.phase == "completed"

    # —— 断言：worktree meta 被写为 completed，title 保留 WORKTREE 值 ——
    wt_final = yaml.safe_load(
        (worktree_root / "requirements" / req_id / "meta.yaml").read_text(encoding="utf-8")
    )
    assert wt_final["title"] == "WORKTREE view (feat - canonical)", (
        f"hotfix 后 archive 应读 worktree meta；实际 title={wt_final['title']!r}"
    )
    assert wt_final["phase"] == "completed"

    # —— 主仓 meta 未被触碰 ——
    main_final = yaml.safe_load(
        (main_repo / "requirements" / req_id / "meta.yaml").read_text(encoding="utf-8")
    )
    assert main_final["title"] == "MAIN repo view (develop)", "主仓 meta 不应被 archive 触碰"
    assert main_final["phase"] == "testing", "主仓 meta.phase 应保持 testing"


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
