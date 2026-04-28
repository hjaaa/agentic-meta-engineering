#!/usr/bin/env bash
# check-reviews.sh — reviewer verdict 门禁校验（薄壳兼容层）
#
# 本脚本是薄壳 exec runner，直接委托统一门禁 runner（adapter 模式）。
# 兼容期保留，F-004 阶段才删除旧入口。
#
# 用法（不变）：
#   bash scripts/check-reviews.sh \
#     --req REQ-2026-001 \
#     --target-phase tech-research \
#     [--strict]
#
# 详见：context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md §5

set -euo pipefail
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 薄壳 exec runner（adapter 模式）：委托统一门禁 runner，保持旧入口行为等价
exec python3 "$SCRIPT_DIR/gates/run.py" --trigger=adapter --legacy=check-reviews "$@"
