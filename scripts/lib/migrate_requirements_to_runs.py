"""批量 rename 工具：requirements/ → runs/ 路径引用替换。

公开入口：
    from migrate_requirements_to_runs import migrate_requirements_to_runs, MigrationReport
    report = migrate_requirements_to_runs(dry_run=True)

功能说明（详见 detailed-design §9）：
  - 6 层扫描矩阵：代码层 / 配置层 / gate 层 / 文档层 / 历史层 / git 层
  - dry_run=True（默认）：只报告，不写文件
  - dry_run=False：真正替换字面量引用
  - risky_unmapped：f-string / concat 不自动改，供人工 review
  - whitelist：内置白名单 + 调用方可追加

⚠️ 禁止在本 feature 中以 dry_run=False 跑真实仓库
   （顺序约束 §9.8：留待 F-012 Plan 7）。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ============================================================================
# 公开数据结构
# ============================================================================

@dataclass(frozen=True)
class Reference:
    """单条 requirements/REQ- 引用记录。"""

    file_path: Path
    line: int
    old_text: str
    new_text: str
    kind: Literal["literal", "f_string", "concat", "comment", "docstring", "yaml_glob"]


@dataclass(frozen=True)
class DirectoryMove:
    """目录重命名记录（wet_run 时填充）。"""

    src: Path
    dst: Path


@dataclass(frozen=True)
class MigrationReport:
    """migrate_requirements_to_runs() 返回值。"""

    scanned_files: int
    files_changed: list[Path]
    references_found: list[Reference]
    risky_unmapped: list[Reference]
    skipped_whitelist: list[Reference]
    moved_directories: list[DirectoryMove]
    pre_commit_added: bool
    dry_run: bool
    duration_ms: int


# ============================================================================
# 内部常量
# ============================================================================

# 匹配 requirements/REQ- 字面量路径（不含纯变量拼接）
_LITERAL_RE = re.compile(r'(requirements/REQ-[\w/.*-]+)')

# f-string 检测：f"requirements/{...}" 或 f'requirements/{...}'
_FSTRING_RE = re.compile(r'f["\']requirements/\{[^}]+\}')

# concat 检测："requirements/" + var 或 'requirements/' + var（纯 Python 正则）
_CONCAT_PY_RE = re.compile(r'''["']requirements/["']\s*\+''')

# 工具自身路径（避免自引用改写）
_SELF_FILES = frozenset([
    "scripts/lib/migrate_requirements_to_runs.py",
    "scripts/git-hooks/pre-commit-rename-guard.sh",
])

# 内置白名单模式（相对仓库根的前缀或 glob 语义）
_BUILTIN_WHITELIST_PATTERNS = [
    "requirements/INDEX.md",
    # plan.md 历史 ADR 段（通配匹配任意 REQ-ID 的 plan.md）
    re.compile(r"requirements/REQ-[^/]+/plan\.md$"),
    # archived 目录
    re.compile(r".*\.archived/.*"),
]

# 扫描目标 glob 模式（6 层扫描矩阵，§9.1）
_SCAN_GLOBS = [
    # 代码层
    "**/*.py",
    "**/*.sh",
    # 配置层
    ".claude/skills/**/*.md",
    ".claude/commands/**/*.md",
    ".claude/agents/**/*.md",
    # gate 层
    "scripts/gates/**/*.yaml",
    # 文档层
    "context/team/engineering-spec/**/*.md",
    "CLAUDE.md",
    # 历史层（当前需求自身产出；其他需求的 plan.md 由白名单过滤）
    "requirements/REQ-2026-009/**/*.md",
]


# ============================================================================
# 内部工具函数
# ============================================================================

def _is_whitelisted(
    rel_path: str,
    extra_whitelist: list[Path] | None,
    abs_path: Path | None = None,
) -> bool:
    """判断路径是否命中白名单（内置 + 调用方传入）。

    参数：
        rel_path: 相对于仓库根的路径字符串（用于内置规则匹配）
        extra_whitelist: 调用方传入的额外白名单路径列表（支持绝对路径）
        abs_path: 文件的绝对路径（用于 extra_whitelist 的精确比对）
    """
    # 内置白名单
    for pat in _BUILTIN_WHITELIST_PATTERNS:
        if isinstance(pat, str):
            if rel_path == pat or rel_path.endswith("/" + pat):
                return True
        else:
            if pat.search(rel_path):
                return True
    # 工具自身文件
    for self_file in _SELF_FILES:
        if rel_path.endswith(self_file):
            return True
    # 调用方附加白名单（支持绝对路径比对）
    if extra_whitelist:
        for p in extra_whitelist:
            p_resolved = p.resolve()
            # 精确绝对路径比对（含 macOS /private/tmp 等 symlink 场景）
            if abs_path is not None and abs_path.resolve() == p_resolved:
                return True
            # 相对路径尾缀比对（降级：仅相对路径传入时）
            p_str = str(p)
            if rel_path == p_str or rel_path.endswith("/" + p_str):
                return True
    return False


def _replace_literal(text: str) -> str:
    """把 requirements/REQ- 字面量替换为 runs/REQ-。"""
    return _LITERAL_RE.sub(lambda m: m.group(0).replace("requirements/REQ-", "runs/REQ-", 1), text)


def _scan_file(
    file_path: Path,
    repo_root: Path,
    include_history_comments: bool,
    extra_whitelist: list[Path] | None = None,
) -> tuple[list[Reference], list[Reference], list[Reference]]:
    """扫描单个文件，返回 (refs, risky, skipped_whitelist)。

    - refs：可自动改的字面量引用
    - risky：f-string / concat，需人工 review
    - skipped_whitelist：命中白名单的引用（不改）
    """
    refs: list[Reference] = []
    risky: list[Reference] = []
    skipped: list[Reference] = []

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning("读取文件失败 file_path=%s error=%s", file_path, e)
        return refs, risky, skipped

    rel_path = str(file_path.relative_to(repo_root))

    for lineno, line in enumerate(content.splitlines(), start=1):
        # 跳过不含目标字符串的行（快速短路）
        if "requirements/REQ-" not in line and "requirements/" not in line:
            continue

        # 检测 f-string（risky_unmapped）
        if _FSTRING_RE.search(line):
            risky.append(Reference(
                file_path=file_path,
                line=lineno,
                old_text=line.rstrip(),
                new_text=line.rstrip(),  # 不自动改
                kind="f_string",
            ))
            continue

        # 检测 concat（risky_unmapped）
        if _CONCAT_PY_RE.search(line):
            risky.append(Reference(
                file_path=file_path,
                line=lineno,
                old_text=line.rstrip(),
                new_text=line.rstrip(),
                kind="concat",
            ))
            continue

        # 无字面量 requirements/REQ- → 跳过
        if not _LITERAL_RE.search(line):
            continue

        # 判断是否为注释 / docstring（仅 include_history_comments=True 时自动改）
        stripped = line.strip()
        is_comment_line = (
            stripped.startswith("#")
            or stripped.startswith('"""')
            or stripped.startswith("'''")
        )
        kind = "comment" if is_comment_line else "literal"

        if is_comment_line and not include_history_comments:
            # 注释行 + 不处理历史注释 → 跳过（不进任何列表）
            continue

        new_line = _replace_literal(line)

        ref = Reference(
            file_path=file_path,
            line=lineno,
            old_text=line.rstrip(),
            new_text=new_line.rstrip(),
            kind=kind,
        )

        # 白名单检测（整个文件维度，传入 extra_whitelist 和 abs_path）
        if _is_whitelisted(rel_path, extra_whitelist, abs_path=file_path):
            skipped.append(ref)
        else:
            refs.append(ref)

    return refs, risky, skipped


def _collect_files(
    repo_root: Path,
    extra_files: list[Path] | None = None,
) -> list[Path]:
    """按 6 层扫描矩阵收集待扫描文件列表。

    参数：
        repo_root: 仓库根路径。
        extra_files: 额外指定的文件列表（测试场景或调用方强制扫描用）。
    """
    seen: set[Path] = set()
    result: list[Path] = []

    for glob_pattern in _SCAN_GLOBS:
        for p in repo_root.glob(glob_pattern):
            if p.is_file() and p not in seen:
                seen.add(p)
                result.append(p)

    # 对单文件（CLAUDE.md）补充处理
    claude_md = repo_root / "CLAUDE.md"
    if claude_md.is_file() and claude_md not in seen:
        result.append(claude_md)

    # 调用方指定的额外文件（测试 fixture 等）
    if extra_files:
        for p in extra_files:
            if p.is_file() and p not in seen:
                seen.add(p)
                result.append(p)

    return result


def _apply_changes(
    file_path: Path,
    refs: list[Reference],
) -> None:
    """把字面量 references 的替换写入文件。

    按行号构建替换映射，一次性写回（避免多次读写）。
    """
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError as e:
        logger.error("wet_run 读取文件失败 file_path=%s error=%s", file_path, e)
        raise

    # 构建行号 → 新内容映射（行号从 1 开始）
    line_map: dict[int, str] = {}
    for ref in refs:
        if ref.old_text != ref.new_text:
            new_content = ref.new_text + ("\n" if ref.new_text else "")
            line_map[ref.line] = new_content

    if not line_map:
        return

    for idx, original_line in enumerate(lines, start=1):
        if idx in line_map:
            lines[idx - 1] = line_map[idx]

    try:
        file_path.write_text("".join(lines), encoding="utf-8")
        logger.info("wet_run 写入完成 file_path=%s changes=%d", file_path, len(line_map))
    except OSError as e:
        logger.error("wet_run 写入文件失败 file_path=%s error=%s", file_path, e)
        raise


# ============================================================================
# 公开 API
# ============================================================================

def migrate_requirements_to_runs(
    dry_run: bool = True,
    include_history_comments: bool = False,
    whitelist: list[Path] | None = None,
    repo_root: Path | None = None,
    extra_files: list[Path] | None = None,
) -> MigrationReport:
    """扫描并（可选）批量替换 requirements/REQ- → runs/REQ- 引用。

    参数：
        dry_run: True（默认）仅报告，不写文件；False 执行真正替换。
        include_history_comments: 是否同时改写注释 / docstring 中的引用。
        whitelist: 附加白名单路径列表（追加到内置白名单）。
        repo_root: 仓库根路径，默认自动推断（本文件向上 3 层）。
        extra_files: 额外指定的文件列表（测试 fixture / 局部扫描用）。

    返回：
        MigrationReport，包含全量扫描结果与变更摘要。

    ⚠️ 顺序约束（§9.8）：
        本函数 wet_run 仅由 F-012 Plan 7 手工触发，
        任何自动化流程禁止以 dry_run=False 调用。
    """
    start_ts = time.monotonic()

    if repo_root is None:
        # scripts/lib/migrate_requirements_to_runs.py → repo_root = ../../..
        repo_root = Path(__file__).resolve().parents[2]

    logger.info("migration 扫描启动 dry_run=%s repo_root=%s", dry_run, repo_root)

    files = _collect_files(repo_root, extra_files=extra_files)
    logger.info("共发现待扫描文件 count=%d", len(files))

    all_refs: list[Reference] = []
    all_risky: list[Reference] = []
    all_skipped: list[Reference] = []

    for fp in files:
        rel_path = str(fp.relative_to(repo_root))
        if _is_whitelisted(rel_path, whitelist, abs_path=fp):
            # 整文件白名单：先扫描，统一放入 skipped_whitelist
            refs, risky, inner_skipped = _scan_file(fp, repo_root, include_history_comments)
            all_skipped.extend(refs)
            all_skipped.extend(inner_skipped)
            # risky 也跳过（白名单文件不报 risky）
            continue

        refs, risky, skipped = _scan_file(
            fp, repo_root, include_history_comments, extra_whitelist=whitelist
        )
        all_refs.extend(refs)
        all_risky.extend(risky)
        all_skipped.extend(skipped)

    files_changed: list[Path] = []
    if not dry_run:
        # 按文件分组，批量写入
        by_file: dict[Path, list[Reference]] = {}
        for ref in all_refs:
            by_file.setdefault(ref.file_path, []).append(ref)

        for fp, file_refs in by_file.items():
            has_change = any(r.old_text != r.new_text for r in file_refs)
            if has_change:
                _apply_changes(fp, file_refs)
                files_changed.append(fp)
                logger.info(
                    "wet_run 文件已更新 file_path=%s refs=%d",
                    fp, len(file_refs),
                )
    else:
        # dry_run 不填 files_changed（保持空列表，符合 §9.7 #1 断言）
        pass

    duration_ms = int((time.monotonic() - start_ts) * 1000)

    report = MigrationReport(
        scanned_files=len(files),
        files_changed=files_changed,
        references_found=all_refs,
        risky_unmapped=all_risky,
        skipped_whitelist=all_skipped,
        moved_directories=[],   # 目录 rename 留 F-012 真迁移时处理
        pre_commit_added=False,  # hook 安装由 migration 文档说明，非自动
        dry_run=dry_run,
        duration_ms=duration_ms,
    )

    logger.info(
        "migration 扫描完成 scanned=%d refs=%d risky=%d skipped=%d"
        " files_changed=%d dry_run=%s duration_ms=%d",
        report.scanned_files,
        len(report.references_found),
        len(report.risky_unmapped),
        len(report.skipped_whitelist),
        len(report.files_changed),
        report.dry_run,
        report.duration_ms,
    )

    return report


# ============================================================================
# CLI 入口（调试用）
# ============================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="requirements/ → runs/ 批量 rename 工具")
    parser.add_argument(
        "--wet-run", action="store_true", help="真正执行替换（默认 dry_run）"
    )
    parser.add_argument(
        "--include-comments", action="store_true", help="同时改写注释中的引用"
    )
    args = parser.parse_args()

    report = migrate_requirements_to_runs(
        dry_run=not args.wet_run,
        include_history_comments=args.include_comments,
    )
    print(f"\n=== 迁移报告（{'预演模式' if report.dry_run else '执行模式'}）===")
    print(f"  扫描文件数: {report.scanned_files}")
    print(f"  字面量引用数: {len(report.references_found)}")
    print(f"  risky_unmapped 数: {len(report.risky_unmapped)}")
    print(f"  白名单跳过数: {len(report.skipped_whitelist)}")
    print(f"  实际变更文件数: {len(report.files_changed)}")
    print(f"  耗时: {report.duration_ms} ms")

    if report.risky_unmapped:
        print("\n⚠️  risky_unmapped（需人工 review）：")
        for ref in report.risky_unmapped:
            print(f"  [{ref.kind}] {ref.file_path}:{ref.line}  {ref.old_text[:80]}")
