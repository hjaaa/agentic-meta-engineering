#!/usr/bin/env bats
# touches_guard.py 集成测试（F-005 / detail-design §5.4 TC-F5-1）。
#
# 覆盖：
#   TC-F5-1 case1: file_path 命中 touches → 不写 violation（正常场景）
#   TC-F5-1 case2: file_path 越界 → touches_violations[] 追加一条记录
#   TC-F5-1 case3: receipt.json 不存在 → 建空骨架（3 字段）并追加 violation
#
# 隔离策略：
#   - CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE 重定向 locate_req_dir 到 sandbox
#   - sandbox 中注入 dispatch_state.json（含 current_feature）
#   - 用临时 audit 目录避免污染真 repo
bats_require_minimum_version 1.5.0

setup() {
  HOOK="${BATS_TEST_DIRNAME}/../../.claude/hooks/touches_guard.py"
  REPO_ROOT="$( cd "${BATS_TEST_DIRNAME}/../.." && pwd )"
  TMP_AUDIT="$(mktemp -d -t touches_guard_audit.XXXXXX)"
  export CLAUDE_GATES_AUDIT_ROOT="$TMP_AUDIT"
}

teardown() {
  rm -rf "${TMP_AUDIT:-}"
  if [[ -n "${SANDBOX_DIR:-}" && -d "${SANDBOX_DIR:-}" ]]; then
    rm -rf "$SANDBOX_DIR"
  fi
  unset CLAUDE_GATES_AUDIT_ROOT
  unset CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE
  unset SANDBOX_DIR
  unset SANDBOX_REQ
}

# ---------- sandbox 辅助 ----------

# 建 sandbox：创建 req_dir 结构、dispatch_state.json、task md（含 touches）
# 用法：_make_sandbox <feature_id> <touches_yaml_list>
# 例：_make_sandbox "F-005" '["scripts/gates/plugins/touches_violation.py"]'
_make_sandbox() {
  local fid="$1"
  local touches_yaml="$2"

  SANDBOX_DIR="$(mktemp -d -t touches_guard_sandbox.XXXXXX)"
  SANDBOX_REQ="$SANDBOX_DIR/REQ-TEST"
  mkdir -p "$SANDBOX_REQ/artifacts/tasks"

  # .dispatch-state.json（供 dispatch_state.read_state 读取；文件名含前缀点和连字符）
  cat >"$SANDBOX_REQ/.dispatch-state.json" <<EOF
{"current_feature": "$fid", "schema_version": "1.0", "req_id": "REQ-TEST"}
EOF

  # features.json（最小化，仅供上层逻辑；touches_guard 不直接读此文件）
  cat >"$SANDBOX_REQ/artifacts/features.json" <<EOF
{"features": [{"id": "$fid"}]}
EOF

  # task md（含 frontmatter.touches）
  cat >"$SANDBOX_REQ/artifacts/tasks/${fid}.md" <<EOF
---
feature_id: $fid
status: in-progress
touches: $touches_yaml
---

测试 task。
EOF

  export SANDBOX_REQ
  export CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE="$SANDBOX_REQ"
}

# ---------- TC-F5-1 case1: 命中 touches → 不记录 violation ----------

@test "TC-F5-1 case1: file_path matches touches - no violation written" {
  _make_sandbox "F-005" '[".claude/hooks/touches_guard.py"]'

  local payload
  payload='{"tool_name":"Edit","tool_input":{"file_path":".claude/hooks/touches_guard.py"}}'

  run python3 "$HOOK" <<<"$payload"
  [ "$status" -eq 0 ]

  # receipt.json 不应存在（无越界）
  local receipt="$SANDBOX_REQ/artifacts/tasks/F-005.receipt.json"
  [ ! -f "$receipt" ]
}

# ---------- TC-F5-1 case2: 越界 → 追加 violation ----------

@test "TC-F5-1 case2: file_path out-of-touches - violation appended" {
  _make_sandbox "F-005" '[".claude/hooks/touches_guard.py"]'

  local payload
  payload='{"tool_name":"Write","tool_input":{"file_path":"scripts/some_other_file.py"}}'

  run python3 "$HOOK" <<<"$payload"
  [ "$status" -eq 0 ]

  # receipt.json 应存在，violations 非空
  local receipt="$SANDBOX_REQ/artifacts/tasks/F-005.receipt.json"
  [ -f "$receipt" ]

  # 检查 violations 包含越界路径
  run python3 -c "
import json
with open('$receipt') as f:
    data = json.load(f)
violations = data.get('touches_violations', [])
assert len(violations) == 1, f'期望 1 个 violation，实际 {len(violations)}'
assert violations[0]['path'] == 'scripts/some_other_file.py', f\"path 不匹配: {violations[0]['path']}\"
assert violations[0]['tool'] == 'Write', f\"tool 不匹配: {violations[0]['tool']}\"
print('ok')
"
  [ "$status" -eq 0 ]
  [[ "$output" == "ok" ]]
}

# ---------- TC-F5-1 case3: receipt 不存在 → 建空骨架并追加 violation ----------

@test "TC-F5-1 case3: receipt.json absent - create skeleton (3 fields) and append violation" {
  _make_sandbox "F-005" '[".claude/hooks/touches_guard.py"]'

  # 确认 receipt.json 初始不存在
  local receipt="$SANDBOX_REQ/artifacts/tasks/F-005.receipt.json"
  [ ! -f "$receipt" ]

  local payload
  payload='{"tool_name":"Edit","tool_input":{"file_path":"context/some_doc.md"}}'

  run python3 "$HOOK" <<<"$payload"
  [ "$status" -eq 0 ]

  # receipt.json 被建出来
  [ -f "$receipt" ]

  # 验证骨架 3 字段 + violations 一条
  run python3 -c "
import json
with open('$receipt') as f:
    data = json.load(f)

# 必须有骨架 3 字段
assert 'feature_id' in data, 'feature_id 字段缺失'
assert 'schema_version' in data, 'schema_version 字段缺失'
assert 'touches_violations' in data, 'touches_violations 字段缺失'

# feature_id 应正确
assert data['feature_id'] == 'F-005', f\"feature_id 错误: {data['feature_id']}\"

# violations 有一条
assert len(data['touches_violations']) == 1, f\"期望 1 条 violation，实际 {len(data['touches_violations'])}\"
print('ok')
"
  [ "$status" -eq 0 ]
  [[ "$output" == "ok" ]]
}

# ---------- fail-open 场景：stdin 非法 → exit 0 ----------

@test "fail-open: invalid JSON stdin - exit 0" {
  run python3 "$HOOK" <<<"{not valid json"
  [ "$status" -eq 0 ]
}

# ---------- fail-open 场景：tool_name=Bash → exit 0 且不处理 ----------

@test "fail-open: tool_name=Bash - exit 0 no action" {
  _make_sandbox "F-005" '[]'

  run python3 "$HOOK" <<<'{"tool_name":"Bash","tool_input":{"command":"ls"}}'
  [ "$status" -eq 0 ]

  # receipt.json 不应被建
  local receipt="$SANDBOX_REQ/artifacts/tasks/F-005.receipt.json"
  [ ! -f "$receipt" ]
}

# ---------- MultiEdit 越界场景 ----------

@test "MultiEdit: one edit out-of-touches - violation recorded" {
  _make_sandbox "F-005" '[".claude/hooks/touches_guard.py"]'

  local payload
  payload='{"tool_name":"MultiEdit","tool_input":{"edits":[{"file_path":".claude/hooks/touches_guard.py"},{"file_path":"context/unrelated.md"}]}}'

  run python3 "$HOOK" <<<"$payload"
  [ "$status" -eq 0 ]

  local receipt="$SANDBOX_REQ/artifacts/tasks/F-005.receipt.json"
  [ -f "$receipt" ]

  run python3 -c "
import json
with open('$receipt') as f:
    data = json.load(f)
violations = data.get('touches_violations', [])
assert len(violations) == 1, f'期望 1 个 violation（仅越界的那个），实际 {len(violations)}'
assert violations[0]['path'] == 'context/unrelated.md'
print('ok')
"
  [ "$status" -eq 0 ]
  [[ "$output" == "ok" ]]
}
