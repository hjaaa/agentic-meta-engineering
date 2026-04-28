#!/usr/bin/env bash
# pre-tool-use trigger 入口（Claude Code PreToolUse Hook 调用）。
#
# 来源：requirements/REQ-2026-002/artifacts/detailed-design.md §4.3（行 425-439）
#
# 职责：
#   1) 解析 stdin 的 PreToolUse JSON：{"tool_name":"...", "tool_input":{...}}
#   2) 提取 tool_name / file_path / command 注入环境变量（plugin 通过 ctx.extra 读取）
#   3) 调 python3 scripts/gates/run.py --trigger=pre-tool-use
#   4) 退出码：0 放行 / 2 阻断（Hook 协议）
#
# 设计要点：
#   - 不在 shell 里做正则判断，所有规则下沉到 plugins（GATE-PROTECT-BRANCH /
#     GATE-BASH-WRITE-PROTECT）
#   - 环境变量传递：CLAUDE_HOOK_TOOL_NAME / CLAUDE_HOOK_FILE_PATH /
#     CLAUDE_HOOK_COMMAND（runner 走 build_context 注入到 ctx.extra）

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATES_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${GATES_DIR}/../.." && pwd)"

# 优先使用环境变量（便于测试 / 旧 hook 兼容），否则解析 stdin JSON
TOOL="${CLAUDE_HOOK_TOOL_NAME:-}"
TARGET_PATH="${CLAUDE_HOOK_FILE_PATH:-}"
COMMAND="${CLAUDE_HOOK_COMMAND:-}"

# F-017：合并三次 python3 -c 为单次调用（实测高频路径节省 ~49ms）
# Python 输出三行：tool / file_path / command（空字符串保留为空行）
# F-032：去 2>/dev/null，让 Python 解析失败信息打到 hook stderr，避免协议漂移无声通过
if [ ! -t 0 ] && { [ -z "$TOOL" ] || [ -z "$TARGET_PATH" ] || [ -z "$COMMAND" ]; }; then
    STDIN=$(cat)
    if [ -n "$STDIN" ]; then
        PARSED=$(printf '%s' "$STDIN" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {}) or {}
    sys.stdout.write(d.get('tool_name', '') + '\n')
    sys.stdout.write((inp.get('file_path') or inp.get('path') or '') + '\n')
    sys.stdout.write(inp.get('command', '') + '\n')
except Exception as exc:
    sys.stderr.write(f'WARNING pre_tool_use.sh JSON 解析失败: {exc}\n')
    sys.stdout.write('\n\n\n')
" || printf '\n\n\n')
        # 用 IFS=$'\n' + read 拆分前三行（command 字段可能含换行，仅取首行；
        # 当前 PreToolUse 协议下 command 不含 \n，详设 §4.3 已确认）
        P_TOOL=$(printf '%s\n' "$PARSED" | sed -n '1p')
        P_PATH=$(printf '%s\n' "$PARSED" | sed -n '2p')
        P_CMD=$(printf '%s\n' "$PARSED" | sed -n '3p')
        [ -z "$TOOL" ] && TOOL="$P_TOOL"
        [ -z "$TARGET_PATH" ] && TARGET_PATH="$P_PATH"
        [ -z "$COMMAND" ] && COMMAND="$P_CMD"
    fi
fi

# 注入到环境变量供 runner build_context 读取
export CLAUDE_HOOK_TOOL_NAME="$TOOL"
export CLAUDE_HOOK_FILE_PATH="$TARGET_PATH"
export CLAUDE_HOOK_COMMAND="$COMMAND"

cd "$REPO_ROOT"
# F-001：修正 Hook 阻断协议
# Claude Code PreToolUse Hook 协议：exit 0 = 放行；exit 2 = 阻断；其他 = non-blocking 警告
# run.py 在 gate fail 时返回 1（非阻断），需翻译为 exit 2 才能真正拦截 Bash 写入
python3 scripts/gates/run.py --trigger=pre-tool-use
rc=$?
if [ "$rc" -eq 0 ]; then
    exit 0
else
    exit 2
fi
