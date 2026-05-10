#!/usr/bin/env bash
# 门禁热路径——每次 Edit/Write/Bash/MultiEdit 调用入口。
# 设计来源：context/team/engineering-spec/design-guidance/gate-system-architecture.md §4.1
# 行为契约：exit 0 = 放行；exit 2 = 阻断；任何意外 → trap → exit 0（fail-open）。
set -u
trap 'exit 0' ERR
exec 3>&2                        # 保存原始 stderr（用于 BLOCKED 消息回传给 Claude Code Agent）
exec 2>>/tmp/guard-error.log     # 自身错误隔离，避免污染 hook 协议 stderr

# 入口名常量（用于 audit 行 entry 字段；与 audit_async.sh 中 ENTRY_* 约定一致）
readonly ENTRY="pre-tool-use-guard"

# 12 类写入正则（F-002 之前抄自已删除的 scripts/gates/plugins/bash_write_protect.py:58 _ALTS；
# 现在 guard.sh 是 live 路径单点防御）
# ⚠️ 已知绕过通道（carryover-A 决策接受）：变量间接引用形式无法被这 12 类正则命中，例如
#     P=requirements/.../reviews/x.json; echo > "$P"
#   防御层次：BYPASS reason 长度 >= 8 + audit reason 全文 + PR review 人工（REQ-2026-006 F-002）
readonly REVIEW_PATH='requirements/[^/]+/reviews/[^/]+\.json'
# 单一长正则；以 ALT 形式连接 12 条 pattern；与 bash_write_protect.py 在 PR-1/PR-2 过渡期内为双轨
# D-006 approval / reject 是人类专属（来源：requirements/REQ-2026-009/plan.md:101）
# 命中即拒绝——hook 只对 AI Bash 触发，tty 用户不走此路径
readonly APPROVAL_SLASH_PATTERN='(/workflow:(approve|reject))(\b|[[:space:]])'
readonly APPROVAL_PYTHON_PATTERN='python3?[[:space:]]+([^[:space:]]+/)?(scripts/lib/)?workflow_(approve|reject)\.py(\b|[[:space:]])'

readonly WRITE_OPS_PATTERN="(\
>>?[[:space:]]*['\"]?[^|;&]*?${REVIEW_PATH}|\
tee[[:space:]]+(-a[[:space:]]+)?['\"]?[^|;&]*?${REVIEW_PATH}|\
mv[[:space:]]+[^[:space:]]+[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
cp[[:space:]]+[^[:space:]]+[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
python3?[[:space:]]+-c[[:space:]]+['\"].*open\\(.*?${REVIEW_PATH}.*?['\"](w|a|wb|ab)['\"]|\
cat[[:space:]]+<<-?[[:space:]]*['\"]?[a-zA-Z_]+['\"]?[[:space:]]+>>?[[:space:]]*['\"]?[^|;&]*?${REVIEW_PATH}|\
printf[[:space:]]+.*?>[[:space:]]*['\"]?[^|;&]*?${REVIEW_PATH}|\
dd[[:space:]]+.*?of=['\"]?[^|;&]*?${REVIEW_PATH}|\
sponge[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
rsync[[:space:]]+(-[^[:space:]]+[[:space:]]+)*[^[:space:]]+[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
install[[:space:]]+(-[^[:space:]]+[[:space:]]+)*[^[:space:]]+[[:space:]]+['\"]?[^|;&]*?${REVIEW_PATH}|\
python3?[[:space:]]+-c[[:space:]]+['\"].*${REVIEW_PATH}.*?\\.write_(text|bytes)\\(\
)"

# audit root：env 优先，回退到脚本所在仓库根（Codex P1：必须与 audit_flush.py
# 的 _REPO_ROOT 一致，否则 hook 在 cwd≠repo 时记录被丢）。
_audit_root() {
  if [[ -n "${CLAUDE_GATES_AUDIT_ROOT:-}" ]]; then
    printf '%s' "${CLAUDE_GATES_AUDIT_ROOT}"
    return
  fi
  local _src_dir
  _src_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
  # .claude/hooks/pre-tool-use-guard.sh → repo root = ../../
  printf '%s' "$( cd "$_src_dir/../.." && pwd )"
}

# audit 行格式：<ts> <cwd> BYPASS|<event> <details> @ entry=<name>
audit_log() {
  local line root
  line="$(date -Iseconds 2>/dev/null) $(pwd) $1 @ entry=${ENTRY}"
  root="$(_audit_root)"
  mkdir -p "${root}/audit/.queue" 2>/dev/null || return 0
  echo "$line" >>"${root}/audit/.queue/$(date +%Y-%m-%d).log" 2>/dev/null || true
}

main() {
  # 0. 全局逃生（A1）——要求 reason 长度 >= 8（防止 BYPASS=1 类无意义值）
  # F-005 carryover-1：三入口 reason 长度判定一致性——与 run.py / submit.py /
  # audit.py 三处 Python 实现对齐，统一为「\n/\r → ' '」+ strip 后长度 >= 8。
  # 旧版 guard 用 raw 长度，导致「8 个空格」等无意义 reason 通过校验。
  local _bypass="${CLAUDE_GATES_GLOBAL_BYPASS:-}"
  if [[ -n "$_bypass" ]]; then
    # 先把换行/回车替换成空格，与 Python 侧一致（防 audit 行被注入换行）
    local _cleaned="${_bypass//$'\n'/ }"
    _cleaned="${_cleaned//$'\r'/ }"
    # bash 纯字符串 strip：剥前后空白
    local _stripped="${_cleaned#"${_cleaned%%[![:space:]]*}"}"
    _stripped="${_stripped%"${_stripped##*[![:space:]]}"}"
    if (( ${#_stripped} < 8 )); then
      cat >&3 <<EOF
BLOCKED: CLAUDE_GATES_GLOBAL_BYPASS reason 太短（strip 后 ${#_stripped} 字符，要求 >= 8）。
请提供有意义的原因，例如：CLAUDE_GATES_GLOBAL_BYPASS="emergency-fix-pr-123"。
EOF
      exit 2
    fi
    audit_log "BYPASS used: ${_cleaned}"
    exit 0
  fi

  # 1. 解析 stdin（jq 失败 → 赋值非零 → ERR trap → exit 0）
  local input tool_name file_path command
  input=$(cat)
  tool_name=$(echo "$input" | jq -r '.tool_name // empty')
  file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
  command=$(echo "$input" | jq -r '.tool_input.command // empty')

  case "$tool_name" in
    Agent)
      # PreToolUse Task 派发：matcher="Task" 命中 tool_name="Agent"（D-007 实采样）
      # 透传退出码——dispatch_precheck.py 自负 fail-open（解析失败 / 锁 timeout 一律 exit 0）
      # 用 exec 替换当前 shell 进程：dispatch_precheck.py 的 exit code 透传给 Claude Code Agent
      # heredoc 二次喂 stdin：guard.sh main 已 input=$(cat) 消费过原 stdin，需重新喂给 Python hook
      exec python3 "$( dirname "${BASH_SOURCE[0]}" )/dispatch_precheck.py" <<<"$input"
      ;;
    Edit|Write|MultiEdit)
      check_branch_protect
      check_review_path "$file_path"
      python3 "$( dirname "${BASH_SOURCE[0]}" )/touches_guard.py" <<<"$input" || true
      ;;
    Bash)
      check_workflow_approval_human_only "$command"
      check_bash_writes_review "$command"
      ;;
  esac

  exit 0
}

check_branch_protect() {
  local b
  b=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || return 0
  case "$b" in
    main|master|develop)
      cat >&3 <<EOF
BLOCKED: 当前在 '$b' 分支，禁止直接 Edit/Write/MultiEdit。
规避方式：
  1) 切到 feature 分支（推荐）：git checkout -b feat/req-xxx
  2) 紧急绕过：CLAUDE_GATES_GLOBAL_BYPASS="<原因>" <重新执行操作>
EOF
      exit 2
      ;;
  esac
}

check_review_path() {
  local p="$1"
  [[ -z "$p" ]] && return 0
  if [[ "$p" =~ ^.*requirements/[^/]+/reviews/.+\.json$ ]]; then
    cat >&3 <<EOF
BLOCKED: $p
reviews/*.json 不能直写。必须走 scripts/save-review.sh（reviewer Agent）
或 scripts/lib/code_review_signoff.py（人类 sign-off，需 tty）。
紧急绕过：CLAUDE_GATES_GLOBAL_BYPASS="<原因>" <重新执行>
EOF
    exit 2
  fi
}

check_bash_writes_review() {
  local cmd="$1"
  [[ -z "$cmd" ]] && return 0
  if echo "$cmd" | grep -qE "$WRITE_OPS_PATTERN"; then
    cat >&3 <<EOF
BLOCKED: Bash 写入 requirements/*/reviews/*.json 被禁。
规避方式：scripts/save-review.sh（reviewer Agent）；
     人类 sign-off 走 scripts/lib/code_review_signoff.py（必须 tty）。
紧急绕过：CLAUDE_GATES_GLOBAL_BYPASS="<原因>" <重新执行>
EOF
    exit 2
  fi
}

check_workflow_approval_human_only() {
  local cmd="$1"
  [[ -z "$cmd" ]] && return 0
  if echo "$cmd" | grep -qE "$APPROVAL_SLASH_PATTERN" \
     || echo "$cmd" | grep -qE "$APPROVAL_PYTHON_PATTERN"; then
    cat >&3 <<EOF
BLOCKED: /workflow:approve / /workflow:reject 是人类专属动作（D-006）。
AI 在主对话或 subagent 中不能调用以下入口：
  - /workflow:approve / /workflow:reject（slash command）
  - python3 scripts/lib/workflow_approve.py / workflow_reject.py（CLI 直入）
请由人类在 tty 终端运行；详见 context/team/ai-collaboration.md 规则三。
紧急绕过：CLAUDE_GATES_GLOBAL_BYPASS="<原因>" <重新执行>
EOF
    exit 2
  fi
}

main "$@"
