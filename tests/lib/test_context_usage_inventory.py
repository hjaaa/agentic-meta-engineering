"""F-004 · ContextInventory.scan 验收测试。

覆盖 5 条验收标准：
  1. scan 返回 list[KnowledgeFile]，5 字段齐全（path / rel_path / kind / size_bytes / fs_mtime）
  2. kind 字段：team / project 按 rel_path 第二段判定
  3. ignore_patterns 生效（`**/draft/**` → draft 目录被排除）
  4. INDEX.md 自身被排除
  5. context_dir 不存在 → FileNotFoundError
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from context_usage_report import (  # noqa: E402
    ContextInventory,
    KnowledgeFile,
)


# ---------------------------------------------------------------------------
# AC-1 · scan 返回 KnowledgeFile，5 字段完整
# ---------------------------------------------------------------------------


def test_scan_returns_knowledge_files_with_full_fields(fake_repo: Path) -> None:
    """所有字段非空且类型正确，path 是绝对路径，rel_path 是 POSIX 相对路径。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=[],
        repo_root=fake_repo,
    )

    files = inv.scan()
    assert files, "至少应扫到 1 个非 INDEX 的 md"
    for kf in files:
        assert isinstance(kf, KnowledgeFile)
        assert kf.path.is_absolute()
        assert kf.path.exists()
        assert kf.rel_path.startswith("context/")
        assert "/" in kf.rel_path  # POSIX 风格
        assert kf.kind in ("team", "project")
        assert kf.size_bytes >= 0
        assert isinstance(kf.fs_mtime, datetime)


# ---------------------------------------------------------------------------
# AC-2 · kind 按 rel_path 第二段判定
# ---------------------------------------------------------------------------


def test_scan_kind_distinguishes_team_and_project(fake_repo: Path) -> None:
    """context/team/foo.md → team；context/project/myproj/bar.md → project。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=[],
        repo_root=fake_repo,
    )
    by_rel = {kf.rel_path: kf.kind for kf in inv.scan()}

    assert by_rel.get("context/team/foo.md") == "team"
    assert by_rel.get("context/team/draft/wip.md") == "team"  # 嵌套也按第二段
    assert by_rel.get("context/project/myproj/bar.md") == "project"


# ---------------------------------------------------------------------------
# AC-3 · ignore_patterns 生效
# ---------------------------------------------------------------------------


def test_scan_ignore_patterns_excludes_draft(fake_repo: Path) -> None:
    """ignore=`**/draft/**` 应过滤 context/team/draft/wip.md。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=["**/draft/**"],
        repo_root=fake_repo,
    )
    rel_paths = {kf.rel_path for kf in inv.scan()}

    assert "context/team/draft/wip.md" not in rel_paths
    # 非 draft 文件仍在
    assert "context/team/foo.md" in rel_paths
    assert "context/project/myproj/bar.md" in rel_paths


# ---------------------------------------------------------------------------
# AC-4 · INDEX.md 自身被排除
# ---------------------------------------------------------------------------


def test_scan_excludes_index_md(fake_repo: Path) -> None:
    """两层 INDEX.md（context/INDEX.md, context/project/myproj/INDEX.md）都不返回。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=[],
        repo_root=fake_repo,
    )
    rel_paths = {kf.rel_path for kf in inv.scan()}

    assert not any(p.endswith("INDEX.md") for p in rel_paths), (
        f"INDEX.md 不应出现在结果里，实际：{rel_paths}"
    )


# ---------------------------------------------------------------------------
# AC-5 · context_dir 不存在 → FileNotFoundError
# ---------------------------------------------------------------------------


def test_init_raises_when_context_dir_missing(tmp_path: Path) -> None:
    """目录不存在时 __init__ 立即抛 FileNotFoundError，不延迟到 scan。"""
    with pytest.raises(FileNotFoundError):
        ContextInventory(
            context_dir=tmp_path / "missing",
            ignore_patterns=[],
            repo_root=tmp_path,
        )


# ---------------------------------------------------------------------------
# 幂等性 · 多次调用返回等价结果（detailed-design.md §组件 1 幂等约定）
# ---------------------------------------------------------------------------


def test_scan_is_idempotent(fake_repo: Path) -> None:
    """连续两次 scan 在 fs 不变的前提下返回字段值相同的列表。"""
    inv = ContextInventory(
        context_dir=fake_repo / "context",
        ignore_patterns=[],
        repo_root=fake_repo,
    )
    first = inv.scan()
    second = inv.scan()
    assert [kf.rel_path for kf in first] == [kf.rel_path for kf in second]
    assert [kf.kind for kf in first] == [kf.kind for kf in second]
    assert [kf.size_bytes for kf in first] == [kf.size_bytes for kf in second]
