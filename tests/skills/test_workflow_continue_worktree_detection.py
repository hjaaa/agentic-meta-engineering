"""Bug-1 修复单测：/workflow:continue 在非 feat/req-* 分支时识别活跃 worktree。

覆盖范围：

  TC-WT-1  `_find_active_worktrees`：porcelain 输出解析（含主仓 develop + 1 个 feat/req-* worktree）
           → 只返回 feat/req-* 那条，run_id 正确从 branch 剥前缀
  TC-WT-2  `_find_active_worktrees`：多个 feat/req-* worktree 全部返回
  TC-WT-3  `_find_active_worktrees`：git 命令失败 → 空列表（fail-open）
  TC-WT-4  `_find_active_worktrees`：git 返回但非零退码 → 空列表
  TC-WT-5  `_find_active_worktrees`：blocks 含 detached HEAD（无 branch 行）→ 跳过
  TC-WT-6  `main` 0 worktree：维持原 ERROR 退码 1
  TC-WT-7  `main` 1 worktree：调 `_switch_to_worktree_and_exec`（被 mock）
  TC-WT-8  `main` 多 worktree：调 `_print_multiple_worktrees`，退码 2

外部依赖（subprocess / os.chdir / os.execv）全部 monkeypatch，不动真实 git 仓 / 文件系统。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import workflow_continue as wc  # noqa: E402


# ============================================================================
# Fixture：构造 porcelain 输出
# ============================================================================


def _make_porcelain(*entries: tuple[str, str | None]) -> str:
    """造一段 git worktree list --porcelain 输出。

    Args:
        entries: 每条 (path, branch)。branch=None 表示 detached HEAD（不写 branch 行）。
    """
    blocks: list[str] = []
    for path, branch in entries:
        lines = [
            f"worktree {path}",
            "HEAD 0000000000000000000000000000000000000000",
        ]
        if branch is None:
            lines.append("detached")
        else:
            lines.append(f"branch refs/heads/{branch}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _stub_subprocess_run(stdout: str, returncode: int = 0):
    """返回一个能塞给 monkeypatch 的 subprocess.run stub。"""
    def _run(*args, **kwargs):  # noqa: ANN002, ANN003
        result = MagicMock()
        result.stdout = stdout
        result.returncode = returncode
        return result
    return _run


# ============================================================================
# TC-WT-1 · 解析：主仓 develop + 1 个 feat/req-* worktree
# ============================================================================


def test_find_active_worktrees_returns_only_feat_req_branches(monkeypatch, tmp_path):
    """porcelain 含 develop + feat/req-*；只返回 feat/req-* 那条，run_id 去前缀。"""
    porcelain = _make_porcelain(
        (str(tmp_path), "develop"),
        (str(tmp_path / ".worktrees" / "feat-req-20260519-foo"),
         "feat/req-20260519-foo"),
    )
    monkeypatch.setattr(subprocess, "run", _stub_subprocess_run(porcelain))

    result = wc._find_active_worktrees(tmp_path)

    assert len(result) == 1
    assert result[0]["run_id"] == "20260519-foo"
    assert result[0]["branch"] == "feat/req-20260519-foo"
    assert result[0]["path"] == Path(str(tmp_path / ".worktrees" / "feat-req-20260519-foo"))


# ============================================================================
# TC-WT-2 · 解析：多个 feat/req-* worktree
# ============================================================================


def test_find_active_worktrees_returns_multiple_feat_req(monkeypatch, tmp_path):
    """多个 feat/req-* worktree 全部返回（让 main 列出供选）。"""
    porcelain = _make_porcelain(
        (str(tmp_path), "develop"),
        (str(tmp_path / "wt-a"), "feat/req-20260519-foo"),
        (str(tmp_path / "wt-b"), "feat/req-REQ-2026-014"),
    )
    monkeypatch.setattr(subprocess, "run", _stub_subprocess_run(porcelain))

    result = wc._find_active_worktrees(tmp_path)

    run_ids = sorted(wt["run_id"] for wt in result)
    assert run_ids == ["20260519-foo", "REQ-2026-014"]


# ============================================================================
# TC-WT-3 · 容错：git 命令抛 OSError → 空列表
# ============================================================================


def test_find_active_worktrees_returns_empty_when_subprocess_raises(monkeypatch, tmp_path):
    """git binary 不存在 / 权限拒绝时 subprocess 抛 OSError → 空列表 fail-open。"""
    def _raise(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("git not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert wc._find_active_worktrees(tmp_path) == []


# ============================================================================
# TC-WT-4 · 容错：git returncode 非 0 → 空列表
# ============================================================================


def test_find_active_worktrees_returns_empty_when_git_nonzero_exit(monkeypatch, tmp_path):
    """git worktree list 非零退码（例如 cwd 不是 git 仓库）→ 空列表。"""
    monkeypatch.setattr(
        subprocess, "run",
        _stub_subprocess_run("fatal: not a git repository\n", returncode=128),
    )
    assert wc._find_active_worktrees(tmp_path) == []


# ============================================================================
# TC-WT-5 · 解析：detached HEAD（无 branch 行）→ 跳过
# ============================================================================


def test_find_active_worktrees_skips_detached_head(monkeypatch, tmp_path):
    """detached HEAD 块没有 `branch refs/heads/...` 行 → 跳过不报错。"""
    porcelain = _make_porcelain(
        (str(tmp_path), None),  # detached
        (str(tmp_path / "wt-a"), "feat/req-20260519-foo"),
    )
    monkeypatch.setattr(subprocess, "run", _stub_subprocess_run(porcelain))

    result = wc._find_active_worktrees(tmp_path)
    assert len(result) == 1
    assert result[0]["run_id"] == "20260519-foo"


# ============================================================================
# TC-WT-6 · main · 0 个 worktree：维持原 ERROR
# ============================================================================


def test_main_zero_worktrees_returns_one_with_original_error(monkeypatch, tmp_path, capsys):
    """无 feat/req-* worktree（仅 develop）→ exit 1，stderr 有 "无法推断 run_id"。"""
    porcelain = _make_porcelain((str(tmp_path), "develop"))
    monkeypatch.setattr(subprocess, "run", _stub_subprocess_run(porcelain))
    # infer_run_id_from_branch 也返 None（develop 分支）
    monkeypatch.setattr(wc, "infer_run_id_from_branch", lambda root: None)

    rc = wc.main(args=[], repo_root=tmp_path)
    captured = capsys.readouterr()

    assert rc == 1
    assert "无法推断 run_id" in captured.err


# ============================================================================
# TC-WT-7 · main · 1 个 worktree：调 switch 函数（mock 掉 execv）
# ============================================================================


def test_main_one_worktree_invokes_switch(monkeypatch, tmp_path, capsys):
    """单 worktree → 调 _switch_to_worktree_and_exec；不实际 execv（mock 成返 0）。"""
    porcelain = _make_porcelain(
        (str(tmp_path), "develop"),
        (str(tmp_path / "wt-a"), "feat/req-20260519-foo"),
    )
    monkeypatch.setattr(subprocess, "run", _stub_subprocess_run(porcelain))
    monkeypatch.setattr(wc, "infer_run_id_from_branch", lambda root: None)

    called = {}
    def _fake_switch(wt, args):
        called["wt"] = wt
        called["args"] = args
        return 0
    monkeypatch.setattr(wc, "_switch_to_worktree_and_exec", _fake_switch)

    rc = wc.main(args=[], repo_root=tmp_path)

    assert rc == 0
    assert called["wt"]["run_id"] == "20260519-foo"
    assert called["args"] == []


# ============================================================================
# TC-WT-8 · main · 多 worktree：列出 + 退码 2
# ============================================================================


def test_main_multiple_worktrees_lists_and_exits_two(monkeypatch, tmp_path, capsys):
    """≥2 个 feat/req-* worktree → 列出供选，退码 2，stderr 含每个 run_id。"""
    porcelain = _make_porcelain(
        (str(tmp_path), "develop"),
        (str(tmp_path / "wt-a"), "feat/req-20260519-foo"),
        (str(tmp_path / "wt-b"), "feat/req-20260519-bar"),
    )
    monkeypatch.setattr(subprocess, "run", _stub_subprocess_run(porcelain))
    monkeypatch.setattr(wc, "infer_run_id_from_branch", lambda root: None)

    rc = wc.main(args=[], repo_root=tmp_path)
    captured = capsys.readouterr()

    assert rc == 2
    assert "20260519-foo" in captured.err
    assert "20260519-bar" in captured.err
    assert "多个活跃需求 worktree" in captured.err
