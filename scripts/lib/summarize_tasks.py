#!/usr/bin/env python3
"""summarize_tasks.py — 汇总 tasks/*.md frontmatter 维度统计。

被 standard-8phase.yaml 的 task-list-summary 节点调用。

用法：
    python3 scripts/lib/summarize_tasks.py <tasks_dir>

输出（stdout，machine-readable + 人类可读）：
    total: N
    by_complexity:
      trivial: a
      light: b
      medium: c
      heavy: d
      unknown: e
    by_status:
      pending: p
      in-progress: q
      done: r
      blocked: s
      unknown: t

退出码：
    0 成功（即便 unknown 桶非空）
    1 tasks_dir 不存在
    2 解析 frontmatter 失败（yaml 错误，非空文件返回 None）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# 字段域（与 task-frontmatter-schema.yaml 对齐；未来扩展时同步）
_COMPLEXITY_BUCKETS = ("trivial", "light", "medium", "heavy", "unknown")
_STATUS_BUCKETS = ("pending", "in-progress", "done", "blocked", "unknown")


def _parse_frontmatter(text: str) -> dict | None:
    """从 markdown text 提取 --- ... --- frontmatter；非法/缺失返回 None。"""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    raw = text[4:end]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def summarize(tasks_dir: Path) -> dict:
    """扫 tasks_dir 下所有 *.md，按 complexity / status 维度计数。"""
    summary: dict = {
        "total": 0,
        "by_complexity": dict.fromkeys(_COMPLEXITY_BUCKETS, 0),
        "by_status": dict.fromkeys(_STATUS_BUCKETS, 0),
    }
    for md in sorted(tasks_dir.glob("*.md")):
        summary["total"] += 1
        fm = _parse_frontmatter(md.read_text(encoding="utf-8"))
        if fm is None:
            summary["by_complexity"]["unknown"] += 1
            summary["by_status"]["unknown"] += 1
            continue
        comp = fm.get("complexity") or "unknown"
        if comp not in _COMPLEXITY_BUCKETS:
            comp = "unknown"
        status = fm.get("status") or "unknown"
        if status not in _STATUS_BUCKETS:
            status = "unknown"
        summary["by_complexity"][comp] += 1
        summary["by_status"][status] += 1
    return summary


def render(summary: dict) -> str:
    lines = [f"total: {summary['total']}", "by_complexity:"]
    for k in _COMPLEXITY_BUCKETS:
        lines.append(f"  {k}: {summary['by_complexity'][k]}")
    lines.append("by_status:")
    for k in _STATUS_BUCKETS:
        lines.append(f"  {k}: {summary['by_status'][k]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="汇总 tasks/ 目录 frontmatter 维度统计")
    parser.add_argument("tasks_dir", help="tasks 目录路径")
    args = parser.parse_args(argv)
    tasks_dir = Path(args.tasks_dir).resolve()
    if not tasks_dir.is_dir():
        print(f"❌ tasks_dir 不存在或非目录：{tasks_dir}", file=sys.stderr)
        return 1
    summary = summarize(tasks_dir)
    print(render(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
