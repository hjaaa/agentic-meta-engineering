#!/usr/bin/env bash
# PreToolUse hook: 阻止在受保护分支上直接做写操作
set -euo pipefail

# 受保护分支可通过环境变量覆盖
PROTECTED=${CLAUDE_PROTECTED_BRANCHES:-"main,master"}

# 获取工具名：优先环境变量（便于测试），否则解析 stdin JSON
TOOL=${CLAUDE_HOOK_TOOL_NAME:-}
if [ -z "$TOOL" ] && [ ! -t 0 ]; then
    # stdin 非 tty（被管道喂数据）时解析 JSON
    STDIN=$(cat)
    TOOL=$(echo "$STDIN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
fi

# 非写工具直接放行
case "$TOOL" in
    Edit|Write|MultiEdit) ;;
    Bash)
        exit 0
        ;;
    *) exit 0 ;;
esac

# 取当前分支
BRANCH=$(git branch --show-current 2>/dev/null || echo "")
if [ -z "$BRANCH" ]; then
    exit 0  # 不在 git 仓库，放行
fi

# 分支匹配检查
IFS=',' read -ra BRANCHES <<< "$PROTECTED"
for b in "${BRANCHES[@]}"; do
    if [ "$BRANCH" = "$b" ]; then
        echo "❌ 禁止在受保护分支 [$BRANCH] 上直接写操作。" >&2
        echo "   请先切换到 feature 分支：/requirement:new 会自动建分支" >&2
        exit 2
    fi
done

exit 0
