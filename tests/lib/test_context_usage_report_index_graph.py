"""tests for IndexGraph（F-005 验收测试）。

覆盖 detailed-design.md §组件 2 / §BrokenLink / §IndexGraphResult 的 4 条
验收标准 + 边界：

  TC1 · indexed_by 正常（键 = 文件 rel_path，值 = INDEX rel_path 列表，字典序）
  TC2 · broken_links：INDEX 列了 fs 不存在的文件 → 带 index_path:line + target
  TC3 · orphans：files 中无 INDEX 引用的子集
  TC4 · 外链 / intra-anchor 跳过，不计入 indexed_by / broken_links
  TC5 · 多个 INDEX 引用同一文件 → indexed_by[target] 含两个 INDEX path（字典序）
  TC6 · 越界路径（`../../outside.md`）resolve_link 返回 None → 不计 broken_links
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from context_usage_report import (  # noqa: E402
    BrokenLink,
    IndexGraph,
    IndexGraphResult,
    KnowledgeFile,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_kf(repo_root: Path, rel_path: str, kind: str = "team") -> KnowledgeFile:
    """构造 KnowledgeFile（不依赖 ContextInventory，避免环依赖）。"""
    p = repo_root / rel_path
    stat = p.stat()
    return KnowledgeFile(
        path=p,
        rel_path=rel_path,
        kind=kind,  # type: ignore[arg-type]
        size_bytes=stat.st_size,
        fs_mtime=datetime.fromtimestamp(int(stat.st_mtime), tz=timezone.utc),
    )


# ---------------------------------------------------------------------------
# TC1 · indexed_by 正常
# ---------------------------------------------------------------------------


def test_indexed_by_lists_index_paths(tmp_path: Path) -> None:
    """INDEX 列了存在文件 → indexed_by 键为文件 rel_path，值为含 INDEX 的列表。"""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "foo.md").write_text("# foo\n", encoding="utf-8")
    (ctx / "INDEX.md").write_text(
        "# index\n\n- [foo](foo.md)\n",
        encoding="utf-8",
    )

    files = [_make_kf(tmp_path, "context/foo.md")]
    result = IndexGraph(ctx, tmp_path).build(files)

    assert isinstance(result, IndexGraphResult)
    assert result.indexed_by == {"context/foo.md": ["context/INDEX.md"]}
    assert result.broken_links == []
    assert result.orphans == []


# ---------------------------------------------------------------------------
# TC2 · broken_links
# ---------------------------------------------------------------------------


def test_broken_links_detected_with_position(tmp_path: Path) -> None:
    """INDEX 列了 nonexistent.md → broken_links 含一条，带 index/line/target/text。"""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "INDEX.md").write_text(
        "# index\n\n\n- [missing one](nonexistent.md)\n",
        encoding="utf-8",
    )

    result = IndexGraph(ctx, tmp_path).build(files=[])

    assert len(result.broken_links) == 1
    bl = result.broken_links[0]
    assert isinstance(bl, BrokenLink)
    assert bl.index_path == "context/INDEX.md"
    assert bl.line == 4  # 1-based: 第 4 行
    assert bl.target == "context/nonexistent.md"
    assert bl.link_text == "missing one"
    assert result.indexed_by == {}


# ---------------------------------------------------------------------------
# TC3 · orphans
# ---------------------------------------------------------------------------


def test_orphans_are_files_without_index_reference(tmp_path: Path) -> None:
    """context 下有文件 但 INDEX 未引用 → orphans 含该 KnowledgeFile。"""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "lonely.md").write_text("# lonely\n", encoding="utf-8")
    (ctx / "indexed.md").write_text("# indexed\n", encoding="utf-8")
    (ctx / "INDEX.md").write_text(
        "# index\n\n- [indexed](indexed.md)\n",
        encoding="utf-8",
    )

    files = [
        _make_kf(tmp_path, "context/lonely.md"),
        _make_kf(tmp_path, "context/indexed.md"),
    ]
    result = IndexGraph(ctx, tmp_path).build(files)

    orphan_paths = [kf.rel_path for kf in result.orphans]
    assert orphan_paths == ["context/lonely.md"]
    assert "context/indexed.md" in result.indexed_by


# ---------------------------------------------------------------------------
# TC4 · 外链 / intra-anchor 跳过
# ---------------------------------------------------------------------------


def test_external_and_anchor_links_skipped(tmp_path: Path) -> None:
    """`[X](https://...)` 与 `[Y](#anchor)` 都不计入 indexed_by / broken_links。"""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "INDEX.md").write_text(
        "# index\n\n"
        "- [GitHub](https://github.com/foo)\n"
        "- [anchor](#section)\n"
        "- [mailto](mailto:foo@bar.com)\n",
        encoding="utf-8",
    )

    result = IndexGraph(ctx, tmp_path).build(files=[])

    assert result.indexed_by == {}
    assert result.broken_links == []


# ---------------------------------------------------------------------------
# TC5 · 多 INDEX 引用同一文件，字典序聚合
# ---------------------------------------------------------------------------


def test_multiple_indexes_referencing_same_file_sorted(tmp_path: Path) -> None:
    """两个 INDEX 都引用 foo.md → indexed_by['context/foo.md'] 含两个 INDEX 路径，字典序。"""
    ctx = tmp_path / "context"
    sub_b = ctx / "b"
    sub_a = ctx / "a"
    sub_a.mkdir(parents=True)
    sub_b.mkdir(parents=True)

    (ctx / "foo.md").write_text("# foo\n", encoding="utf-8")
    # 故意让子 INDEX 先扫到（b 在前），验证 list 内部排序的是字典序而不是扫描序
    (sub_b / "INDEX.md").write_text(
        "# b idx\n\n- [foo](../foo.md)\n", encoding="utf-8"
    )
    (sub_a / "INDEX.md").write_text(
        "# a idx\n\n- [foo](../foo.md)\n", encoding="utf-8"
    )

    files = [_make_kf(tmp_path, "context/foo.md")]
    result = IndexGraph(ctx, tmp_path).build(files)

    assert result.indexed_by == {
        "context/foo.md": [
            "context/a/INDEX.md",
            "context/b/INDEX.md",
        ]
    }
    assert result.orphans == []


# ---------------------------------------------------------------------------
# TC6 · 越界路径不计入 broken_links
# ---------------------------------------------------------------------------


def test_out_of_repo_links_are_skipped(tmp_path: Path) -> None:
    """INDEX 列 `../../outside.md` → resolve_link 返回 None → 跳过（不计 broken_links）。"""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "INDEX.md").write_text(
        "# index\n\n- [outside](../../outside.md)\n",
        encoding="utf-8",
    )

    result = IndexGraph(ctx, tmp_path).build(files=[])

    assert result.indexed_by == {}
    assert result.broken_links == []


# ---------------------------------------------------------------------------
# 边界 · INDEX 自身不作为被索引对象
# ---------------------------------------------------------------------------


def test_index_referencing_another_index_is_not_in_indexed_by(tmp_path: Path) -> None:
    """根 INDEX 引用子 INDEX → 子 INDEX 不进 indexed_by（INDEX 是索引方，不是被索引方）。"""
    ctx = tmp_path / "context"
    sub = ctx / "team"
    sub.mkdir(parents=True)

    (sub / "INDEX.md").write_text("# team idx\n", encoding="utf-8")
    (ctx / "INDEX.md").write_text(
        "# root\n\n- [team](team/INDEX.md)\n", encoding="utf-8"
    )

    result = IndexGraph(ctx, tmp_path).build(files=[])

    assert result.indexed_by == {}
    assert result.broken_links == []


# ---------------------------------------------------------------------------
# 幂等性 · 两次 build 输出等价
# ---------------------------------------------------------------------------


def test_build_is_idempotent(tmp_path: Path) -> None:
    """连续两次 build 在 fs 不变前提下返回等价结果。"""
    ctx = tmp_path / "context"
    ctx.mkdir()
    (ctx / "foo.md").write_text("# foo\n", encoding="utf-8")
    (ctx / "INDEX.md").write_text(
        "# index\n- [foo](foo.md)\n- [bad](missing.md)\n", encoding="utf-8"
    )

    files = [_make_kf(tmp_path, "context/foo.md")]
    g = IndexGraph(ctx, tmp_path)
    r1 = g.build(files)
    r2 = g.build(files)

    assert r1.indexed_by == r2.indexed_by
    assert r1.broken_links == r2.broken_links
    assert [kf.rel_path for kf in r1.orphans] == [kf.rel_path for kf in r2.orphans]
