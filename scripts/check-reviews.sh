#!/usr/bin/env bash
# check-reviews.sh — reviewer verdict 门禁校验
#
# 用法：
#   bash scripts/check-reviews.sh \
#     --req REQ-2026-001 \
#     --target-phase tech-research \
#     [--strict]
#
# 详见：context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md §5

set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$SCRIPT_DIR/lib/check_reviews.py" "$@"
