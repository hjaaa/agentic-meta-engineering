"""audit_flush.py：把 audit/.queue/*.log 汇总到 audit/<YYYY-MM>/<entry>-<YYYY-MM-DD>.json。

设计来源：requirements/REQ-2026-006/artifacts/detailed-design.md §4.3。

职责：
  1. _collect_logs：收集 audit/.queue/*.log 文件列表
  2. _parse_lines：解析日志行，按 entry 分桶
  3. _dispatch：协调解析 → 写桶 → 归档流程（持有进程级 flock，防并发重复写）
  4. _write_buckets：把分桶数据 append 到 audit/<YYYY-MM>/<entry>-<YYYY-MM-DD>.json
  5. _archive_logs：mv 已处理 .log 到 audit/.queue.done/<YYYY-MM-DD>/（同名加 .dup<N>）

设计约束（F-004 §4.3）：
  - 仅 stdlib（pathlib/json/shutil/datetime/argparse/re/fcntl）
  - 任何步骤失败完全静默 → main 永不抛，返回 0
  - 支持 --dry-run 仅打印计划不动文件
  - 解析用 rsplit(" @ entry=", 1) 兼容 event 段含 @ entry= 字面量（评审 -002 minor）
  - 同日多次 flush 走 append，不去重不覆盖
  - entry 字段白名单校验：^[A-Za-z0-9:_-]+$，不合法整行跳过（防路径穿越 F-1）
  - _dispatch 入口 fcntl.LOCK_EX|LOCK_NB，拿不到锁立即 return（防并发重复 F-5）
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Any

# entry 字段白名单：匹配 spec D-006 的 ENTRY_* 命名约束
# 允许字母、数字、冒号、下划线、连字符（如 runner / trigger:submit / pre-tool-use-guard）
# 用模块级缓存避免每行重新编译
_ENTRY_RE = re.compile(r"^[A-Za-z0-9:_-]+$")

# 仓库根（scripts/lib/ 的父目录的父目录）
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_QUEUE_DIR = _REPO_ROOT / "audit" / ".queue"
_QUEUE_DONE_DIR = _REPO_ROOT / "audit" / ".queue.done"
_AUDIT_DIR = _REPO_ROOT / "audit"


def _collect_logs(queue_dir: Path) -> list[Path]:
    """收集 audit/.queue/*.log 文件列表；目录不存在时返回空列表。"""
    if not queue_dir.is_dir():
        return []
    return sorted(queue_dir.glob("*.log"))


def _parse_lines(log_file: Path) -> list[dict[str, Any]]:
    """解析单个 .log 文件，返回已解析的 entry 记录列表。

    行格式：<ISO ts> <cwd> <event-line> @ entry=<entry>
    用 rsplit 切分以兼容 event 段本身含 '@ entry=' 字面量（评审 -002 minor）。
    解析失败的行跳过（不抛异常）。
    """
    records: list[dict[str, Any]] = []
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return records

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            # 用 rsplit 从右侧切分，兼容 event 段含 @ entry= 的情况
            left, entry = line.rsplit(" @ entry=", 1)
            entry = entry.strip()
            # 白名单校验：entry 仅允许字母/数字/冒号/下划线/连字符
            # 不合法（含 / 或 .. 等路径字符）直接跳过整行，防路径穿越（F-1）
            if not _ENTRY_RE.match(entry):
                continue
            # left: <ISO ts> <cwd> <event-line>
            parts = left.split(" ", 2)
            if len(parts) < 2:
                continue
            ts_str = parts[0]
            # 提取日期（ISO 时间戳格式 YYYY-MM-DDTHH:MM:SS）
            try:
                record_date = datetime.fromisoformat(ts_str).date()
            except ValueError:
                record_date = date.today()
            records.append({
                "entry": entry,
                "date": record_date,
                "raw": line,
                "ts": ts_str,
            })
        except (ValueError, IndexError):
            # 解析失败跳过此行
            continue
    return records


def _write_buckets(
    buckets: dict[str, dict[date, list[str]]],
    audit_dir: Path,
    dry_run: bool,
) -> None:
    """把分桶数据 append 写入 audit/<YYYY-MM>/<entry>-<YYYY-MM-DD>.json。

    同日多次 flush 走 append 模式（不去重不覆盖）。
    """
    for entry, date_map in buckets.items():
        for record_date, raw_lines in date_map.items():
            yyyy_mm = record_date.strftime("%Y-%m")
            fname = f"{entry}-{record_date.strftime('%Y-%m-%d')}.json"
            out_path = audit_dir / yyyy_mm / fname
            if dry_run:
                print(f"[dry-run] would append {len(raw_lines)} records → {out_path}")
                continue
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with out_path.open("a", encoding="utf-8") as f:
                    for raw in raw_lines:
                        f.write(raw + "\n")
            except Exception:
                # 写入失败静默跳过
                pass


def _archive_logs(
    log_files: list[Path],
    queue_done_dir: Path,
    archive_date: date,
    dry_run: bool,
) -> None:
    """mv 已处理 .log 到 audit/.queue.done/<YYYY-MM-DD>/，同名文件加 .dup<N>。"""
    done_dir = queue_done_dir / archive_date.strftime("%Y-%m-%d")
    if dry_run:
        for f in log_files:
            print(f"[dry-run] would archive {f.name} → {done_dir}/")
        return
    try:
        done_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    for src in log_files:
        dest = done_dir / src.name
        if dest.exists():
            # 同名文件加 .dup<N>
            n = 1
            while True:
                dup_dest = done_dir / f"{src.name}.dup{n}.log"
                if not dup_dest.exists():
                    dest = dup_dest
                    break
                n += 1
        try:
            shutil.move(str(src), str(dest))
        except Exception:
            # 归档失败静默跳过
            pass


def _dispatch(
    queue_dir: Path,
    audit_dir: Path,
    queue_done_dir: Path,
    dry_run: bool,
) -> None:
    """协调：收集 → 解析 → 写桶 → 归档。任何步骤失败静默继续。

    进程级排他锁（F-5）：
      - 锁文件：audit/.queue/.flush.lock
      - 使用 fcntl.LOCK_EX | LOCK_NB（非阻塞）
      - 拿不到锁说明另一个 flush 进程正在运行，直接 return 0（D-005 best-effort）
      - with 块退出时自动释放锁，无需手动 unlock
    """
    # 确保 queue_dir 存在再建锁文件（queue_dir 不存在时 _collect_logs 也会返回空）
    try:
        queue_dir.mkdir(parents=True, exist_ok=True)
        lock_path = queue_dir / ".flush.lock"
        lock_fh = lock_path.open("w", encoding="utf-8")
    except Exception:
        # 无法创建锁文件时静默 return，D-005 best-effort
        return

    try:
        # 非阻塞排他锁：拿不到锁说明另一个 flush 进程正在执行
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        # 另一个进程持有锁，本次静默跳过（不重复写）
        lock_fh.close()
        return

    try:
        log_files = _collect_logs(queue_dir)
        if not log_files:
            return

        # 按 entry × date 分桶
        buckets: dict[str, dict[date, list[str]]] = defaultdict(lambda: defaultdict(list))
        for log_file in log_files:
            records = _parse_lines(log_file)
            for rec in records:
                buckets[rec["entry"]][rec["date"]].append(rec["raw"])

        _write_buckets(buckets, audit_dir, dry_run)
        _archive_logs(log_files, queue_done_dir, date.today(), dry_run)
    finally:
        # 退出时释放锁（flock 随 fd 关闭自动释放）
        lock_fh.close()


def main(argv: list[str] | None = None) -> int:
    """入口：永不抛异常，返回 0。支持 --dry-run 仅打印计划不动文件。"""
    parser = argparse.ArgumentParser(description="flush audit queue logs to JSON buckets")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印计划，不移动或写入任何文件",
    )
    try:
        args = parser.parse_args(argv)
        _dispatch(
            queue_dir=_QUEUE_DIR,
            audit_dir=_AUDIT_DIR,
            queue_done_dir=_QUEUE_DONE_DIR,
            dry_run=args.dry_run,
        )
    except Exception:  # noqa: BLE001
        # 任何步骤失败完全静默，不影响 SessionEnd hook
        pass
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
