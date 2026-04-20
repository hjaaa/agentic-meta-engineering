#!/usr/bin/env bash
# PostToolUse hook: 追加进度日志到当前需求的 process.txt
set -uo pipefail

# 获取工具名：优先环境变量，否则解析 stdin JSON
TOOL=${CLAUDE_HOOK_TOOL_NAME:-}
if [ -z "$TOOL" ] && [ ! -t 0 ]; then
    STDIN=$(cat)
    TOOL=$(echo "$STDIN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
fi
TOOL=${TOOL:-unknown}

# 只对写类工具记录
case "$TOOL" in
    Edit|Write|MultiEdit|Bash) ;;
    *) exit 0 ;;
esac

# 取当前分支
BRANCH=$(git branch --show-current 2>/dev/null || echo "")
[ -z "$BRANCH" ] && exit 0

# 反查 requirements/*/meta.yaml 中 branch 字段匹配当前分支的目录
REQ_DIR=""
for meta in requirements/*/meta.yaml; do
    [ -f "$meta" ] || continue
    META_BRANCH=$(grep -E '^branch:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
    if [ "$META_BRANCH" = "$BRANCH" ]; then
        REQ_DIR=$(dirname "$meta")
        break
    fi
done

[ -z "$REQ_DIR" ] && exit 0

# 取当前 phase
PHASE=$(grep -E '^phase:' "$REQ_DIR/meta.yaml" 2>/dev/null | head -1 | awk '{print $2}')
PHASE=${PHASE:-unknown}

# 追加日志
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "$TS [$PHASE] tool=$TOOL" >> "$REQ_DIR/process.txt"

exit 0
