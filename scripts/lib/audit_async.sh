#!/usr/bin/env bash
# 异步 audit 工具函数库——供 run.py（subprocess 调用）和 trigger 脚本（source）共用。
# 注意：pre-tool-use-guard.sh 自行内联了等价 audit_log()，不 source 此文件
# （最小依赖、最快启动；10 行重复换零依赖，spec §4.2 注明的有意冗余）。

# 入口名常量（呼应 outline-design §3 与 R-2 minor）
readonly ENTRY_GUARD="pre-tool-use-guard"
readonly ENTRY_RUNNER="runner"
readonly ENTRY_TRIGGER_SUBMIT="trigger:submit"
readonly ENTRY_TRIGGER_PHASE="trigger:phase-transition"
readonly ENTRY_TRIGGER_SAVE_REVIEW="trigger:save-review"
readonly ENTRY_TRIGGER_MANUAL="trigger:manual"

# 取 audit root：env 优先，回退到脚本所在仓库根（Codex P1：consumer 在 repo 根，
# producer 不能用 cwd-relative，否则 hook 在 cwd≠repo 时记录被丢）。
_audit_root() {
  if [[ -n "${CLAUDE_GATES_AUDIT_ROOT:-}" ]]; then
    printf '%s' "${CLAUDE_GATES_AUDIT_ROOT}"
    return
  fi
  local _src_dir
  _src_dir="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
  # scripts/lib/audit_async.sh → repo root = ../../
  printf '%s' "$( cd "$_src_dir/../.." && pwd )"
}

# audit_append_async <event-line> [entry-name]
# 行格式：<ISO ts> <cwd> <event-line> @ entry=<name>
# 写入 <audit-root>/audit/.queue/<YYYY-MM-DD>.log；失败完全静默（best-effort）。
audit_append_async() {
  local line="$1"
  local entry="${2:-${ENTRY_RUNNER}}"
  local root
  root="$(_audit_root)"
  local f="${root}/audit/.queue/$(date +%Y-%m-%d).log"
  local ts
  ts="$(date -Iseconds 2>/dev/null)"
  mkdir -p "$(dirname "$f")" 2>/dev/null || return 0
  echo "$ts $(pwd) ${line} @ entry=${entry}" >>"$f" 2>/dev/null || true
}

# audit_flush_queue：把 .queue/*.log 整理成 audit/<YYYY-MM>/<entry>-<YYYY-MM-DD>.json（详见 §4.3）。
# 由 SessionEnd hook（.claude/hooks/audit-flush.sh）调用，失败完全静默。
audit_flush_queue() {
  python3 scripts/lib/audit_flush.py 2>/dev/null || true
}
