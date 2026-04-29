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
# F-004 round-4：runner syntax 自检 —— 在调用前用 py_compile 静态检查 run.py，
# merge 冲突 marker / 半成品 commit / 误删 import 等"语法级损坏"在此被捕获并 fail-open，
# 避免 chicken-and-egg 死锁（hook 自身依赖 import 中的文件）。开销 ~50ms / Bash 调用。
SYNTAX_ERR=$(mktemp -t gate-runner-syntax.XXXXXX)
if ! python3 -m py_compile scripts/gates/run.py 2>"$SYNTAX_ERR"; then
    echo "WARNING pre-tool-use runner py_compile 失败，fail-open 放行避免锁死工具链（典型场景：merge 冲突 marker / 半成品 commit）：" >&2
    cat "$SYNTAX_ERR" >&2
    rm -f "$SYNTAX_ERR"
    exit 0
fi
rm -f "$SYNTAX_ERR"

# Hook 阻断协议（F-001 立 / F-004 round-4 fail-open 加固）：
# Claude Code PreToolUse Hook 协议：exit 0 = 放行；exit 2 = 阻断；其他 = non-blocking 警告。
# run.py 退出码语义（F-004 round-3 G-5 统一）：
#   0 → 全过 / SKIP / PASS                  → hook exit 0（放行）
#   1 → 业务级 gate FAIL（含 strict warn）  → hook exit 2（阻断，正确语义）
#   2 → runner 自身异常（SyntaxError / registry 加载失败 / 非法 trigger /
#         非法 reason / plugin 抛未捕获异常）→ hook exit 0 + WARNING
#         （fail-open on infra-failure：避免门禁系统反向 brick 工具链——
#          典型场景：merge 冲突期 run.py 含 marker → SyntaxError → 任何工具调用
#          都触发 hook → hook 自身崩溃 → 死锁，无法解冲突。详见
#          context/team/engineering-spec/design-guidance/hook-fail-open.md）
#   其他（130/137 等信号终止）→ 同 rc=2，fail-open
RUNNER_ERR=$(mktemp -t gate-runner-err.XXXXXX)
python3 scripts/gates/run.py --trigger=pre-tool-use 2>"$RUNNER_ERR"
rc=$?
case "$rc" in
    0)
        rm -f "$RUNNER_ERR"
        exit 0
        ;;
    1)
        # 业务级失败：透传 stderr 后阻断
        cat "$RUNNER_ERR" >&2
        rm -f "$RUNNER_ERR"
        exit 2
        ;;
    *)
        # runner 自身异常：fail-open + WARNING
        echo "WARNING pre-tool-use runner 自身故障 (rc=$rc)，fail-open 放行避免锁死工具链；详见 stderr：" >&2
        cat "$RUNNER_ERR" >&2
        rm -f "$RUNNER_ERR"
        exit 0
        ;;
esac
