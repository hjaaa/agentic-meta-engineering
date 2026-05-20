"""context_usage_inventory — F-004 知识文件枚举组件。

负责：
  - KnowledgeFile 数据载体 (frozen dataclass)
  - _classify_kind 路径分类助手
  - ContextInventory 枚举器：rglob + ignore + 剔除 INDEX.md
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from markdown_links import glob_match  # noqa: E402


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
