"""INDEX.md 自动校验核心。

检查项（见 specs/2026-04-22-index-meta-validation-design.md §3.1）：
  1. INDEX 列了但 fs 不存在           → error "腐化"
  2. INDEX 引用的 anchor 在目标 md 里不存在 → warning "软腐化"
  3. INDEX 同目录 + 一级子目录存在但 INDEX 未列 → warning "遗漏"
  4. 全局无任何 INDEX 引用的 md          → warning "孤岛"
  5. INDEX.md 超过 warn_line_limit       → warning "超长"

原则：
  - 只报告不修改（人靠语义判断决定是否 /knowledge:organize-index 修复）
  - ignore 白名单用于声明"合法的不挂主入口"
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import yaml

from common import REPO_ROOT, Report, Severity, paint, rel

CONFIG_PATH = Path(__file__).parent / "index-config.yaml"

# 解析 markdown 链接 `[text](url)` 但不包含图片 `![alt](url)`
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
# 解析标题行
HEADING_RE = re.compile(r"^(#+)\s+(.+?)\s*$")


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _glob_match_any(rel_path: str, patterns: list[str]) -> bool:
    # 用 fnmatch 逐条测试；fnmatch 支持 * 和 ?，不支持 **。人工扩展 **。
    for pat in patterns:
        if _fnmatch_glob(rel_path, pat):
            return True
    return False


def _fnmatch_glob(path: str, pattern: str) -> bool:
    """把 `**` 视为"任意层级"，其余交给 fnmatch。"""
    if "**" not in pattern:
        return fnmatch.fnmatch(path, pattern)
    # 把 ** 变正则 .*
    regex_parts = []
    i = 0
    while i < len(pattern):
        if pattern[i : i + 2] == "**":
            regex_parts.append(".*")
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                i += 1
        elif pattern[i] == "*":
            regex_parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            regex_parts.append("[^/]")
            i += 1
        elif pattern[i] == ".":
            regex_parts.append(r"\.")
            i += 1
        else:
            regex_parts.append(re.escape(pattern[i]))
            i += 1
    regex = "^" + "".join(regex_parts) + "$"
    return re.match(regex, path) is not None


def _slugify(title: str) -> str:
    """近似 GitHub anchor 规则：lower + 空格→`-` + 去非字母数字/中文/连字符。"""
    s = title.lower().strip()
    s = re.sub(r"[^\w一-龥\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s


def _extract_headings(md_path: Path) -> set[str]:
    """提取目标 md 里所有 H1-H6 标题的 slug 集合（用于 anchor 对比）。"""
    slugs: set[str] = set()
    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            m = HEADING_RE.match(line)
            if m:
                slugs.add(_slugify(m.group(2)))
    except (FileNotFoundError, UnicodeDecodeError):
        pass
    return slugs


def _extract_links(index_path: Path) -> list[tuple[str, int]]:
    """返回 [(link_url, line_no), ...]；line_no 用于错误定位。"""
    out: list[tuple[str, int]] = []
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, UnicodeDecodeError):
        return out
    for i, line in enumerate(lines, start=1):
        for m in LINK_RE.finditer(line):
            url = m.group(2).strip()
            out.append((url, i))
    return out


def _is_external_or_intra_anchor(url: str) -> bool:
    if url.startswith(("http://", "https://", "mailto:", "tel:")):
        return True
    if url.startswith("#"):
        return True
    return False


def _resolve_link(index_path: Path, url: str) -> tuple[Path, str | None]:
    """把 INDEX 里写的相对/绝对 URL 解析成 (target_path, anchor|None)。

    URL 可能是：
      - foo/bar.md 或 ./foo/bar.md（相对 INDEX 所在目录）
      - /context/foo.md（从 repo 根的绝对路径）
      - foo/bar.md#section（带 anchor）
    """
    path_part, _, anchor = url.partition("#")
    path_part = unquote(path_part)
    anchor = anchor or None

    if path_part.startswith("/"):
        target = REPO_ROOT / path_part.lstrip("/")
    else:
        target = (index_path.parent / path_part).resolve()
    return target, anchor


def _count_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (FileNotFoundError, UnicodeDecodeError):
        return 0


def _check_index_file(
    index_path: Path,
    referenced_targets: set[Path],
    ignore_patterns: list[str],
    warn_line_limit: int,
    sibling_scan_depth: int,
    report: Report,
) -> None:
    label = rel(index_path)

    # --- 1 & 2. 链接腐化 / 锚点检查 ---
    listed_targets: set[Path] = set()
    for url, line_no in _extract_links(index_path):
        if _is_external_or_intra_anchor(url):
            continue
        target, anchor = _resolve_link(index_path, url)
        listed_targets.add(target)
        referenced_targets.add(target)

        if not target.exists():
            report.add(label, Severity.ERROR, "broken", f"第 {line_no} 行链接 {url!r} 指向的路径不存在")
            continue
        if anchor and target.is_file() and target.suffix == ".md":
            slugs = _extract_headings(target)
            if _slugify(unquote(anchor)) not in slugs:
                report.add(
                    label,
                    Severity.WARNING,
                    "anchor",
                    f"第 {line_no} 行锚点 #{anchor} 在 {rel(target)} 中未找到匹配标题",
                )

    # --- 3. 遗漏检查（同目录 + N 级子目录的 md，未被 INDEX 引用） ---
    index_dir = index_path.parent
    siblings = _collect_siblings(index_dir, sibling_scan_depth)
    for md in siblings:
        if md == index_path:
            continue
        rel_from_root = str(md.resolve().relative_to(REPO_ROOT))
        if _glob_match_any(rel_from_root, ignore_patterns):
            continue
        if md.resolve() in {t.resolve() for t in listed_targets if t.exists()}:
            continue
        report.add(
            label,
            Severity.WARNING,
            "unlisted",
            f"{rel(md)} 在 INDEX 作用范围内但未被列出",
        )

    # --- 5. 行数 ---
    line_count = _count_lines(index_path)
    if line_count > warn_line_limit:
        report.add(
            label,
            Severity.WARNING,
            "too-long",
            f"共 {line_count} 行，超过 warn_line_limit={warn_line_limit}（违反设计红线）",
        )


def _collect_siblings(index_dir: Path, depth: int) -> list[Path]:
    """收集 index_dir 的"作用范围"内的 *.md 文件。

    作用范围规则：
      - 同目录（rel_depth = 0）的 md 一定算
      - 子目录（rel_depth ≤ depth）里的 md 只有在"该子目录没有自己的 INDEX.md"时才算；
        有子 INDEX 的目录里的 md 由那个子 INDEX 负责
      - INDEX.md 本身不在"遗漏"候选集里
    """
    # 预扫描：找出 index_dir 下所有子目录中的 INDEX.md，这些目录是"委派点"
    delegated_dirs: set[Path] = set()
    for sub_idx in index_dir.rglob("INDEX.md"):
        sub_idx_resolved = sub_idx.resolve()
        if sub_idx_resolved == (index_dir / "INDEX.md").resolve():
            continue
        delegated_dirs.add(sub_idx.parent.resolve())

    def _under_delegated(md_resolved: Path) -> bool:
        for d in delegated_dirs:
            try:
                md_resolved.relative_to(d)
                return True
            except ValueError:
                continue
        return False

    results: list[Path] = []
    for md in index_dir.rglob("*.md"):
        if md.name == "INDEX.md":
            continue
        rel_depth = len(md.relative_to(index_dir).parts) - 1
        if rel_depth > depth:
            continue
        if _under_delegated(md.resolve()):
            continue
        results.append(md)
    return results


def _discover_indexes(scan_roots: list[str]) -> list[Path]:
    found: list[Path] = []
    for root in scan_roots:
        root_path = REPO_ROOT / root
        if not root_path.exists():
            continue
        found.extend(root_path.rglob("INDEX.md"))
    return sorted(set(found))


def _discover_all_md(scan_roots: list[str]) -> list[Path]:
    found: list[Path] = []
    for root in scan_roots:
        root_path = REPO_ROOT / root
        if not root_path.exists():
            continue
        found.extend(root_path.rglob("*.md"))
    return sorted(set(found))


def _check_orphans(
    all_md: list[Path],
    referenced_targets: set[Path],
    ignore_patterns: list[str],
    report: Report,
) -> None:
    """全局孤岛检测：所有 md - 所有 INDEX 引用过的 md - ignore 白名单 = 孤岛。"""
    referenced_resolved = {t.resolve() for t in referenced_targets if t.exists()}
    for md in all_md:
        if md.resolve() in referenced_resolved:
            continue
        rel_from_root = str(md.resolve().relative_to(REPO_ROOT))
        if _glob_match_any(rel_from_root, ignore_patterns):
            continue
        report.add(
            "全局",
            Severity.WARNING,
            "orphan",
            f"{rel_from_root} 全局无任何 INDEX 引用",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 INDEX.md 的条目一致性与健康度")
    parser.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = parser.parse_args()

    try:
        config = _load_config()
    except Exception as exc:  # noqa: BLE001
        print(paint(f"读取 {rel(CONFIG_PATH)} 失败: {exc}", "red"), file=sys.stderr)
        return 2

    scan_roots = config.get("scan_roots", [])
    ignore = config.get("ignore", []) or []
    warn_line_limit = int(config.get("warn_line_limit", 200))
    sibling_scan_depth = int(config.get("sibling_scan_depth", 1))

    indexes = _discover_indexes(scan_roots)
    if not indexes:
        print(paint("未发现任何 INDEX.md，无需校验", "cyan"))
        return 0

    report = Report()
    referenced_targets: set[Path] = set()

    for idx in indexes:
        _check_index_file(
            idx,
            referenced_targets,
            ignore,
            warn_line_limit,
            sibling_scan_depth,
            report,
        )

    all_md = _discover_all_md(scan_roots)
    _check_orphans(all_md, referenced_targets, ignore, report)

    print(report.render())
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
