#!/usr/bin/env python3
"""append_process.py — 追加语义事件到 requirements/<id>/process.txt。

被 standard-8phase.yaml 的 phase-to-* / archive-finalize 等节点的 bash 调用。

用法：
    python3 scripts/lib/append_process.py "<event_line>"

run_id 推断（优先级）：
    1. env $RUN_ID（workflow_dispatcher 注入）
    2. 当前 cwd 路径片段中的 requirements/<id>/...

格式：
    `YYYY-MM-DD HH:MM:SS <event_line>\n`（时区 Asia/Shanghai，对齐 time-format.md）

并发：
    单原子段 LOCK_EX（POSIX）；Windows 退化（archive_runner 同模式）。

退出码：
    0  成功追加
    1  参数缺失 / 推断不到 run_id / process.txt 父目录不存在
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_DIR = REPO_ROOT / "requirements"
_CST = timezone(timedelta(hours=8))


def _now_cst_str() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def _resolve_run_id() -> str:
    """优先 env $RUN_ID；否则从 cwd 推断（cwd 在 requirements/<id>/ 之下时取 <id>）。"""
    env_id = os.environ.get("RUN_ID", "").strip()
    if env_id:
        return env_id
    cwd = Path.cwd().resolve()
    try:
        rel = cwd.relative_to(REQUIREMENTS_DIR)
    except ValueError:
        # cwd 不在 REQUIREMENTS_DIR 之下，尝试 cwd 上下任意层级中的 requirements/<id>/
        for parent in [cwd, *cwd.parents]:
            try:
                rel = parent.relative_to(REQUIREMENTS_DIR)
                break
            except ValueError:
                continue
        else:
            return ""
    parts = rel.parts
    return parts[0] if parts else ""


def _try_lock_exclusive(fh) -> None:
    """POSIX：fcntl.flock LOCK_EX；其他平台静默放弃（与 archive_runner 同语义）。"""
    try:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except (ImportError, OSError):
        pass


def append_event(req_id: str, event_line: str) -> None:
    """主入口：追加一行到 requirements/<req_id>/process.txt。"""
    process_path = REQUIREMENTS_DIR / req_id / "process.txt"
    if not process_path.parent.exists():
        print(
            f"❌ requirements/{req_id}/ 不存在；run_id 是否正确？",
            file=sys.stderr,
        )
        raise SystemExit(1)
    full_line = f"{_now_cst_str()} {event_line}\n"
    with process_path.open("a", encoding="utf-8") as f:
        _try_lock_exclusive(f)
        f.write(full_line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="追加语义事件到 requirements/<id>/process.txt",
    )
    parser.add_argument("event_line", help="事件描述（一行）")
    parser.add_argument(
        "--run",
        help="显式 run_id；不传则按 $RUN_ID / cwd 推断",
        default=None,
    )
    args = parser.parse_args(argv)
    req_id = (args.run or "").strip() or _resolve_run_id()
    if not req_id:
        print(
            "❌ 推断不到 run_id；请通过 --run、$RUN_ID 或在 requirements/<id>/ 子树下运行",
            file=sys.stderr,
        )
        return 1
    append_event(req_id, args.event_line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
