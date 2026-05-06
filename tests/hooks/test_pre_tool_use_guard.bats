#!/usr/bin/env bats
# --separate-stderr 旗标要求 bats >= 1.5.0
bats_require_minimum_version 1.5.0

# 跑测试时由 test fixture 替代真实 git 行为；通过 GIT_DIR 重定向到临时仓库。
setup() {
  TMP="$(mktemp -d)"
  cd "$TMP"
  # 显式 init.defaultBranch=main——CI runner 老版 git 默认 master，会让
  # "blocks Write on main branch"（依赖初始为 main）/"blocks MultiEdit on master branch"
  # （依赖 master 不存在）两个用例双双失败。
  git -c init.defaultBranch=main init -q
  # 临时仓库本地配置 user 身份——CI runner 默认不带全局 git config，
  # 否则 git commit 报 fatal: empty ident name
  git config user.email "test@example.com"
  git config user.name "test"
  # 初始 commit 使 HEAD 可解析，否则 git rev-parse --abbrev-ref HEAD 报错
  git commit --allow-empty -m "init" -q
  git checkout -qb feature/test
  GUARD="${BATS_TEST_DIRNAME}/../../.claude/hooks/pre-tool-use-guard.sh"
  # hotfix REQ-2026-008：guard.sh Edit/Write/MultiEdit 路径会调用 touches_guard.py。
  # 该 hook 通过 _REPO_ROOT = parents[2] 指向真 agentic-meta-engineering 仓库，
  # _locate_req_dir() 若没 OVERRIDE 会用真分支匹配真 meta.yaml.branch → 写到真
  # F-007.receipt.json 的 touches_violations[]（污染真需求产物）。
  # 这里强制 OVERRIDE 到一个不存在的目录，让 _locate_req_dir 返回 None → fail-open。
  TOUCHES_GUARD_FAKE_REQ_DIR="$TMP/__nonexistent_req_dir__"
  export CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE="$TOUCHES_GUARD_FAKE_REQ_DIR"
}

teardown() {
  rm -rf "$TMP"
  unset CLAUDE_GATES_GLOBAL_BYPASS
  unset CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE
  unset TOUCHES_GUARD_FAKE_REQ_DIR
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

@test "BYPASS reason too short (1 char) is rejected" {
  git checkout -qb develop
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | env CLAUDE_GATES_GLOBAL_BYPASS=1 $GUARD"
  [ "$status" -eq 2 ]
}

@test "BYPASS reason too short (7 chars) is rejected" {
  git checkout -qb develop
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | env CLAUDE_GATES_GLOBAL_BYPASS=tooShrt $GUARD"
  [ "$status" -eq 2 ]
}

@test "BYPASS reason length 8 is accepted" {
  git checkout -qb develop
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | env CLAUDE_GATES_GLOBAL_BYPASS=fix-test $GUARD"
  [ "$status" -eq 0 ]
}

# F-005 carryover-1：raw 长度 ≥ 8 但 strip 后 < 8 应被拒（与 Python 三入口对齐）
@test "BYPASS reason whitespace-padded short is rejected (strip-then-check)" {
  git checkout -qb develop
  # 8 空格——raw 长度 8，strip 后 0；旧 raw-长度策略会通过，新 strip 策略拒绝
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | env 'CLAUDE_GATES_GLOBAL_BYPASS=        ' $GUARD"
  [ "$status" -eq 2 ]
}

# F-005 carryover-1：strip 后 ≥ 8 应通过（前后空白允许）
@test "BYPASS reason with leading/trailing whitespace stripped to 8 is accepted" {
  git checkout -qb develop
  # raw 长度 12，strip 后 8 → 通过
  run bash -c "echo '{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"a.txt\"}}' | env 'CLAUDE_GATES_GLOBAL_BYPASS=  fix-test  ' $GUARD"
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

# ===== V-06：hyperfine 100 runs 均值 < 5ms =====

@test "V-06 hyperfine 100 runs avg < 5ms" {
  command -v hyperfine >/dev/null || skip "hyperfine not installed"
  # 用 echo '{}' 喂 fail-open 路径（最稳定的最短路径——tool_name 缺失即 fail-open exit 0）
  run hyperfine --warmup 5 --runs 100 --export-json /tmp/v06.json \
    -N "echo '{}' | $GUARD"
  [ "$status" -eq 0 ]
  # 解析 JSON 拿 mean，断言 < 5ms（5e-3 秒）
  local mean
  mean=$(python3 -c "import json,sys; print(json.load(open('/tmp/v06.json'))['results'][0]['mean'])")
  python3 -c "import sys; sys.exit(0 if float('$mean') < 0.005 else 1)"
}
