"""context/** 知识利用率统计——CLI 入口与公开接口 re-export（F-011）。

本模块是 F-004 ~ F-010 各组件的统一出口：
  - 顶部 re-export 所有子模块的公开类与函数（保持 tests 不改动）
  - 底部为 F-011 CLI 逻辑：_parse_since / _check_dirs / _build_file_cache /
    _print_summary / _render_and_write / _build_all_files_for_git /
    _scan_and_filter / _aggregate_summaries / _parse_args / _run / main

不读文件内容、只列路径与 stat——内容解析由 markdown_links 模块负责。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# ---------------------------------------------------------------------------
# Re-export all public names so tests can continue to do:
#   from context_usage_report import KnowledgeFile, ContextInventory, ...
# ---------------------------------------------------------------------------

from context_usage_inventory import KnowledgeFile, ContextInventory, _classify_kind  # noqa: E402, F401
from context_usage_git import GitTimestamp, _parse_git_log_output, _build_timestamp_result  # noqa: E402, F401
from context_usage_index_graph import BrokenLink, IndexGraphResult, IndexGraph  # noqa: E402, F401
from context_usage_evidence import (  # noqa: E402, F401
    ReferenceEvidence,
    EvidenceScanner,
    _RAW_PATH_RE,
    _SOURCE_MARKER_RE,
    _strip_line_suffix,
    _resolve_url_to_context_rel,
    _scan_text_lines,
    _scan_json_values,
)
from context_usage_applied import (  # noqa: E402, F401
    AppliedEvidence,
    AppliedSignalClassifier,
    _ANY_H_RE,
    _build_section_map,
    _section_line_range,
)
from context_usage_aggregator import (  # noqa: E402, F401
    KnowledgeStatus,
    KnowledgeUsageSummary,
    UsageAggregator,
)
from context_usage_renderer import ReportRenderer, _to_iso8601  # noqa: E402, F401

__all__ = [
    "KnowledgeFile", "ContextInventory", "_classify_kind",
    "GitTimestamp", "fetch_git_timestamps",
    "_parse_git_log_output", "_build_timestamp_result",
    "BrokenLink", "IndexGraphResult", "IndexGraph",
    "ReferenceEvidence", "EvidenceScanner",
    "_RAW_PATH_RE", "_SOURCE_MARKER_RE", "_strip_line_suffix",
    "_resolve_url_to_context_rel", "_scan_text_lines", "_scan_json_values",
    "AppliedEvidence", "AppliedSignalClassifier",
    "_ANY_H_RE", "_build_section_map", "_section_line_range",
    "KnowledgeStatus", "KnowledgeUsageSummary", "UsageAggregator",
    "ReportRenderer", "_to_iso8601",
    "main", "_parse_args", "_parse_since", "_run",
    "_check_dirs", "_build_file_cache", "_print_summary",
    "_render_and_write", "_build_all_files_for_git",
    "_scan_and_filter", "_aggregate_summaries",
]

# ---------------------------------------------------------------------------
# F-011 · CLI 入口：main() + argparse + 6 档退出码
# 接口/数据结构来源：detailed-design.md §CLI 入口 / §CLI Arguments / §异常处理表
# ---------------------------------------------------------------------------

import argparse
import re
import subprocess
from datetime import datetime, timezone


def fetch_git_timestamps(
    files: list[KnowledgeFile],
    since_days: int,
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, GitTimestamp], list[str]]:
    """批量获取文件的 git 提交时间戳（F-008）。

    定义在主模块以保持测试 @patch("context_usage_report.subprocess.run") 有效。
    失败时回退 fs_mtime，返回 (dict[rel_path, GitTimestamp], warnings)。
    详见 context_usage_git._parse_git_log_output / _build_timestamp_result。
    """
    if repo_root is None:
        repo_root = Path.cwd()
    repo_root = repo_root.resolve()

    if not files:
        return {}, []

    warnings: list[str] = []

    def _fallback_all(reason: str) -> tuple[dict[str, GitTimestamp], list[str]]:
        warnings.append(reason)
        result = {
            f.rel_path: GitTimestamp(
                first_commit_at=None,
                last_commit_at=f.fs_mtime,
                source="fs_mtime",
            )
            for f in files
        }
        return result, warnings

    try:
        rel_paths = [f.rel_path for f in files]
        cmd = [
            "git", "log",
            f"--since={since_days}d",
            "--name-only",
            "--pretty=%H|%cI",
            "--",
        ] + rel_paths

        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            text=True,
            check=True,
            capture_output=True,
            timeout=30,
        )

        ts_dict = _parse_git_log_output(proc.stdout)
        result = _build_timestamp_result(files, ts_dict)

    except subprocess.TimeoutExpired:
        return _fallback_all("git log 超时（30s），回退 fs_mtime")
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        return _fallback_all(f"git log 失败（{type(exc).__name__}），回退 fs_mtime")

    return result, warnings


def _parse_since(since: str) -> int:
    r"""解析 --since 字符串为天数（\d+(d|w|m)）。例：90d→90, 2w→14, 3m→90。

    Raises:
        ValueError: 格式非法
    """
    match = re.match(r"^(\d+)([dwm])$", since)
    if not match:
        raise ValueError(f"invalid --since format: {since}, expected \\d+(d|w|m)")

    count = int(match.group(1))
    unit = match.group(2)

    if unit == "d":
        return count
    elif unit == "w":
        return count * 7
    elif unit == "m":
        return count * 30
    else:
        raise ValueError(f"unknown unit: {unit}")


def _check_dirs(context_dir: Path, requirements_dir: Path) -> int | None:
    """校验输入目录。返回 exit code 或 None 表示通过。"""
    if not context_dir.is_dir():
        print(f"ERROR: context-dir 不存在或非目录: {context_dir}", file=sys.stderr)
        return 2
    if not requirements_dir.is_dir():
        print(
            f"ERROR: requirements-dir 不存在或非目录: {requirements_dir}",
            file=sys.stderr,
        )
        return 2
    return None


def _build_file_cache(
    evidences: list[ReferenceEvidence],
    requirements_dir: Path,
    warnings: list[str],
) -> dict[Path, str]:
    """从引用证据收集 source 文件内容缓存。"""
    file_cache: dict[Path, str] = {}
    for evidence in evidences:
        src_path = requirements_dir / evidence.source
        if src_path not in file_cache and src_path.is_file():
            try:
                file_cache[src_path] = src_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                warnings.append(f"读取 {evidence.source} 失败: {e}")
    return file_cache


def _print_summary(summaries: list[KnowledgeUsageSummary], warnings: list[str]) -> None:
    """输出摘要统计到 stdout，warnings 逐条打到 stderr。

    detailed-design.md L781-782：warning / error 行走 stderr，行格式 `<LEVEL> <message>`。
    F-011 review M1 fix：原实现仅打数量到 stdout，CI grep `WARN ` 无法收集。
    """
    status_counts: dict[str, int] = {}
    for s in summaries:
        status = s.status.value if isinstance(s.status, KnowledgeStatus) else str(s.status)
        status_counts[status] = status_counts.get(status, 0) + 1
    print(f"总数: {len(summaries)}")
    for status in sorted(status_counts.keys()):
        print(f"  {status}: {status_counts[status]}")
    if warnings:
        print(f"Warnings: {len(warnings)}")
        for w in warnings:
            print(f"WARN {w}", file=sys.stderr)


def _render_and_write(
    renderer: ReportRenderer,
    summaries: list[KnowledgeUsageSummary],
    warnings: list[str],
    args: argparse.Namespace,
) -> int:
    """渲染并写入报告。返回 exit code：0=success，5=write error。

    F-011 review M2 fix：先 render 两份 content 再批量 write，缩小半写窗口。
    若 json 写失败时 md 已落盘，stderr 提示用户哪一份成功。
    """
    md_content: str | None = None
    json_content: str | None = None

    try:
        if args.format in ("md", "both"):
            md_content = renderer.render_markdown(summaries, warnings)
        if args.format in ("json", "both"):
            json_content = renderer.render_json(summaries, warnings)
    except Exception as e:
        print(f"ERROR: 渲染失败: {e}", file=sys.stderr)
        return 5

    md_written = False
    try:
        if md_content is not None:
            renderer.write(md_content, args.output)
            md_written = True
        if json_content is not None:
            renderer.write(json_content, args.json_output)
        return 0
    except OSError as e:
        print(f"ERROR: 写报告失败: {e}", file=sys.stderr)
        if md_written and json_content is not None:
            print(
                f"WARN 部分写入：md 已成功 ({args.output})，json 未写 ({args.json_output})",
                file=sys.stderr,
            )
        return 5


def _build_all_files_for_git(
    files: list[KnowledgeFile],
    evidences: list[ReferenceEvidence],
    requirements_dir: Path,
    warnings: list[str],
) -> list[KnowledgeFile]:
    """合并 context files + reference source files 用于 git 时间戳查询。"""
    all_files: list[KnowledgeFile] = files.copy()
    reference_source_paths: set[str] = {e.source for e in evidences}

    for src_rel in reference_source_paths:
        src_abs = requirements_dir / src_rel
        if src_abs.is_file():
            try:
                kf = KnowledgeFile(
                    path=src_abs,
                    rel_path=src_rel,
                    kind="team",
                    size_bytes=src_abs.stat().st_size,
                    fs_mtime=datetime.fromtimestamp(
                        src_abs.stat().st_mtime, tz=timezone.utc
                    ).replace(microsecond=0),
                )
                all_files.append(kf)
            except OSError as e:
                warnings.append(f"读取文件元数据 {src_rel} 失败: {e}")
    return all_files


def _scan_and_filter(
    args: argparse.Namespace,
    warnings: list[str],
) -> tuple[list[KnowledgeFile], object, list[ReferenceEvidence]]:
    """执行扫描 + 过滤，返回 (files, graph_result, evidences)。"""
    inv = ContextInventory(
        context_dir=args.context_dir,
        ignore_patterns=["**/draft/**", "**/INDEX.md"],
        repo_root=args.repo_root,
    )
    files = inv.scan()
    if args.only_experience:
        files = [f for f in files if "experience" in f.rel_path]
    if args.project:
        files = [
            f
            for f in files
            if f.rel_path.startswith(f"context/project/{args.project}/")
        ]

    graph_result = IndexGraph(
        context_dir=args.context_dir, repo_root=args.repo_root
    ).build(files)
    scanner = EvidenceScanner(
        requirements_dir=args.requirements_dir,
        context_files={f.rel_path for f in files},
        repo_root=args.repo_root,
    )
    evidences = scanner.scan()
    warnings.extend(scanner.warnings)

    return files, graph_result, evidences


def _aggregate_summaries(
    files: list[KnowledgeFile],
    graph_result: object,
    evidences: list[ReferenceEvidence],
    applied: list[AppliedEvidence],
    timestamps: dict[str, GitTimestamp],
    now: datetime,
) -> list[KnowledgeUsageSummary]:
    """聚合四路证据，返回 KnowledgeUsageSummary 列表。"""
    return UsageAggregator(
        inventory=files,
        index_result=graph_result,
        references=evidences,
        applied=applied,
        git_timestamps=timestamps,
        now=now,
    ).aggregate()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数；argv=None 时从 sys.argv 读。"""
    from common import REPO_ROOT  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="context_usage_report",
        description="生成 context/** 知识利用率统计报告",
    )

    parser.add_argument(
        "--context-dir",
        type=Path,
        default=REPO_ROOT / "context",
        help="context 目录路径（默认 REPO_ROOT/context）",
    )
    parser.add_argument(
        "--requirements-dir",
        type=Path,
        default=REPO_ROOT / "requirements",
        help="requirements 目录路径（默认 REPO_ROOT/requirements）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "reports" / "context-usage.md",
        help="Markdown 报告输出路径（默认 REPO_ROOT/reports/context-usage.md）",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPO_ROOT / "reports" / "context-usage.json",
        help="JSON 报告输出路径（默认 REPO_ROOT/reports/context-usage.json）",
    )
    parser.add_argument(
        "--since",
        type=str,
        default="90d",
        help="查询范围（默认 90d）；格式 \\d+(d|w|m)，例 90d / 2w / 3m",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="过滤 context/project/<X>/；若不指定则不过滤",
    )
    parser.add_argument(
        "--only-experience",
        action="store_true",
        help="仅统计 context/team/experience/** 下的文件",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["md", "json", "both"],
        default="both",
        help="报告格式（默认 both）",
    )
    parser.add_argument(
        "--fail-on-broken-index",
        action="store_true",
        help="若检出 INDEX 断链则 exit 3",
    )
    parser.add_argument(
        "--fail-on-orphan",
        action="store_true",
        help="若检出孤岛文件则 exit 4",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="仓库根（测试注入）",
    )

    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    """执行报告生成逻辑。返回 exit code 0-5。"""
    err = _check_dirs(args.context_dir, args.requirements_dir)
    if err:
        return err

    try:
        since_days = _parse_since(args.since)
    except ValueError as e:
        print(f"ERROR: 无效的 --since 参数: {e}", file=sys.stderr)
        return 1

    warnings: list[str] = []
    now = datetime.now(tz=timezone.utc)

    files, graph_result, evidences = _scan_and_filter(args, warnings)

    file_cache = _build_file_cache(evidences, args.requirements_dir, warnings)
    applied = AppliedSignalClassifier().classify(evidences, file_cache)
    all_files_for_git = _build_all_files_for_git(
        files, evidences, args.requirements_dir, warnings
    )
    timestamps, git_warnings = fetch_git_timestamps(
        all_files_for_git, since_days, repo_root=args.repo_root
    )
    warnings.extend(git_warnings)

    summaries = _aggregate_summaries(files, graph_result, evidences, applied, timestamps, now)

    renderer = ReportRenderer(
        config={
            "context_dir": str(args.context_dir),
            "requirements_dir": str(args.requirements_dir),
            "since_days": since_days,
            "high_value_reference_min": 3,
            "stale_threshold_days": 90,
        },
        broken_links_count=len(graph_result.broken_links),
        orphans_count=len(graph_result.orphans),
        now=now,
    )

    exit_code = _render_and_write(renderer, summaries, warnings, args)
    if exit_code != 0:
        return exit_code

    _print_summary(summaries, warnings)

    if args.fail_on_broken_index and graph_result.broken_links:
        print(
            f"ERROR: BROKEN_LINKS_DETECTED ({len(graph_result.broken_links)} 条)",
            file=sys.stderr,
        )
        return 3
    if args.fail_on_orphan and graph_result.orphans:
        print(
            f"ERROR: ORPHANS_DETECTED ({len(graph_result.orphans)} 个文件)",
            file=sys.stderr,
        )
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Args:
        argv: sys.argv[1:] 风格参数列表；None 时用 sys.argv[1:]

    Returns:
        进程退出码（0-5）
    """
    try:
        args = _parse_args(argv)
        return _run(args)
    except SystemExit:
        raise


if __name__ == "__main__":
    sys.exit(main())
