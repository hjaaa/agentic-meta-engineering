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

if [ ! -t 0 ]; then
    STDIN=$(cat)
    if [ -n "$STDIN" ]; then
        if [ -z "$TOOL" ]; then
            TOOL=$(printf '%s' "$STDIN" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('tool_name',''), end='')
except Exception:
    pass
" 2>/dev/null || echo "")
        fi
        if [ -z "$TARGET_PATH" ]; then
            TARGET_PATH=$(printf '%s' "$STDIN" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {}) or {}
    print(inp.get('file_path') or inp.get('path') or '', end='')
except Exception:
    pass
" 2>/dev/null || echo "")
        fi
        if [ -z "$COMMAND" ]; then
            COMMAND=$(printf '%s' "$STDIN" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {}) or {}
    print(inp.get('command',''), end='')
except Exception:
    pass
" 2>/dev/null || echo "")
        fi
    fi
fi

# 注入到环境变量供 runner build_context 读取
export CLAUDE_HOOK_TOOL_NAME="$TOOL"
export CLAUDE_HOOK_FILE_PATH="$TARGET_PATH"
export CLAUDE_HOOK_COMMAND="$COMMAND"

cd "$REPO_ROOT"
python3 scripts/gates/run.py --trigger=pre-tool-use
exit $?
