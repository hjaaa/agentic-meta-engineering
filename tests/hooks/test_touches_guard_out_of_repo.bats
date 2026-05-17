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

# F-002 out-of-repo: 字面量 ~/ 路径被 _is_out_of_repo 正确判定（codex round-1 C2 反面案例）
# 历史 Path.resolve() 不展开 ~，~/.tmp.json 解析为 <cwd>/~/...，若 cwd 在 toplevel 子树内
# 则 relative_to 成功 → 错误判 in-repo → out-of-repo 短路失效。
# 修复后 Path(file_path).expanduser().resolve() 先展开 ~。
# 直接调 _is_out_of_repo 断言返回 True——绕过 dispatch lock 依赖，精准覆盖 expanduser 修复点。
@test "F-002 out-of-repo: literal ~/ path resolves as out-of-repo" {
  run python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from touches_guard import _is_out_of_repo, _get_worktree_toplevel
toplevel = _get_worktree_toplevel()
assert toplevel is not None, 'toplevel must resolve in test cwd'
assert _is_out_of_repo('~/.test-claude-tilde.json', toplevel) is True, \
    f'expanduser missing: ~/.test-claude-tilde.json must be out-of-repo'
print('OK')
"
  [ "$status" -eq 0 ]
  [[ "$output" == *OK* ]]
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

# F-002 NFR: hook latency p99 absolute budget（D-014 校准自 detailed-design §4.2 "+1ms 增量"）
@test "F-002 NFR: hook p99 latency under absolute budget" {
  payload='{"tool_name":"Write","tool_input":{"file_path":"/tmp/perf-test.json"}}'
  # 100 次实测 p99；2026-05-17 macOS / Python 3.14 实测 ~162ms（含 python 启动 + git subprocess
  # 固有成本）。预算 < 300ms 提供 ~85% 余量护栏，抓数量级回归 + 抗 CI 慢机器 flake。
  # ADR：plan.md D-014（校准自 detailed-design §4.2 字面 "+1ms 增量" 相对预算）。
  p99_ns=$(
    for i in $(seq 1 100); do
      python3 -c "
import time, subprocess, sys
t0 = time.perf_counter_ns()
subprocess.run(['python3', '.claude/hooks/touches_guard.py'],
               input='$payload', text=True, capture_output=True, check=False)
print(time.perf_counter_ns() - t0)
"
    done | sort -n | awk 'BEGIN{c=0} {a[c++]=$1} END{print a[int(c*0.99)]}'
  )
  p99_ms=$(( p99_ns / 1000000 ))
  echo "F-002 hook p99 = ${p99_ms}ms (budget < 300ms; D-014 校准自 +1ms 增量)"
  [ "$p99_ms" -lt 300 ]
}
