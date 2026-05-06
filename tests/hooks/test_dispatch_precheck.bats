#!/usr/bin/env bats
# dispatch_precheck.py 集成测试（F-004 / detail-design §2）。
# 覆盖 fail-open 7+ 场景 + B-1 / B-2 / B-3 BLOCKED + tool_name=Edit fail-open。
#
# fixture 策略：用环境变量 CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE 把 hook 的
# locate_req_dir_by_branch 重定向到 sandbox 临时目录，避免污染真 git 分支 / 真 repo。
bats_require_minimum_version 1.5.0

setup() {
  HOOK="${BATS_TEST_DIRNAME}/../../.claude/hooks/dispatch_precheck.py"
  REPO_ROOT="$( cd "${BATS_TEST_DIRNAME}/../.." && pwd )"
  # 用临时 audit 目录避免污染 repo audit/.queue
  TMP_AUDIT="$(mktemp -d -t dispatch_precheck_audit.XXXXXX)"
  export CLAUDE_GATES_AUDIT_ROOT="$TMP_AUDIT"
}

teardown() {
  rm -rf "$TMP_AUDIT"
  if [[ -n "${SANDBOX_DIR:-}" && -d "$SANDBOX_DIR" ]]; then
    rm -rf "$SANDBOX_DIR"
  fi
  unset CLAUDE_GATES_AUDIT_ROOT
  unset CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE
  unset SANDBOX_DIR
}

# ---------- helpers ----------

# 在临时目录建 sandbox req：features.json + tasks/F-001.md + tasks/F-002.md（默认全 pending）
# 用法：_make_sandbox <req_id>；调用后 SANDBOX_DIR / SANDBOX_REQ 可用
_make_sandbox() {
  local req_id="$1"
  SANDBOX_DIR="$(mktemp -d -t dispatch_precheck_sandbox.XXXXXX)"
  SANDBOX_REQ="$SANDBOX_DIR/$req_id"
  mkdir -p "$SANDBOX_REQ/artifacts/tasks"
  cat >"$SANDBOX_REQ/artifacts/features.json" <<EOF
{
  "schema_version": "1.0",
  "requirement_id": "$req_id",
  "features": [
    {"id":"F-001","title":"a","description":"d","modules":[],"depends_on":[],"depends_on_features":[],"complexity":"trivial","touches":[],"acceptance":[]},
    {"id":"F-002","title":"b","description":"d","modules":[],"depends_on":[],"depends_on_features":["F-001"],"complexity":"trivial","touches":[],"acceptance":[]}
  ]
}
EOF
  cat >"$SANDBOX_REQ/artifacts/tasks/F-001.md" <<'EOF'
---
feature_id: F-001
title: a
status: pending
complexity: trivial
depends_on: []
touches: []
created_at: 2026-05-06 10:00:00
updated_at: 2026-05-06 10:00:00
review_report: null
---
EOF
  cat >"$SANDBOX_REQ/artifacts/tasks/F-002.md" <<'EOF'
---
feature_id: F-002
title: b
status: pending
complexity: trivial
depends_on: [F-001]
touches: []
created_at: 2026-05-06 10:00:00
updated_at: 2026-05-06 10:00:00
review_report: null
---
EOF
  export CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE="$SANDBOX_REQ"
}

# ---------- fail-open 7+ 场景 ----------

@test "fail-open scenario 1: tool_name=Edit (not Agent)" {
  run bash -c "echo '{\"tool_name\":\"Edit\"}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 1b: tool_name=Bash (D-007 only Agent fuzzy match)" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"ls\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 2: stdin empty" {
  run bash -c "echo -n '' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 2b: stdin invalid JSON" {
  run bash -c "echo '{not json' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 3: prompt missing (no tool_input)" {
  run bash -c "echo '{\"tool_name\":\"Agent\"}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 3b: prompt empty string" {
  run bash -c "echo '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 3c: prompt is null" {
  run bash -c "echo '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":null}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 4: feature_id regex miss" {
  run bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"hello world\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 4b: feature_id with prefix not allowed (D-007 hard rule)" {
  # `# feature_id: F-001` 不命中——必须独占首行
  run bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"# feature_id: F-001\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 5: req_dir override points to non-existent path" {
  export CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE="/tmp/does-not-exist-$$"
  run bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-001\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 5b: req_dir exists but no features.json" {
  SANDBOX_DIR="$(mktemp -d -t dispatch_precheck_sandbox.XXXXXX)"
  mkdir -p "$SANDBOX_DIR/REQ-2099-101/artifacts"
  export CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE="$SANDBOX_DIR/REQ-2099-101"
  run bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-001\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 6: features.json invalid JSON" {
  _make_sandbox "REQ-2099-106"
  echo "{not json" >"$SANDBOX_REQ/artifacts/features.json"
  run bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-001\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 7: feature_id F-999 not in features.json" {
  _make_sandbox "REQ-2099-107"
  run bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-999\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

@test "fail-open scenario 10: top-level except sanity (BOM in stdin)" {
  # 任何未预期异常都应被顶层 except Exception 接住
  run bash -c "printf '\xef\xbb\xbf{\"tool_name\":\"Agent\"}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}

# ---------- BLOCKED 场景 ----------

@test "BLOCKED B-1: F-001 status=in-progress (not pending)" {
  _make_sandbox "REQ-2099-101"
  # 改 F-001 status=in-progress
  sed -i.bak 's/^status: pending$/status: in-progress/' "$SANDBOX_REQ/artifacts/tasks/F-001.md"
  rm "$SANDBOX_REQ/artifacts/tasks/F-001.md.bak"

  run --separate-stderr bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-001\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 2 ]
  [[ "$stderr" =~ "BLOCKED" ]]
  [[ "$stderr" =~ "F-001" ]]
  [[ "$stderr" =~ "in-progress" ]]
}

@test "BLOCKED B-1b: F-001 status=done (not pending; cannot re-dispatch)" {
  _make_sandbox "REQ-2099-101b"
  sed -i.bak 's/^status: pending$/status: done/' "$SANDBOX_REQ/artifacts/tasks/F-001.md"
  rm "$SANDBOX_REQ/artifacts/tasks/F-001.md.bak"

  run --separate-stderr bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-001\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 2 ]
  [[ "$stderr" =~ "BLOCKED" ]]
  [[ "$stderr" =~ "F-001" ]]
  [[ "$stderr" =~ "done" ]]
}

@test "BLOCKED B-2: F-002 deps F-001 not done (default sandbox: F-001 pending)" {
  _make_sandbox "REQ-2099-102"
  run --separate-stderr bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-002\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 2 ]
  [[ "$stderr" =~ "BLOCKED" ]]
  [[ "$stderr" =~ "F-002" ]]
  [[ "$stderr" =~ "F-001" ]]
}

@test "BLOCKED B-3: state.current_feature=F-001, dispatch F-002 (concurrent block)" {
  _make_sandbox "REQ-2099-103"
  # 让 F-001 已 done 让 B-2 通过；测 B-3
  sed -i.bak 's/^status: pending$/status: done/' "$SANDBOX_REQ/artifacts/tasks/F-001.md"
  rm "$SANDBOX_REQ/artifacts/tasks/F-001.md.bak"
  cat >"$SANDBOX_REQ/.dispatch-state.json" <<'EOF'
{
  "schema_version": "1.0",
  "req_id": "REQ-2099-103",
  "current_feature": "F-001",
  "acquired_at": "2026-05-06T10:00:00+08:00",
  "acquired_by_pid": 99999
}
EOF
  run --separate-stderr bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-002\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 2 ]
  [[ "$stderr" =~ "BLOCKED" ]]
  [[ "$stderr" =~ "F-001 派发中" ]]
}

# ---------- 成功路径 ----------

@test "DISPATCH OK: F-001 pending + idle state → exit 0 + state written" {
  _make_sandbox "REQ-2099-104"
  run bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-001\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
  [[ -f "$SANDBOX_REQ/.dispatch-state.json" ]]
  STATE_CONTENT="$(cat $SANDBOX_REQ/.dispatch-state.json)"
  [[ "$STATE_CONTENT" =~ "F-001" ]]
  [[ "$STATE_CONTENT" =~ "current_feature" ]]
}

@test "DISPATCH same feature retry: state.current_feature=F-001 + dispatch F-001 → exit 0" {
  # B-3 允许 current_feature == 自身（重派同 feature 不阻断）
  _make_sandbox "REQ-2099-105"
  cat >"$SANDBOX_REQ/.dispatch-state.json" <<'EOF'
{
  "schema_version": "1.0",
  "req_id": "REQ-2099-105",
  "current_feature": "F-001",
  "acquired_at": "2026-05-06T10:00:00+08:00",
  "acquired_by_pid": 99999
}
EOF
  run bash -c "printf '%s' '{\"tool_name\":\"Agent\",\"tool_input\":{\"prompt\":\"feature_id: F-001\\nbody\"}}' | python3 $HOOK"
  [ "$status" -eq 0 ]
}
