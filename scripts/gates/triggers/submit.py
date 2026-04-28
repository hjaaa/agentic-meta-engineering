"""submit trigger 入口（H3）：把 /requirement:submit 的"前置门禁"统一委托给 run.py。

来源：requirements/REQ-2026-002/artifacts/detailed-design.md §4.2（行 411-423）。

设计要点：
  - 复用 phase-transition gate 集合（registry.yaml 里 triggers 含 'submit' 的全部条目）
  - 在 submit 上额外挂 GATE-PR-MERGED-STATE（已在 H4 完成）
  - 本文件只负责门禁通道；push / open PR 等 git 动作仍由 .claude/commands/requirement/submit.md
    的 Bash 步骤承担

用法：
  python scripts/gates/triggers/submit.py --req=REQ-2026-002
  python scripts/gates/triggers/submit.py --req=REQ-2026-002 --force-with-blockers
  python scripts/gates/triggers/submit.py --req=REQ-2026-002 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

# 把 scripts/gates 加入 import 路径，复用 run.py 的 main()
_TRIGGER_DIR = Path(__file__).resolve().parent
_GATES_DIR = _TRIGGER_DIR.parent
if str(_GATES_DIR) not in sys.path:
    sys.path.insert(0, str(_GATES_DIR))

import run as runner  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="submit trigger（统一调 run.py）")
    p.add_argument("--req", dest="requirement_id", required=True, help="需求 ID，如 REQ-2026-002")
    p.add_argument(
        "--force-with-blockers",
        action="store_true",
        help="允许在有 blocker 级审查问题时仍开 PR（透传给 runner，由 escape_hatch 校验）",
    )
    p.add_argument("--strict", action="store_true", help="warning 也视为失败")
    p.add_argument("--dry-run", action="store_true", help="只打印执行计划，不跑 gate")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """submit 门禁通道入口。

    返回：runner exit code（0 通过 / 1 含 error 失败 / 2 自身异常）。
    """
    args = parse_args(argv if argv is not None else sys.argv[1:])

    runner_argv = [
        "--trigger=submit",
        f"--req={args.requirement_id}",
    ]
    if args.strict:
        runner_argv.append("--strict")
    if args.dry_run:
        runner_argv.append("--dry-run")

    # NOTE：--force-with-blockers 是流程级 escape_hatch（registry.yaml escape_hatches[1]）；
    # 当前 runner 还未实现 escape_hatch 的 CLI 解析层，先把开关透传到 env，
    # F-004 落地 escape_hatch CLI 后再切到 --force-with-blockers 标志。
    # 此处为占位实现，确保 H3 通道打通，不影响下游接入。
    if args.force_with_blockers:
        import os
        os.environ.setdefault("CLAUDE_GATES_FORCE_WITH_BLOCKERS", "1")

    return runner.main(runner_argv)


if __name__ == "__main__":
    sys.exit(main())
