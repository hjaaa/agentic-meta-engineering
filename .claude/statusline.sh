#!/usr/bin/env bash
# StatusLine: [REQ-ID·阶段中文·N/8] 分支 ⬆ N ahead | 🤖 模型
set -uo pipefail

# 阶段英文 → 中文 + 序号
phase_info() {
    case "$1" in
        bootstrap)       echo "初始化·1/8" ;;
        definition)      echo "需求定义·2/8" ;;
        tech-research)   echo "技术预研·3/8" ;;
        outline-design)  echo "概要设计·4/8" ;;
        detail-design)   echo "详细设计·5/8" ;;
        task-planning)   echo "任务规划·6/8" ;;
        development)     echo "开发实施·7/8" ;;
        testing)         echo "测试验收·8/8" ;;
        *)               echo "未知·?/8" ;;
    esac
}

BRANCH=$(git branch --show-current 2>/dev/null || echo "")

# 查找匹配需求
REQ_ID=""; PHASE=""
if [ -n "$BRANCH" ]; then
    for meta in requirements/*/meta.yaml; do
        [ -f "$meta" ] || continue
        MB=$(grep -E '^branch:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
        if [ "$MB" = "$BRANCH" ]; then
            REQ_ID=$(grep -E '^id:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
            PHASE=$(grep -E '^phase:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
            break
        fi
    done
fi

# 领先 commit 数
AHEAD=0
if git remote get-url origin > /dev/null 2>&1; then
    AHEAD=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)
fi

# 模型（从 CLAUDE_MODEL 环境变量，默认 sonnet）
MODEL=${CLAUDE_MODEL:-sonnet}

# 组装
if [ -n "$REQ_ID" ] && [ -n "$PHASE" ]; then
    PI=$(phase_info "$PHASE")
    LEFT="[${REQ_ID}·${PI}]"
else
    LEFT="[no-requirement]"
fi

AHEAD_PART=""
[ "$AHEAD" != "0" ] && AHEAD_PART=" ⬆ ${AHEAD} ahead"

echo "${LEFT} ${BRANCH:-detached}${AHEAD_PART}  |  🤖 ${MODEL}"
