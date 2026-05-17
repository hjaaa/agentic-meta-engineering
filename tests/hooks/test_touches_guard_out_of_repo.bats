#!/usr/bin/env bats

setup() {
  cd "$(git rev-parse --show-toplevel)"
}

# F-002 out-of-repo: /tmp 路径不记 violation
@test "F-002 out-of-repo: /tmp path no violation" {
  payload='{"tool_name":"Write","tool_input":{"file_path":"/tmp/test-out-of-repo.json"}}'
  run bash -c "echo '$payload' | python3 .claude/hooks/touches_guard.py"
  [ "$status" -eq 0 ]
  # 不应有新增 violation 记录
  ! grep -q "/tmp/test-out-of-repo.json" requirements/*/artifacts/tasks/*.receipt.json
}

# F-002 out-of-repo: /var 路径不记 violation
@test "F-002 out-of-repo: /var path no violation" {
  payload='{"tool_name":"Edit","tool_input":{"file_path":"/var/log/test.log"}}'
  run bash -c "echo '$payload' | python3 .claude/hooks/touches_guard.py"
  [ "$status" -eq 0 ]
}

# F-002 out-of-repo: ~/ 路径不记 violation
@test "F-002 out-of-repo: HOME path no violation" {
  home_path="$HOME/.test-claude-out.json"
  payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$home_path\"}}"
  run bash -c "echo '$payload' | python3 .claude/hooks/touches_guard.py"
  [ "$status" -eq 0 ]
}

# F-002 worktree edge case: worktree cwd 内文件按 worktree-local 判定
@test "F-002 worktree edge case: file in worktree cwd uses worktree-local check" {
  tmp_wt=$(mktemp -d)
  git worktree add "$tmp_wt" HEAD 2>/dev/null || skip "无法创建 worktree"
  payload="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$tmp_wt/Makefile\"}}"
  hook_path="$tmp_wt/.claude/hooks/touches_guard.py"
  run bash -c "cd '$tmp_wt' && echo '$payload' | python3 '$hook_path'"
  [ "$status" -eq 0 ]
  git worktree remove --force "$tmp_wt"
}

# F-002 NFR: hook 延迟 p99 < 1ms 增量
@test "F-002 NFR: hook latency p99 less than 1ms increment" {
  # baseline 待 testing 阶段固化
  skip "baseline 待 testing 阶段固化"
}
