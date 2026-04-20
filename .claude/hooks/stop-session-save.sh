#!/usr/bin/env bash
# Stop hook: 会话结束时打 SESSION_END 标记
set -uo pipefail

BRANCH=$(git branch --show-current 2>/dev/null || echo "")
[ -z "$BRANCH" ] && exit 0

for meta in requirements/*/meta.yaml; do
    [ -f "$meta" ] || continue
    META_BRANCH=$(grep -E '^branch:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
    if [ "$META_BRANCH" = "$BRANCH" ]; then
        REQ_DIR=$(dirname "$meta")
        PHASE=$(grep -E '^phase:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
        TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        echo "$TS [${PHASE:-unknown}] SESSION_END" >> "$REQ_DIR/process.txt"
        break
    fi
done

exit 0
