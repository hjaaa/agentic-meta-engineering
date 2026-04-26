#!/usr/bin/env bash
# run-e2e.sh
# REQ-2026-001 集成测试入口，端到端验证 extract-experience Hook 全链路。
# 运行方式：bash requirements/REQ-2026-001/artifacts/tests/run-e2e.sh
# 注意：TC-08 需等待约 35s watchdog 超时，请耐心等待。
#
# 退出码：全 PASS → 0；任一 FAIL → 1（stderr 列出失败 TC）

set -eu

# ============================================================
# 全局路径常量
# ============================================================

# 脚本自身所在目录（tests/）
TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
# 仓库根目录（tests/ 向上 4 级：tests → artifacts → REQ-2026-001 → requirements → <root>）
REPO_ROOT="$(cd "$TESTS_DIR/../../../.." && pwd)"
# 受测 Hook 脚本路径
MAIN_HOOK="$REPO_ROOT/.claude/hooks/extract-experience.sh"
WORKER_HOOK="$REPO_ROOT/.claude/hooks/extract-experience-worker.sh"
# mock-claude.sh 路径
MOCK_CLAUDE="$TESTS_DIR/mock-claude.sh"
# fixture 路径
FIXTURE_NORMAL="$TESTS_DIR/fixtures/transcript-normal.jsonl"
FIXTURE_LARGE="$TESTS_DIR/fixtures/transcript-large.jsonl"

# ============================================================
# 全局状态追踪
# ============================================================
FAIL_COUNT=0
FAIL_LIST=""   # 逗号分隔的失败 TC 列表

# ============================================================
# 基础 helper：构造伪仓库 + 清理
# ============================================================

# setup_fake_repo: 在 /tmp 下建一个伪 feat/req-* 仓库
# 参数: $1 = workdir 路径（调用方负责生成唯一路径）
#       $2 = 分支名（如 feat/req-TEST-001）
#       $3 = req_id（如 TEST-001）
#       $4 = phase（如 development / completed，空则默认 development）
#       $5 = skip_req_dir（"1" 表示不创建 requirements 目录与 meta.yaml，用于 TC-04 场景）
setup_fake_repo() {
  local workdir="$1"
  local branch="$2"
  local req_id="$3"
  local phase="${4:-development}"
  local skip_req_dir="${5:-0}"

  # 初始化 git 仓库（bare 最小配置，只需 HEAD 能读）
  git init -q "$workdir"
  git -C "$workdir" config user.email "test@test.com"
  git -C "$workdir" config user.name "test"
  # 先提交一个空 commit，让 HEAD 可用
  git -C "$workdir" commit -q --allow-empty -m "init"
  # 切到目标分支
  git -C "$workdir" checkout -q -b "$branch"

  # 按需创建 requirements 目录 + meta.yaml + notes.md
  if [ "$skip_req_dir" != "1" ]; then
    local req_dir="$workdir/requirements/REQ-${req_id}"
    mkdir -p "$req_dir"
    cat > "$req_dir/meta.yaml" <<YAML
id: REQ-${req_id}
title: 测试需求
phase: ${phase}
YAML
    # notes.md 初始为空（或含占位符）
    printf '# REQ-%s Notes\n' "$req_id" > "$req_dir/notes.md"
  fi

  # 把 .claude 目录 symlink 或拷贝进来，让受测脚本能被调用
  # 使用 symlink 避免拷贝大文件，也确保修改受测脚本时测试立即感知
  ln -s "$REPO_ROOT/.claude" "$workdir/.claude"
}

# teardown: 清理工作目录
teardown() {
  local workdir="$1"
  rm -rf "$workdir" 2>/dev/null
}

# ============================================================
# 断言 helper
# ============================================================

# assert_contains: 验证文件包含指定字符串
# $1=文件路径 $2=期望字符串 $3=失败说明
assert_contains() {
  local file="$1"
  local pattern="$2"
  local msg="${3:-}"
  if ! grep -qF "$pattern" "$file" 2>/dev/null; then
    echo "[ASSERT FAIL] '$pattern' not found in $file. $msg" >&2
    return 1
  fi
  return 0
}

# assert_not_contains: 验证文件不包含指定字符串
assert_not_contains() {
  local file="$1"
  local pattern="$2"
  local msg="${3:-}"
  if grep -qF "$pattern" "$file" 2>/dev/null; then
    echo "[ASSERT FAIL] '$pattern' unexpectedly found in $file. $msg" >&2
    return 1
  fi
  return 0
}

# assert_count_ge: 验证文件中模式出现次数 >= 期望值
assert_count_ge() {
  local file="$1"
  local pattern="$2"
  local expected="$3"
  local actual
  actual=$(grep -c "$pattern" "$file" 2>/dev/null || echo 0)
  if [ "$actual" -lt "$expected" ]; then
    echo "[ASSERT FAIL] '$pattern' count=$actual < expected=$expected in $file" >&2
    return 1
  fi
  return 0
}

# ============================================================
# 构造 Hook 输入 JSON
# ============================================================

# make_hook_input: 构造 extract-experience.sh 期望的 stdin JSON
# $1=工作目录路径  $2=transcript 文件路径
make_hook_input() {
  local cwd="$1"
  local transcript="$2"
  # 用 python3 生成合法 JSON（避免引号转义问题）
  python3 -c "
import json
print(json.dumps({'cwd': '$cwd', 'transcript_path': '$transcript'}))
"
}

# ============================================================
# 调用主 Hook 的 helper（同步等待 worker 完成）
# ============================================================

# run_hook_and_wait: 调用 extract-experience.sh，然后等待 worker 完成
# worker 是 nohup 后台启动的，需要轮询 notes.md 变化来判断完成
# $1=hook_input_json  $2=notes_file  $3=最大等待秒数（实际秒级，sleep 1 累计）  $4=mock_mode
run_hook_and_wait() {
  local hook_input="$1"
  local notes_file="$2"
  local max_wait="${3:-10}"
  local mock_mode="${4:-success}"
  local initial_size
  initial_size=$(wc -c < "$notes_file" 2>/dev/null || echo 0)

  # 调用主 Hook（同步返回，worker 在后台跑）
  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
  MOCK_CLAUDE_MODE="$mock_mode" \
    bash "$MAIN_HOOK" <<< "$hook_input"

  # 等待 notes.md 发生变化（说明 worker 已完成写入）
  # 每次 sleep 1s，elapsed 以秒为单位累加，名实一致
  local elapsed=0
  while [ "$elapsed" -lt "$max_wait" ]; do
    local current_size
    current_size=$(wc -c < "$notes_file" 2>/dev/null || echo 0)
    if [ "$current_size" -gt "$initial_size" ]; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  # 超时未变化也返回 0（部分 TC 期望 notes.md 不变，这里只是等待，不做断言）
  return 0
}

# ============================================================
# TC 定义
# ============================================================

# TC-01: 正常会话提取
# 期望：notes.md 末尾增 "## 会话经验（YYYY-MM-DD HH:MM）" 小节
tc_01_normal() {
  local workdir="/tmp/req-experience-tc01-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-001" "TEST-001" "development"
  local notes_file="$workdir/requirements/REQ-TEST-001/notes.md"
  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_NORMAL")"

  run_hook_and_wait "$hook_input" "$notes_file" 15 "success"

  # 断言：notes.md 含 "## 会话经验"
  local result=0
  assert_contains "$notes_file" "## 会话经验" "TC-01 应写入会话经验小节" || result=1
  # 断言：含 mock-claude 输出的特征内容
  assert_contains "$notes_file" "mkdir 原子锁" "TC-01 应含 mock-claude 输出" || result=1

  teardown "$workdir"
  return $result
}

# TC-02: env opt-out
# 期望：设置 SKIP_EXPERIENCE_HOOK=1 时 notes.md 不变
tc_02_opt_out() {
  local workdir="/tmp/req-experience-tc02-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-002" "TEST-002" "development"
  local notes_file="$workdir/requirements/REQ-TEST-002/notes.md"
  local initial_content
  initial_content="$(cat "$notes_file")"
  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_NORMAL")"

  # SKIP_EXPERIENCE_HOOK=1 时 hook 应直接 exit 0，不启动 worker
  SKIP_EXPERIENCE_HOOK=1 \
  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
    bash "$MAIN_HOOK" <<< "$hook_input"

  # 等待一小段，确保即使有后台进程也有时间完成（此处期望什么都没发生）
  sleep 0.5

  local result=0
  local final_content
  final_content="$(cat "$notes_file")"
  if [ "$initial_content" != "$final_content" ]; then
    echo "[ASSERT FAIL] TC-02: notes.md should not change when SKIP_EXPERIENCE_HOOK=1" >&2
    result=1
  fi

  teardown "$workdir"
  return $result
}

# TC-03: 非需求分支
# 期望：分支为 develop 或 hotfix/xxx 时，notes.md 不变
tc_03_non_req_branch() {
  local workdir="/tmp/req-experience-tc03-$$"
  # 使用 develop 分支（不匹配 feat/req-* 模式）
  setup_fake_repo "$workdir" "develop" "TEST-003" "development"
  local notes_file="$workdir/requirements/REQ-TEST-003/notes.md"
  local initial_content
  initial_content="$(cat "$notes_file")"
  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_NORMAL")"

  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
    bash "$MAIN_HOOK" <<< "$hook_input"
  sleep 0.5

  local result=0
  assert_not_contains "$notes_file" "## 会话经验" "TC-03 非需求分支不应写入会话经验" || result=1

  teardown "$workdir"
  return $result
}

# TC-04: meta.yaml 缺失
# 期望：分支匹配 feat/req-* 但 meta.yaml 不存在时，notes.md 不变（且不新建）
tc_04_no_meta() {
  local workdir="/tmp/req-experience-tc04-$$"
  # skip_req_dir=1：不创建 requirements 目录与 meta.yaml
  setup_fake_repo "$workdir" "feat/req-TEST-004" "TEST-004" "" "1"

  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_NORMAL")"
  local notes_file="$workdir/requirements/REQ-TEST-004/notes.md"

  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
    bash "$MAIN_HOOK" <<< "$hook_input"
  sleep 0.5

  local result=0
  # notes.md 不应被新建
  if [ -f "$notes_file" ]; then
    echo "[ASSERT FAIL] TC-04: notes.md should not be created when meta.yaml missing" >&2
    result=1
  fi

  teardown "$workdir"
  return $result
}

# TC-05: phase=completed
# 期望：meta.yaml 设置 phase: completed 时，notes.md 不变
tc_05_phase_completed() {
  local workdir="/tmp/req-experience-tc05-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-005" "TEST-005" "completed"
  local notes_file="$workdir/requirements/REQ-TEST-005/notes.md"
  local initial_content
  initial_content="$(cat "$notes_file")"
  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_NORMAL")"

  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
    bash "$MAIN_HOOK" <<< "$hook_input"
  sleep 0.5

  local result=0
  assert_not_contains "$notes_file" "## 会话经验" "TC-05 phase=completed 不应写入会话经验" || result=1

  teardown "$workdir"
  return $result
}

# TC-06: claude -p 失败（mock exit 1）
# 期望：notes.md 末尾写入 "[hook-skipped: claude-exit-1]"
tc_06_claude_fail() {
  local workdir="/tmp/req-experience-tc06-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-006" "TEST-006" "development"
  local notes_file="$workdir/requirements/REQ-TEST-006/notes.md"
  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_NORMAL")"

  run_hook_and_wait "$hook_input" "$notes_file" 10 "fail"

  local result=0
  assert_contains "$notes_file" "hook-skipped: claude-exit-1" "TC-06 应写入 claude-exit-1 标记" || result=1

  teardown "$workdir"
  return $result
}

# TC-07: claude -p 输出为空（mock empty）
# 期望：notes.md 末尾写入 "[hook-skipped: empty-output-bug-7263]"
tc_07_claude_empty() {
  local workdir="/tmp/req-experience-tc07-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-007" "TEST-007" "development"
  local notes_file="$workdir/requirements/REQ-TEST-007/notes.md"
  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_NORMAL")"

  run_hook_and_wait "$hook_input" "$notes_file" 10 "empty"

  local result=0
  assert_contains "$notes_file" "hook-skipped: empty-output-bug-7263" "TC-07 应写入 empty-output-bug-7263 标记" || result=1

  teardown "$workdir"
  return $result
}

# TC-08: 超时（mock slow，sleep 60）
# 期望：worker 30s 后被 watchdog kill，notes.md 不变（trap 不跑，无 skipped 标记）
# 注意：此用例等待约 35s（watchdog 30s kill + 5s 缓冲），属正常现象
tc_08_timeout() {
  echo "[TC-08] 正在等待 watchdog 约 35s 超时，请耐心等待..." >&2

  local workdir="/tmp/req-experience-tc08-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-008" "TEST-008" "development"
  local notes_file="$workdir/requirements/REQ-TEST-008/notes.md"
  local initial_content
  initial_content="$(cat "$notes_file")"
  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_NORMAL")"

  # 调用主 Hook（worker 启动后立即返回）
  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
  MOCK_CLAUDE_MODE="slow" \
    bash "$MAIN_HOOK" <<< "$hook_input"

  # 等待 35s，确保 watchdog（30s）已经 kill worker
  sleep 35

  local result=0
  local final_content
  final_content="$(cat "$notes_file")"
  # watchdog kill -9 时 trap EXIT 不会跑，所以 notes.md 应与初始相同
  if [ "$initial_content" != "$final_content" ]; then
    echo "[ASSERT FAIL] TC-08: notes.md should not change after watchdog kill" >&2
    result=1
  fi

  teardown "$workdir"
  return $result
}

# TC-09: 大 transcript（100 行）
# 期望：tail 60 行后正常工作，notes.md 写入会话经验小节
tc_09_large_transcript() {
  local workdir="/tmp/req-experience-tc09-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-009" "TEST-009" "development"
  local notes_file="$workdir/requirements/REQ-TEST-009/notes.md"
  local hook_input
  hook_input="$(make_hook_input "$workdir" "$FIXTURE_LARGE")"

  run_hook_and_wait "$hook_input" "$notes_file" 15 "success"

  local result=0
  assert_contains "$notes_file" "## 会话经验" "TC-09 大 transcript 应正常写入" || result=1

  teardown "$workdir"
  return $result
}

# TC-11: transcript 截断失败（worker tail -n 60 失败路径）
# 期望：notes.md 末尾写入 "[hook-skipped: transcript-truncate-failed]"
# 触发方式：直接调用 worker，传不存在的 transcript 路径（绕过主 Hook 的 -f 守门）
# 边界含义：主 Hook 校验 transcript 后到 worker 启动间，文件被删除/不可读的极端时序
tc_11_transcript_truncate_failed() {
  local workdir="/tmp/req-experience-tc11-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-011" "TEST-011" "development"
  local notes_file="$workdir/requirements/REQ-TEST-011/notes.md"
  # 故意传一个不存在的 transcript 路径，让 worker tail 失败
  local missing_transcript="/tmp/req-experience-tc11-$$-nonexistent.jsonl"

  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
    bash "$WORKER_HOOK" "$workdir" "$missing_transcript" "$notes_file"

  local result=0
  assert_contains "$notes_file" "hook-skipped: transcript-truncate-failed" "TC-11 应写入 transcript-truncate-failed 标记" || result=1

  teardown "$workdir"
  return $result
}

# TC-12: prompt 模板缺失（worker §4.2 步骤 3 失败路径）
# 期望：notes.md 末尾写入 "[hook-skipped: prompt-template-missing]"
# 触发方式：手工搭一个最小 workdir，故意不创建 .claude/hooks/extract-experience.prompt.md
# 不能复用 setup_fake_repo（它把整个 .claude symlink 进 workdir，含 prompt 模板）
tc_12_prompt_missing() {
  local workdir="/tmp/req-experience-tc12-$$"
  mkdir -p "$workdir/requirements/REQ-TEST-012"
  printf '# REQ-TEST-012 Notes\n' > "$workdir/requirements/REQ-TEST-012/notes.md"
  local notes_file="$workdir/requirements/REQ-TEST-012/notes.md"
  # 注意：不创建 $workdir/.claude 目录，prompt 文件不存在

  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
    bash "$WORKER_HOOK" "$workdir" "$FIXTURE_NORMAL" "$notes_file"

  local result=0
  assert_contains "$notes_file" "hook-skipped: prompt-template-missing" "TC-12 应写入 prompt-template-missing 标记" || result=1

  rm -rf "$workdir" 2>/dev/null
  return $result
}

# TC-10: 并发写（两个 worker 同时运行）
# 期望：两条"## 会话经验"都写入，无内容撕裂
# 注意：stale-lock 探测机制下，并发时一方可能写 notes-busy；
#       因此期望 grep "## 会话经验" 出现 >= 1 次（非 0 即合格）
#       实际行为视锁竞争结果而定：两方都成功 = 2 条；一方 notes-busy = 1 条
tc_10_concurrent_write() {
  local workdir="/tmp/req-experience-tc10-$$"
  setup_fake_repo "$workdir" "feat/req-TEST-010" "TEST-010" "development"
  local notes_file="$workdir/requirements/REQ-TEST-010/notes.md"

  # 直接调用两个 worker 实例（并发），共享同一 notes.md
  # 使用真实 worker 脚本，注入 EXPERIENCE_HOOK_CLAUDE_BIN
  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
  MOCK_CLAUDE_MODE="success" \
    bash "$WORKER_HOOK" "$workdir" "$FIXTURE_NORMAL" "$notes_file" &
  local pid1=$!

  EXPERIENCE_HOOK_CLAUDE_BIN="$MOCK_CLAUDE" \
  MOCK_CLAUDE_MODE="success" \
    bash "$WORKER_HOOK" "$workdir" "$FIXTURE_NORMAL" "$notes_file" &
  local pid2=$!

  # 等待两个 worker 都完成
  wait $pid1
  wait $pid2

  local result=0
  # 期望至少 1 条"## 会话经验"（并发锁竞争时至少一方成功）
  assert_count_ge "$notes_file" "## 会话经验" 1 "TC-10 并发写应至少产生 1 条经验记录" || result=1

  # 验证内容完整性：文件末尾不应有截断迹象（简单判断：文件可被 wc 统计）
  local line_count
  line_count=$(wc -l < "$notes_file" 2>/dev/null || echo -1)
  if [ "$line_count" -lt 1 ]; then
    echo "[ASSERT FAIL] TC-10: notes.md appears corrupted (line_count=$line_count)" >&2
    result=1
  fi

  teardown "$workdir"
  return $result
}

# ============================================================
# 主流程：依次运行所有 TC，收集结果
# ============================================================

run_tc() {
  local tc_num="$1"
  local tc_func="$2"
  local tc_desc="$3"

  printf '[%s] %s ... ' "$tc_num" "$tc_desc"
  if "$tc_func"; then
    echo "PASS"
  else
    echo "FAIL"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    if [ -z "$FAIL_LIST" ]; then
      FAIL_LIST="$tc_num"
    else
      FAIL_LIST="$FAIL_LIST, $tc_num"
    fi
  fi
}

main() {
  # 全局兜底清理：无论正常退出还是被中断，都清除 TC workdir 临时目录
  trap 'rm -rf /tmp/req-experience-tc*-$$ 2>/dev/null' EXIT INT TERM

  echo "=========================================="
  echo " REQ-2026-001 端到端集成测试"
  echo " 受测 Hook: $MAIN_HOOK"
  echo " 受测 Worker: $WORKER_HOOK"
  echo "=========================================="
  echo ""

  # 前置检查：受测脚本必须存在且可执行
  local preflight_ok=1
  for f in "$MAIN_HOOK" "$WORKER_HOOK" "$MOCK_CLAUDE" "$FIXTURE_NORMAL" "$FIXTURE_LARGE"; do
    if [ ! -f "$f" ]; then
      echo "[PREFLIGHT FAIL] 文件不存在: $f" >&2
      preflight_ok=0
    fi
  done
  if [ "$preflight_ok" -eq 0 ]; then
    echo "前置检查失败，终止测试。" >&2
    exit 1
  fi

  run_tc "TC-01" tc_01_normal          "正常会话提取"
  run_tc "TC-02" tc_02_opt_out         "env opt-out (SKIP_EXPERIENCE_HOOK=1)"
  run_tc "TC-03" tc_03_non_req_branch  "非需求分支 (develop)"
  run_tc "TC-04" tc_04_no_meta         "meta.yaml 缺失"
  run_tc "TC-05" tc_05_phase_completed "phase=completed"
  run_tc "TC-06" tc_06_claude_fail     "claude -p 失败 (exit 1)"
  run_tc "TC-07" tc_07_claude_empty    "claude -p 输出为空 (bug-7263)"
  run_tc "TC-08" tc_08_timeout         "超时 watchdog (约 35s，请等待)"
  run_tc "TC-09" tc_09_large_transcript "大 transcript (100 行)"
  run_tc "TC-10" tc_10_concurrent_write "并发写 notes.md"
  run_tc "TC-11" tc_11_transcript_truncate_failed "transcript 截断失败 (tail -n 60 失败路径)"
  run_tc "TC-12" tc_12_prompt_missing "prompt 模板缺失"

  echo ""
  echo "=========================================="

  # 清理 /tmp 残留文件（TC-08 slow worker 被 watchdog kill -9，trap 不运行，
  # 所以 /tmp/req-experience-*-*.{jsonl,txt,err} 可能残留，属预期行为，由此处统一清理）
  rm -f /tmp/req-experience-*-transcript.jsonl \
        /tmp/req-experience-*-result.txt \
        /tmp/req-experience-*-claude.err 2>/dev/null
  local residual
  residual=$(ls /tmp/req-experience-* 2>/dev/null | wc -l | tr -d ' ')
  if [ "$residual" -gt 0 ]; then
    echo "[警告] 清理后仍有 /tmp/req-experience-* 残留文件 ($residual 个)：" >&2
    ls /tmp/req-experience-* 2>/dev/null >&2
  else
    echo "临时文件清理验证: OK（/tmp/req-experience-* 为空）"
  fi

  if [ "$FAIL_COUNT" -eq 0 ]; then
    echo "结果: 全部 PASS (12/12)"
    echo "=========================================="
    exit 0
  else
    echo "结果: ${FAIL_COUNT} 个 FAIL" >&2
    echo "失败 TC: $FAIL_LIST" >&2
    echo "==========================================" >&2
    exit 1
  fi
}

main "$@"
