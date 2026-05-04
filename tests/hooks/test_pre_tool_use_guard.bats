#!/usr/bin/env bats
# --separate-stderr 旗标要求 bats >= 1.5.0
bats_require_minimum_version 1.5.0

# 跑测试时由 test fixture 替代真实 git 行为；通过 GIT_DIR 重定向到临时仓库。
setup() {
  TMP="$(mktemp -d)"
  cd "$TMP"
  git init -q
  # 初始 commit 使 HEAD 可解析，否则 git rev-parse --abbrev-ref HEAD 报错
  git commit --allow-empty -m "init" -q
  git checkout -qb feature/test
  GUARD="${BATS_TEST_DIRNAME}/../../.claude/hooks/pre-tool-use-guard.sh"
}

teardown() {
  rm -rf "$TMP"
  unset CLAUDE_GATES_GLOBAL_BYPASS
}

# ===== V-01 第 1 类：分支保护命中（develop / main / master） =====

@test "blocks Edit on develop branch" {
  git checkout -qb develop
  run --separate-stderr bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 2 ]
  [[ "$stderr" =~ "BLOCKED" ]]
}

@test "blocks Write on main branch" {
  # main 分支在 setup 中已由 git init 初始创建，用 checkout 而非 checkout -b
  git checkout -q main
  run bash -c "echo '{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "blocks MultiEdit on master branch" {
  git checkout -qb master
  run bash -c "echo '{\"tool_name\":\"MultiEdit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

# ===== V-01 第 2 类：分支保护未命中（feature / fix / setup / release） =====

@test "allows Edit on feature branch" {
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 0 ]
}

# ===== V-01 第 3 类：reviews 路径写保护（Edit/Write/MultiEdit） =====

@test "blocks Edit to requirements/REQ-x/reviews/y.json" {
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"requirements/REQ-2026-006/reviews/x.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

# ===== V-01 第 4 类：Bash 写 reviews 路径（12 种 pattern） =====

@test "pattern 1: > redirect" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x > requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 2: >> append" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x >> requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 3: tee" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x | tee requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 4: tee -a" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x | tee -a requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 5: mv" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"mv tmp requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 6: cp" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"cp tmp requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 7: python3 -c open(.., 'w')" {
  # 用 jq 构建 JSON，避免双引号嵌套破坏 JSON 结构
  CMD="python3 -c \"open('requirements/REQ-x/reviews/y.json','w').write('x')\""
  run bash -c "jq -n --arg cmd \"$CMD\" '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\$cmd}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 8: heredoc redirect" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"cat <<EOF > requirements/REQ-x/reviews/y.json\\nfoo\\nEOF\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 9: printf >" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"printf %s data > requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 10: dd of=" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"dd if=/dev/null of=requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 11: sponge" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo x | sponge requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 12: rsync" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"rsync src requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 13: install" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"install -m 644 src requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 2 ]
}

@test "pattern 14: pathlib write_text" {
  # 用 jq 构建 JSON，避免双引号嵌套破坏 JSON 结构
  CMD="python3 -c \"from pathlib import Path; Path('requirements/REQ-x/reviews/y.json').write_text('x')\""
  run bash -c "jq -n --arg cmd \"$CMD\" '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\$cmd}}' | $GUARD"
  [ "$status" -eq 2 ]
}

# ===== V-01 第 5 类：BYPASS 跳过 =====

@test "CLAUDE_GATES_GLOBAL_BYPASS skips block" {
  git checkout -qb develop
  run bash -c "CLAUDE_GATES_GLOBAL_BYPASS=fix-test echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | env CLAUDE_GATES_GLOBAL_BYPASS=fix-test $GUARD"
  [ "$status" -eq 0 ]
}

# ===== V-01 第 6 类：fail-open（stdin 非 JSON / git 不在 PATH / tool_name 缺失） =====

@test "fail-open: stdin not JSON" {
  run bash -c "echo 'not-a-json' | $GUARD"
  [ "$status" -eq 0 ]
}

@test "fail-open: tool_name missing" {
  run bash -c "echo '{}' | $GUARD"
  [ "$status" -eq 0 ]
}

@test "fail-open: not in git repo" {
  cd /tmp  # 真实非 git 目录
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | $GUARD"
  [ "$status" -eq 0 ]
}

@test "fail-open: git not in PATH" {
  # PATH=/usr/bin:/bin 保留 bash(/bin) 和 jq(/usr/bin)，但 git 通常在 /usr/local/bin 或 /opt/homebrew/bin
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | PATH='/usr/bin:/bin' $GUARD"
  [ "$status" -eq 0 ]
}

# ===== V-01 第 7 类：反例（不应阻断） =====

@test "negative: cat reviews file should not block" {
  run bash -c "echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"cat requirements/REQ-x/reviews/y.json\"}}' | $GUARD"
  [ "$status" -eq 0 ]
}

@test "negative: read tool other path should not block" {
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"src/foo.py\"}}' | $GUARD"
  [ "$status" -eq 0 ]
}
