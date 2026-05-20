"""context_usage_index_graph — F-005 IndexGraph 组件。

负责：
  - BrokenLink 数据载体 (frozen dataclass)
  - IndexGraphResult 数据载体 (frozen dataclass)
  - IndexGraph: 扫 context/**/INDEX.md，识别断链与孤岛
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from markdown_links import extract_links, resolve_link  # noqa: E402


@dataclass(frozen=True)
class BrokenLink:
    """INDEX.md 里列了但 fs 不存在的链接。

    四字段对应 detailed-design.md §BrokenLink；frozen 便于放进 set/dict。
    """

    index_path: str   # 出现断链的 INDEX.md 的 rel_path（POSIX）
    line: int         # 1-based 行号
    target: str       # 目标 rel_path（理论的，fs 上不存在）；POSIX
    link_text: str    # 原始 link text


@dataclass(frozen=True)
class IndexGraphResult:
    """IndexGraph.build() 的产物。

    三字段对应 detailed-design.md §IndexGraphResult。
    """

    indexed_by: dict[str, list[str]]
    broken_links: list[BrokenLink]
    orphans: list  # list[KnowledgeFile]


class IndexGraph:
    """构建 context/**/INDEX.md 的链接图（detailed-design §组件 2）。

    职责：
      - rglob 扫 context_dir 下所有 INDEX.md（INDEX 自身从不被 ignore）
      - 用 markdown_links.extract_links + resolve_link 解析每条 link
      - 输出 indexed_by / broken_links / orphans 三视图

    幂等：纯计算，无 IO 写。
    """

    def __init__(self, context_dir: Path, repo_root: Path) -> None:
        """
        Args:
            context_dir: INDEX 扫描根（默认 REPO_ROOT/context）
            repo_root:   仓库根，用于 rel_path 计算 + resolve_link 越界判定
        """
        self._context_dir = context_dir
        self._repo_root = repo_root.resolve()

    def _process_index_file(
        self, index_path: Path, index_rel: str
    ) -> tuple[list[tuple[str, str]], list[BrokenLink]]:
        """处理单个 INDEX.md：读文件 + 遍历每条 link，返回该 INDEX 的局部结果。

        Args:
            index_path: INDEX.md 的绝对路径
            index_rel:  INDEX.md 相对仓库根的 POSIX rel_path

        Returns:
            (indexed_items, broken_links)
              - indexed_items: list of (target_rel, index_rel)，调用方据此聚合 indexed_by
              - broken_links:  本 INDEX 内的断链列表

        约定（与 build() 一致）：
          - 外链 / intra-anchor / 越界：跳过
          - INDEX → INDEX：跳过（INDEX 是索引方，不计入 indexed_by）
          - INDEX 不可读：返回 ([], []) (fail-open)
        """
        try:
            md_text = index_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return [], []

        indexed_items: list[tuple[str, str]] = []
        broken_links: list[BrokenLink] = []

        for link in extract_links(md_text):
            resolved = resolve_link(link.url, index_path, self._repo_root)
            if resolved is None:
                continue
            target_rel = resolved.relative_to(self._repo_root).as_posix()
            if not resolved.exists():
                broken_links.append(
                    BrokenLink(
                        index_path=index_rel,
                        line=link.line,
                        target=target_rel,
                        link_text=link.text,
                    )
                )
                continue
            if resolved.name == "INDEX.md":
                continue
            indexed_items.append((target_rel, index_rel))

        return indexed_items, broken_links

    def build(self, files: list) -> IndexGraphResult:  # files: list[KnowledgeFile]
        """单次构建，返回 IndexGraphResult。

        Args:
            files: ContextInventory.scan() 输出，用于 cross-check 孤岛

        约定：
          - INDEX.md 自身不计入 indexed_by 的 key（INDEX 是索引方，不是被索引方）
          - indexed_by[target] 列表按字典序排序
          - broken_links 按 (index_path, line) 升序
          - orphans 按 rel_path 升序
        """
        indexed_by: dict[str, list[str]] = {}
        broken_links: list[BrokenLink] = []

        for index_path in sorted(self._context_dir.rglob("INDEX.md")):
            if not index_path.is_file():
                continue
            index_rel = index_path.resolve().relative_to(self._repo_root).as_posix()
            items, broken = self._process_index_file(index_path, index_rel)
            for target_rel, idx_rel in items:
                indexed_by.setdefault(target_rel, []).append(idx_rel)
            broken_links.extend(broken)

        for k in indexed_by:
            indexed_by[k] = sorted(indexed_by[k])

        orphans = sorted(
            (kf for kf in files if kf.rel_path not in indexed_by),
            key=lambda kf: kf.rel_path,
        )

        broken_links.sort(key=lambda b: (b.index_path, b.line))

        return IndexGraphResult(
            indexed_by=indexed_by,
            broken_links=broken_links,
            orphans=orphans,
        )
