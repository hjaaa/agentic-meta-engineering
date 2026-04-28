#!/usr/bin/env bash
# check-sourcing.sh —— 刨根问底（Source-or-Mark）三态校验入口（薄壳兼容层）
#
# 注意：本脚本已由 F-002 改写为薄壳，直接 exec 统一门禁 runner（adapter 模式）。
#       兼容期保留，F-004 阶段才删除旧入口。
#
# 用法（不变）：
#   bash scripts/check-sourcing.sh requirements/<REQ-ID>/artifacts/requirement.md
#   bash scripts/check-sourcing.sh --requirement <REQ-ID>
#   bash scripts/check-sourcing.sh --all
#   bash scripts/check-sourcing.sh --all --strict
#
# 退出码：
#   0 — 通过
#   1 — 存在 error（或 --strict 下存在 warning）
#   2 — 脚本自身异常
#
# 事实源：
#   context/team/ai-collaboration.md §"规则一：刨根问底（Source-or-Mark）"
#   .claude/skills/requirement-doc-writer/reference/sourcing-rules.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 薄壳 exec runner（adapter 模式）：保持与旧入口行为等价
exec python3 "${SCRIPT_DIR}/lib/check_sourcing.py" "$@"
