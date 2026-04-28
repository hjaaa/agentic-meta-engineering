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
# F-005 round-2：导出当前 PID 给后代进程，bash_write_protect.py 用此 env 比对 ppid 链，
# 替代脆弱的 comm 字符串匹配（防止伪造 save-review.sh 命名绕过白名单）
export SAVE_REVIEW_PID=$$
exec python3 "$SCRIPT_DIR/lib/save_review.py" "$@"
