"""submit trigger 入口（H3）：把 /requirement:submit 的"前置门禁"统一委托给 run.py。

来源：requirements/REQ-2026-002/artifacts/detailed-design.md §4.2（行 411-423）。

设计要点：
  - 复用 phase-transition gate 集合（registry.yaml 里 triggers 含 'submit' 的全部条目）
  - 在 submit 上额外挂 GATE-PR-MERGED-STATE（已在 H4 完成）
  - 本文件只负责门禁通道；push / open PR 等 git 动作仍由 .claude/commands/requirement/submit.md
    的 Bash 步骤承担

用法：
  python scripts/gates/triggers/submit.py --req=REQ-2026-002
  python scripts/gates/triggers/submit.py --req=REQ-2026-002 --force-with-blockers='临时绕过：已有 Jira 跟进'
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
    """解析 submit trigger 的 CLI 参数。

    参数：argv — argparse 入参列表。
    返回：argparse.Namespace 含 requirement_id / force_with_blockers / strict / dry_run。
    支持的 flag：
      --req                  需求 ID（必填，如 REQ-2026-002）
      --force-with-blockers  允许 blocker 级审查问题仍开 PR；必须提供非空 reason，
                             与 run.py 协议一致（F-004 round-3 G-1 在 runner 落地校验）。
                             round-5 修复：原本只 set env var 不传给 runner（Codex P1 bug），
                             现在直接透传 --force-with-blockers='<reason>' 给 runner argv。
      --strict               warning 也视为失败
      --dry-run              只打印执行计划，不跑 gate
    """
    p = argparse.ArgumentParser(description="submit trigger（统一调 run.py）")
    p.add_argument("--req", dest="requirement_id", required=True, help="需求 ID，如 REQ-2026-002")
    # F-004：推荐别名（与 run.py 同款双 dest 模式）
    p.add_argument(
        "--bypass-review-blockers",
        dest="force_with_blockers",
        default=None,
        metavar="REASON",
        help=(
            "（推荐）允许 review-verdict tag 类失败仍开 PR；不放行 workspace_clean 等非 review 类失败。"
            "必须提供非空 reason；透传给 runner（run.py:_validate_force_reason）"
        ),
    )
    p.add_argument(
        "--force-with-blockers",
        dest="force_with_blockers",
        default=None,
        metavar="REASON",
        help="[DEPRECATED 2026-11-01] 等价于 --bypass-review-blockers",
    )
    p.add_argument(
        "--target",
        dest="target",
        default=None,
        metavar="BRANCH",
        help="目标 base 分支，覆盖 meta.base_branch（透传给 runner --target）",
    )
    p.add_argument("--strict", action="store_true", help="warning 也视为失败")
    p.add_argument("--dry-run", action="store_true", help="只打印执行计划，不跑 gate")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """submit 门禁通道入口。

    返回：runner exit code（0 通过 / 1 含 error 失败 / 2 自身异常）。

    F-004 round-5（Codex P1 修复）：
      原实现把 --force-with-blockers 转为 CLAUDE_GATES_FORCE_WITH_BLOCKERS env var，
      但 run.py 既不读这个 env 也不接受 boolean 形式 → escape_hatch 在 submit 入口完全
      非功能性。现修为直接 forward `--force-with-blockers='<reason>'` 到 runner argv，
      与 `python scripts/gates/run.py --trigger=submit ...` 直接调用路径一致。
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
    if args.force_with_blockers is not None:
        # F-004 round-5：直接透传给 runner（含 reason），由 run.py:_validate_force_reason
        # 做三段校验（非空 / ≤1024 / 控制字符过滤）。runner 校验失败时返回 2。
        # F-004（FG-004）：推荐别名走同 dest，runner 处通过 raw argv 检测旧名打 deprecation。
        runner_argv.append(f"--bypass-review-blockers={args.force_with_blockers}")
    if args.target is not None:
        # F-004：透传 --target 给 runner；base_reachable / ahead_of_origin 优先用此值
        runner_argv.append(f"--target={args.target}")

    return runner.main(runner_argv)


if __name__ == "__main__":
    sys.exit(main())
