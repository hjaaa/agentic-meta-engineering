#!/usr/bin/env bash
# check-plan.sh —— plan.md 新鲜度 + 非占位符软校验入口
#
# 用法：
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
exec python3 "${SCRIPT_DIR}/lib/check_plan.py" "$@"
