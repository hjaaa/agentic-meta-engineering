"""process.txt 单一写入通道 CLI——封装时间戳取值 + tag 白名单校验 + append-only 安全。

背景：
  Skill `requirement-progress-logger` 规定 `[save] / [phase-transition] / [blocker] /
  [blocker-resolved] / [review:*] / [gate:*]` 等 AI 自律拼接的事件必须取 Asia/Shanghai now
  + tag 必须在白名单内。原方案"AI 直接 printf >>"无强制约束，已发生时间倒流案例
  （`requirements/20260521-archive-runner-auto-pr/process.txt` 2026-05-21 phase-transition
  时间戳手填 `15:08:00`，晚于后续 [save] 的真实 `15:04:29`）。

  本 CLI 把时间戳取值收紧到脚本控制，与 archive_runner._append_process_event /
  submit_codex._append_process_event 同步使用 `_CST = timezone(timedelta(hours=8))`。

用法：
  python3 scripts/lib/log_process.py \\
    --req 20260521-archive-runner-auto-pr \\
    --tag save \\
    "definition 阶段 2 轮 review 通过"

  python3 scripts/lib/log_process.py \\
    --req 20260521-archive-runner-auto-pr \\
    --tag review:approved \\
    "REV-...-002 looks_clean@b0f4762"

事件 tag 白名单（与 .claude/skills/requirement-progress-logger/SKILL.md 同步）：
  phase-transition / save / blocker / blocker-resolved
  review:approved / review:needs_revision / review:rejected
  gate:pass / gate:fail
  archived / codex-review-triggered / codex-review-received

退出码：
  0 — 成功
  1 — 参数/校验错误（tag 不在白名单 / req 目录不存在 / 消息含 CR/LF 等）
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# Asia/Shanghai 时区常量（与 archive_runner._CST / submit_codex._CST 同步，time-format.md 统一约束）
_CST = timezone(timedelta(hours=8))

# tag 白名单——正则匹配支持冒号 sub-form（review:approved 等）
_TAG_PATTERN = re.compile(
    r"^("
    r"phase-transition"
    r"|save"
    r"|blocker|blocker-resolved"
    r"|review:(approved|needs_revision|rejected)"
    r"|gate:(pass|fail)"
    r"|archived"
    r"|codex-review-triggered|codex-review-received"
    r")$"
)


def _now_str() -> str:
    """返回当前 Asia/Shanghai 时间字符串（`YYYY-MM-DD HH:MM:SS`，不含 offset）。

    与 archive_runner._now_str / submit_codex._now_str 同格式（time-format.md 约束）。
    """
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def _validate_message(message: str) -> str:
    """清理 + 校验消息体。

    - strip CR / LF（防 process.txt 多行注入，与 save_review_validation 同策略）
    - 拒绝空消息
    """
    if message is None:
        raise ValueError("message must not be None")
    cleaned = message.replace("\r", "").replace("\n", " ").strip()
    if not cleaned:
        raise ValueError("message must be non-empty after stripping CR/LF/whitespace")
    return cleaned


def append_event(req_id: str, tag: str, message: str) -> str:
    """对外 API：追加一行到 requirements/<req_id>/process.txt。

    返回写入的完整行（不含末尾换行），便于调用方回显。
    """
    if not _TAG_PATTERN.match(tag):
        raise ValueError(
            f"tag {tag!r} 不在白名单（phase-transition / save / blocker / blocker-resolved "
            f"/ review:(approved|needs_revision|rejected) / gate:(pass|fail) / archived "
            f"/ codex-review-triggered / codex-review-received）"
        )
    cleaned_message = _validate_message(message)

    req_dir = REQUIREMENTS_DIR / req_id
    if not req_dir.is_dir():
        raise FileNotFoundError(f"需求目录不存在：{req_dir}")

    process_path = req_dir / "process.txt"
    line = f"{_now_str()} [{tag}] {cleaned_message}"
    with process_path.open("a", encoding="utf-8") as fp:
        fp.write(line + "\n")
    return line


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="append semantic event line to requirements/<id>/process.txt",
    )
    parser.add_argument("--req", required=True, help="REQ-YYYY-NNN 或 YYYYMMDD-slug")
    parser.add_argument(
        "--tag",
        required=True,
        help="事件 tag（见白名单：phase-transition / save / blocker / blocker-resolved / review:* / gate:*）",
    )
    parser.add_argument("message", help="事件描述")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        line = append_event(args.req, args.tag, args.message)
    except (ValueError, FileNotFoundError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    print(f"✓ {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
