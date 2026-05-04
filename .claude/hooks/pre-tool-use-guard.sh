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

# audit 行格式：<ts> <cwd> BYPASS|<event> <details> @ entry=<name>
audit_log() {
  local line
  line="$(date -Iseconds 2>/dev/null) $(pwd) $1 @ entry=${ENTRY}"
  mkdir -p audit/.queue 2>/dev/null || return 0
  echo "$line" >>"audit/.queue/$(date +%Y-%m-%d).log" 2>/dev/null || true
}

main() {
  # 0. 全局逃生（A1）——要求 reason 长度 >= 8（防止 BYPASS=1 类无意义值）
  local _bypass="${CLAUDE_GATES_GLOBAL_BYPASS:-}"
  if [[ -n "$_bypass" ]]; then
    if (( ${#_bypass} < 8 )); then
      cat >&3 <<EOF
BLOCKED: CLAUDE_GATES_GLOBAL_BYPASS reason 太短（${#_bypass} 字符，要求 >= 8）。
请提供有意义的原因，例如：CLAUDE_GATES_GLOBAL_BYPASS="emergency-fix-pr-123"。
EOF
      exit 2
    fi
    # audit 写 reason 全文（替换控制字符为可见形式以防 audit 行被换行注入）
    local _safe_reason="${_bypass//$'\n'/\\n}"
    _safe_reason="${_safe_reason//$'\r'/\\r}"
    audit_log "BYPASS used: ${_safe_reason}"
    exit 0
  fi

  # 1. 解析 stdin（jq 失败 → 赋值非零 → ERR trap → exit 0）
  local input tool_name file_path command
  input=$(cat)
  tool_name=$(echo "$input" | jq -r '.tool_name // empty')
  file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
  command=$(echo "$input" | jq -r '.tool_input.command // empty')

  case "$tool_name" in
    Edit|Write|MultiEdit)
      check_branch_protect
      check_review_path "$file_path"
      ;;
    Bash)
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

main "$@"
