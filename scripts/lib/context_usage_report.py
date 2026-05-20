"""context/** 知识利用率统计——核心组件（F-004 起逐步落地）。

本模块对 detailed-design.md §接口签名 / §数据结构 的实现承诺：

  - 数据载体 frozen dataclass：KnowledgeFile（F-004）
  - 扫描组件 ContextInventory（F-004）
  - IndexGraph / EvidenceScanner / ... 后续 feature 接入

不读文件内容、只列路径与 stat——内容解析由 markdown_links 模块负责。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import sys

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from markdown_links import (  # noqa: E402
    extract_links,
    glob_match,
    resolve_link,
)


@dataclass(frozen=True)
class KnowledgeFile:
    """context/** 下一个被纳入统计的 md 文件。

    五字段与 detailed-design.md §数据结构 一一对应；frozen 保证下游聚合阶段
    放进 set / dict key 不会因引用相等性意外改写。
    """

    path: Path
    rel_path: str
    kind: Literal["team", "project"]
    size_bytes: int
    fs_mtime: datetime


def _classify_kind(rel_path: str) -> Literal["team", "project"]:
    """按 rel_path 第二段判定 team / project。

    `context/team/...` → "team"；`context/project/<X>/...` → "project"。
    其余形态（如 `context/foo.md` 直接挂根、或第一段非 `context`）一律
    归 "team"——detailed-design.md §数据结构 把 kind 收敛为二选一字面量，
    不引入 "other" 第三态，避免下游分支扩散。

    路径分段约定：调用方传入的 rel_path 已是 POSIX `/` 风格（由
    ContextInventory.scan 统一规范化）。
    """
    parts = rel_path.split("/")
    if len(parts) >= 2 and parts[0] == "context" and parts[1] == "project":
        return "project"
    return "team"


class ContextInventory:
    """枚举 context/** 下所有纳入统计的 md 文件。

    职责（detailed-design §组件 1）：
    - rglob('*.md') 扫 context_dir 下所有 md
    - 应用 index-config.yaml ignore 规则（复用 markdown_links.glob_match）
    - 剔除 INDEX.md
    - 输出 list[KnowledgeFile]（不读内容，只列路径与 stat）
    """

    def __init__(
        self,
        context_dir: Path,
        ignore_patterns: list[str],
        repo_root: Path,
    ) -> None:
        """
        Args:
            context_dir: 扫描根（默认 REPO_ROOT/context）
            ignore_patterns: 来自 index-config.yaml 的忽略 glob，可空列表
            repo_root: 用于计算相对路径

        Raises:
            FileNotFoundError: context_dir 不存在
        """
        if not context_dir.exists():
            raise FileNotFoundError(f"context_dir 不存在：{context_dir}")
        self._context_dir = context_dir
        self._ignore_patterns = list(ignore_patterns)
        self._repo_root = repo_root.resolve()

    def scan(self) -> list[KnowledgeFile]:
        """单次扫描，返回过滤后的文件列表。

        幂等：多次调用返回同一结果（在 fs 不变前提下）。
        性能预期：5000 文件 < 1s（仅 rglob + ignore 匹配，不读内容）。
        """
        results: list[KnowledgeFile] = []
        for path in sorted(self._context_dir.rglob("*.md")):
            if not path.is_file():
                continue
            if path.name == "INDEX.md":
                continue
            rel_path = path.resolve().relative_to(self._repo_root).as_posix()
            if any(glob_match(rel_path, p) for p in self._ignore_patterns):
                continue
            stat = path.stat()
            results.append(
                KnowledgeFile(
                    path=path,
                    rel_path=rel_path,
                    kind=_classify_kind(rel_path),
                    size_bytes=stat.st_size,
                    fs_mtime=datetime.fromtimestamp(
                        int(stat.st_mtime), tz=timezone.utc
                    ),
                )
            )
        return results


# ---------------------------------------------------------------------------
# F-005 · IndexGraph：扫 context/**/INDEX.md，识别断链与孤岛
# 接口/数据结构来源：detailed-design.md §组件 2 / §数据结构（interfaces_frozen）
# ---------------------------------------------------------------------------


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
    orphans: list[KnowledgeFile]


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
            # INDEX 不可读：跳过，不计断链（fail-open；与 EvidenceScanner 一致基调）
            return [], []

        indexed_items: list[tuple[str, str]] = []
        broken_links: list[BrokenLink] = []

        for link in extract_links(md_text):
            resolved = resolve_link(link.url, index_path, self._repo_root)
            if resolved is None:
                # 外链 / intra-anchor / 越界 → 跳过
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
            # INDEX 自身不作为被索引对象（避免 INDEX → INDEX 循环计入）
            if resolved.name == "INDEX.md":
                continue
            indexed_items.append((target_rel, index_rel))

        return indexed_items, broken_links

    def build(self, files: list[KnowledgeFile]) -> IndexGraphResult:
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

        # indexed_by 每个 list 字典序排序
        for k in indexed_by:
            indexed_by[k] = sorted(indexed_by[k])

        # orphans：files 中 rel_path 未出现在 indexed_by key 的子集
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
