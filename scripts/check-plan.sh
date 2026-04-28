#!/usr/bin/env bash
# check-plan.sh —— plan.md 新鲜度 + 非占位符软校验入口（薄壳兼容层）
#
# 本脚本是薄壳 exec runner，直接委托统一门禁 runner（adapter 模式）。
# 兼容期保留，F-004 阶段才删除旧入口。
#
# 用法（不变）：
#   bash scripts/check-plan.sh requirements/REQ-2026-001
#   bash scripts/check-plan.sh --requirement REQ-2026-001
#   bash scripts/check-plan.sh --all
#   bash scripts/check-plan.sh --all --strict
#
# 退出码：
#   0 — 通过（warning 允许存在；--strict 下视为失败）
#   1 — 存在 error（或 --strict 下存在 warning）
#   2 — 脚本自身异常
#
# 事实源：
#   context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md §6.2
#   .claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 薄壳 exec runner（adapter 模式）：委托统一门禁 runner，保持旧入口行为等价
exec python3 "${SCRIPT_DIR}/gates/run.py" --trigger=adapter --legacy=check-plan "$@"
