#!/usr/bin/env bash
# .claude/hooks/extract-experience.sh
# SessionEnd Hook 主入口：守门 + fork worker
# 任何异常都 exit 0，不影响用户退出

set -u

# === 1. 同步读 stdin（绕开 macOS async 空 stdin bug #38162）===
HOOK_INPUT="$(cat)"

# === 2. opt-out env 短路 ===
if [[ "${SKIP_EXPERIENCE_HOOK:-0}" == "1" ]]; then
  exit 0
fi

# === 3. 解析 JSON 字段（python3 macOS/Linux 自带）===
# 注意：parse_field 返回字段值或空字符串，异常时静默返回空
parse_field() {
  echo "$HOOK_INPUT" | python3 -c "
import json, sys
try:
    print(json.load(sys.stdin).get('${1:-}', ''))
except Exception:
    pass
" 2>/dev/null
}

CWD="$(parse_field cwd)"
TRANSCRIPT="$(parse_field transcript_path)"

# === 4. 守门：cwd 必须可访问 ===
[[ -z "$CWD" || ! -d "$CWD" ]] && exit 0
cd "$CWD" || exit 0

# === 5. 守门：当前分支必须匹配 feat/req-* ===
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
[[ "$BRANCH" =~ ^feat/req- ]] || exit 0

# === 6. 守门：对应 meta.yaml 必须存在 ===
REQ_ID="${BRANCH#feat/req-}"
META_FILE="$CWD/requirements/REQ-${REQ_ID}/meta.yaml"
[[ -f "$META_FILE" ]] || {
  # meta.yaml 不存在，静默跳过
  exit 0
}

# === 7. 守门：phase 不能是 completed ===
PHASE="$(grep -E '^phase:' "$META_FILE" | head -1 | awk '{print $2}')"
[[ "$PHASE" == "completed" ]] && exit 0

# === 8. 校验 transcript_path 存在 ===
[[ -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]] && exit 0

# === 9. fork worker，disown 脱离进程组（绕 #41577）===
NOTES_FILE="$CWD/requirements/REQ-${REQ_ID}/notes.md"
WORKER="$CWD/.claude/hooks/extract-experience-worker.sh"

[[ -x "$WORKER" ]] || exit 0

nohup bash "$WORKER" "$CWD" "$TRANSCRIPT" "$NOTES_FILE" >/dev/null 2>&1 &
disown $!

exit 0
