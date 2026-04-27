#!/usr/bin/env bash
# save-review.sh — review JSON 写入通道
#
# 用法：
#   bash scripts/save-review.sh \
#     --req REQ-2026-001 \
#     --phase definition \
#     --reviewer requirement-quality-reviewer \
#     [--scope feature_id=F-001] \
#     < verdict.json
#
# 详见：context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md §4

set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec python3 "$SCRIPT_DIR/lib/save_review.py" "$@"
