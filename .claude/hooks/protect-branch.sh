#!/usr/bin/env bash
# PreToolUse hook：
#   1) 阻止在受保护分支（main / master / develop）上直接做 Edit / Write / MultiEdit
#   2) 任何分支下，阻止直接 Edit / Write / MultiEdit 命中 requirements/*/reviews/*.json
#      （这是 save-review.sh / check-reviews.sh 的唯一写入通道，禁止主对话 LLM 直接 Edit）
set -euo pipefail

# 受保护分支可通过环境变量覆盖
PROTECTED=${CLAUDE_PROTECTED_BRANCHES:-"main,master,develop"}

# 取工具名 + 目标路径：优先环境变量（便于测试），否则解析 stdin JSON
TOOL=${CLAUDE_HOOK_TOOL_NAME:-}
TARGET_PATH=${CLAUDE_HOOK_FILE_PATH:-}
if { [ -z "$TOOL" ] || [ -z "$TARGET_PATH" ]; } && [ ! -t 0 ]; then
    STDIN=$(cat)
    if [ -z "$TOOL" ]; then
        TOOL=$(echo "$STDIN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
    fi
    if [ -z "$TARGET_PATH" ]; then
        TARGET_PATH=$(echo "$STDIN" | python3 -c "
import json, sys
d = json.load(sys.stdin)
inp = d.get('tool_input', {}) or {}
print(inp.get('file_path') or inp.get('path') or '', end='')
" 2>/dev/null || echo "")
    fi
fi

# 非写工具直接放行
case "$TOOL" in
    Edit|Write|MultiEdit) ;;
    Bash)
        exit 0
        ;;
    *) exit 0 ;;
esac

# 路径级拦截：reviews/*.json 是 save-review.sh 的唯一写入通道，禁止直接编辑（任何分支）
if [ -n "$TARGET_PATH" ]; then
    case "$TARGET_PATH" in
        */requirements/*/reviews/*.json|requirements/*/reviews/*.json)
            echo "❌ 禁止直接 Edit/Write [$TARGET_PATH]" >&2
            echo "   reviews/*.json 是 save-review.sh 的唯一写入通道。" >&2
            echo "   如要修订评审结论，请让 reviewer Agent 重新评审（supersedes 链）。" >&2
            exit 2
            ;;
    esac
fi

# 取当前分支
BRANCH=$(git branch --show-current 2>/dev/null || echo "")
if [ -z "$BRANCH" ]; then
    exit 0  # 不在 git 仓库，放行
fi

# 受保护分支匹配检查
IFS=',' read -ra BRANCHES <<< "$PROTECTED"
for b in "${BRANCHES[@]}"; do
    if [ "$BRANCH" = "$b" ]; then
        echo "❌ 禁止在受保护分支 [$BRANCH] 上直接写操作。" >&2
        echo "   请先切换到 feature 分支：/requirement:new 会自动建分支" >&2
        exit 2
    fi
done

exit 0
