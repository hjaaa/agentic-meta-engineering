#!/usr/bin/env bash
# PostToolUse hook: 追加工具级进度日志
#
# 日志布局（由 meta.yaml 的 log_layout 字段控制）：
#   - split（v2 默认）：工具日志写 process.tool.log，语义事件由 Skill 写 process.txt
#   - legacy / 缺字段：工具日志写 process.txt（老需求兼容）
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

# 读 log_layout，决定写入目标
LAYOUT=$(grep -E '^log_layout:' "$REQ_DIR/meta.yaml" 2>/dev/null | head -1 | awk '{print $2}')
case "${LAYOUT:-legacy}" in
    split) LOG_FILE="$REQ_DIR/process.tool.log" ;;
    *)     LOG_FILE="$REQ_DIR/process.txt" ;;
esac

# 追加日志
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "$TS [$PHASE] tool=$TOOL" >> "$LOG_FILE"

exit 0
