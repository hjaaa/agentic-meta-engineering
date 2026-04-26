#!/usr/bin/env bash
# .claude/hooks/extract-experience-worker.sh
# 后台 worker：截断 transcript + claude -p + 写 notes.md
# 整体最多运行 30 秒，超时被 watchdog 杀掉

set -u

CWD="$1"
TRANSCRIPT_PATH="$2"
NOTES_FILE="$3"

# 修 R-9：worker 是 nohup fork 出来的，cwd 已经漂移，必须 cd 回会话目录
# 否则 git 等命令、相对路径全部错乱
cd "$CWD" || exit 0

# === 1. watchdog：30 秒后强杀整个 worker ===
# 先启动 watchdog，再注册 trap——确保 trap 能拿到 WATCHDOG_PID
SELF_PID=$$
(sleep 30 && kill -9 "$SELF_PID" 2>/dev/null) &
WATCHDOG_PID=$!

# 临时文件路径：用 $$ 避免多 worker 并发冲突
TMP_FILE="/tmp/req-experience-$$-transcript.jsonl"
RESULT_FILE="/tmp/req-experience-$$-result.txt"
LOCK_DIR="${NOTES_FILE}.lock"

# cleanup 覆盖正常退出 + 超时被杀（trap EXIT 在 kill -9 时不会跑，但正常路径会）
cleanup() {
  rm -f "$TMP_FILE" "$RESULT_FILE" 2>/dev/null
  rmdir "$LOCK_DIR" 2>/dev/null
  # 清理 watchdog，避免 worker 已正常完成后 watchdog 还在等待
  kill -9 "$WATCHDOG_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

# ---------- helper functions ----------
# 放在 main 流程之前，确保调用时已定义（bash 函数在调用点解析，定义须在调用前）

# acquire_lock: mkdir 原子锁，最多 5 次重试
# 成功返回 0，全部失败返回 1
acquire_lock() {
  local i
  for i in 1 2 3 4 5; do
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

# write_section: 追加"## 会话经验"成功小节到 notes.md
# 调用前必须已持有锁（acquire_lock 成功）
write_section() {
  local content="$1"
  local stamp
  stamp="$(TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M")"
  {
    printf '\n\n## 会话经验（%s）\n\n%s\n' "$stamp" "$content"
  } >> "$NOTES_FILE"
}

# append_skip_marker: 追加"[hook-skipped]"标记到 notes.md
# $1 = reason（错误码），$2 = "skip-write"（可选，notes-busy 时不写避免死循环）
# 其它 reason 默认走 acquire_lock + 写，lock 争抢失败则静默放弃
append_skip_marker() {
  local reason="$1"
  local skip_write="${2:-}"
  # notes-busy 场景：已经锁失败，再尝试写会死循环，直接 return
  [[ "$skip_write" == "skip-write" ]] && return 0
  acquire_lock || return 0
  local stamp
  stamp="$(TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M")"
  {
    printf '\n\n## 会话经验（%s）\n\n_[hook-skipped: %s]_\n' "$stamp" "$reason"
  } >> "$NOTES_FILE"
}

# ---------- main flow ----------

# === 2. 截断 transcript（最近 60 行 ≈ 30 轮）===
# 60 行依据：requirements/REQ-2026-001/artifacts/tech-feasibility.md:74
tail -n 60 "$TRANSCRIPT_PATH" > "$TMP_FILE" 2>/dev/null || {
  append_skip_marker "transcript-truncate-failed"
  exit 0
}

# === 3. 读取并渲染 prompt 模板 ===
PROMPT_FILE="$CWD/.claude/hooks/extract-experience.prompt.md"
[[ -f "$PROMPT_FILE" ]] || {
  append_skip_marker "prompt-template-missing"
  exit 0
}

PROMPT="$(cat "$PROMPT_FILE")"
# 将模板占位符替换为实际截断后的 transcript 路径
PROMPT="${PROMPT//\{\{TRANSCRIPT_PATH\}\}/$TMP_FILE}"

# === 4. 调用 claude -p ===
# 关键：
#   </dev/null — 关闭 stdin，绕过 claude #7263（大 stdin 导致空输出 bug）
#   SKIP_EXPERIENCE_HOOK=1 — 短路递归（防 R-5：claude -p 内部又触发 SessionEnd hook）
#   EXPERIENCE_HOOK_CLAUDE_BIN — 允许测试注入 mock 脚本，不硬依赖真实 claude
SKIP_EXPERIENCE_HOOK=1 "${EXPERIENCE_HOOK_CLAUDE_BIN:-claude}" -p "$PROMPT" \
  --add-dir "$(dirname "$TMP_FILE")" \
  --output-format text \
  </dev/null \
  > "$RESULT_FILE" 2>&1
CLAUDE_EXIT=$?

# === 5. 判定结果 ===
if [[ "$CLAUDE_EXIT" -ne 0 ]]; then
  append_skip_marker "claude-exit-${CLAUDE_EXIT}"
  exit 0
fi

# -s 检查文件非空（绕 #7263 验证：即使 exit 0 也可能输出为空）
if [[ ! -s "$RESULT_FILE" ]]; then
  append_skip_marker "empty-output-bug-7263"
  exit 0
fi

# === 6. mkdir 原子锁 + 追加 notes.md ===
acquire_lock || {
  # notes-busy：5 次 mkdir 全部失败，说明有并发 worker 占锁
  # 传 "skip-write" 避免 append_skip_marker 再次尝试 acquire_lock → 无限递归
  append_skip_marker "notes-busy" "skip-write"
  exit 0
}

write_section "$(cat "$RESULT_FILE")"
exit 0
