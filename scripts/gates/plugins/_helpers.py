"""plugins 共享工具函数（F-016/F-017/F-018 提取）。

本模块收纳跨 plugin 复用的路径解析辅助函数，降低各 plugin 的 CC 并消除重复代码。

函数列表：
  - _changed_artifact_paths  — 从 changed_files 筛出 artifacts/**/*.md 路径
  - _changed_req_dirs        — 从 changed_files 提取涉及的需求目录集合
"""
from __future__ import annotations

from pathlib import Path


def _changed_artifact_paths(changed_files: list[str]) -> list[Path]:
    """从 changed_files 中筛选出命中 requirements/*/artifacts/**/*.md 的路径。

    参数：
      changed_files — staged 文件列表（相对仓库根的路径字符串，不含前导 /）

    返回：
      命中的 Path 列表（保持原始顺序，不去重）

    使用场景：sourcing.py _resolve_targets 的 pre-commit 分支。
    """
    result: list[Path] = []
    for f in changed_files:
        p = Path(f)
        parts = p.parts
        if (
            len(parts) >= 4
            and parts[0] == "requirements"
            and parts[2] == "artifacts"
            and f.endswith(".md")
        ):
            result.append(p)
    return result


def _changed_req_dirs(changed_files: list[str], repo_root: Path) -> set[Path]:
    """从 changed_files 中提取涉及的需求目录集合（绝对路径）。

    参数：
      changed_files — staged 文件列表（相对仓库根的路径字符串）
      repo_root     — 仓库根目录绝对路径（用于拼接绝对路径）

    返回：
      涉及的需求目录绝对路径 set（如 {repo_root}/requirements/REQ-2026-002）

    使用场景：plan_freshness._resolve_req_dirs / traceability.run 的 pre-commit 分支。
    """
    dirs: set[Path] = set()
    for f in changed_files:
        parts = Path(f).parts
        if len(parts) >= 2 and parts[0] == "requirements":
            dirs.add(repo_root / parts[0] / parts[1])
    return dirs
