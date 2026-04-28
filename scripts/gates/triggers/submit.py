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
import os
import sys
from pathlib import Path
from typing import Optional

# 把 scripts/gates 加入 import 路径，复用 run.py 的 main()
_TRIGGER_DIR = Path(__file__).resolve().parent
_GATES_DIR = _TRIGGER_DIR.parent
if str(_GATES_DIR) not in sys.path:
    sys.path.insert(0, str(_GATES_DIR))

import run as runner  # noqa: E402

# F-023 round-2：env 变量名抽常量，便于 try/finally 引用
_FORCE_WITH_BLOCKERS_ENV = "CLAUDE_GATES_FORCE_WITH_BLOCKERS"


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析 submit trigger 的 CLI 参数（F-015 round-2 加 docstring）。

    参数：argv — argparse 入参列表。
    返回：argparse.Namespace 含 requirement_id / force_with_blockers / strict / dry_run。
    支持的 flag：
      --req               需求 ID（必填，如 REQ-2026-002）
      --force-with-blockers  允许 blocker 级审查问题仍开 PR（F-004 落地 CLI 解析；
                              当前转 env 占位，runner 不读，详见 main 内注释）
      --strict            warning 也视为失败
      --dry-run           只打印执行计划，不跑 gate
    """
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

    F-020 / F-023 round-2：
      --force-with-blockers 是流程级 escape_hatch 占位实现（registry.yaml
      escape_hatches[force-with-blockers]）；F-004 才在 runner 落地 CLI 解析与
      audit 写入。本轮转为 env 透传，**用 try/finally 在调用结束后 pop**，
      避免同进程多次调用 main 时环境变量永久驻留污染下次执行。
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

    # F-023：try/finally 包裹 env 注入，确保多次调用不残留
    set_by_us = False
    if args.force_with_blockers and _FORCE_WITH_BLOCKERS_ENV not in os.environ:
        os.environ[_FORCE_WITH_BLOCKERS_ENV] = "1"
        set_by_us = True
    try:
        return runner.main(runner_argv)
    finally:
        if set_by_us:
            os.environ.pop(_FORCE_WITH_BLOCKERS_ENV, None)


if __name__ == "__main__":
    sys.exit(main())
