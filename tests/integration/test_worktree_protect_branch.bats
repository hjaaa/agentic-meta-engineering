#!/usr/bin/env bats
# F-002 集成测试：protect-branch hook 在 worktree feat 分支内不误触发
#
# 来源：requirements/REQ-2026-014/artifacts/detailed-design.md:537-548
# 风险落点：tech-feasibility.md R8（worktree 内 hook 行为）
#
# 验证目标：
#   - 在临时 git repo 内挂一个 worktree（分支 feat/req-test）
#   - 模拟 Claude Code Edit 工具的 PreToolUse JSON stdin
#   - 调 .claude/hooks/pre-tool-use-guard.sh
#   - 期望 rc=0 且 stderr 空（worktree 内 feat 分支不触发 protect-branch BLOCKED）
#
# 运行入口：仓内 bats 已装（/opt/homebrew/bin/bats）；CI 路径需在 F-006 Makefile 收敛后接入。
# 临时本地跑：bats tests/integration/test_worktree_protect_branch.bats

setup() {
  # 测试隔离用临时目录
  TMP_BASE="$(mktemp -d)"
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  HOOK="$REPO_ROOT/.claude/hooks/pre-tool-use-guard.sh"
  MAIN_REPO="$TMP_BASE/main-repo"
  WORKTREE_PATH="$MAIN_REPO/.worktrees/feat-req-test"

  # 建主 repo + 首 commit
  mkdir -p "$MAIN_REPO"
  cd "$MAIN_REPO"
  git init --initial-branch=main -q
  git config user.email "test@example.com"
  git config user.name "Test User"
  echo "seed" > README.md
  git add README.md
  git commit -q -m "seed"

  # 挂 worktree：feat/req-test 分支
  git worktree add "$WORKTREE_PATH" -b feat/req-test -q

  # Edit 工具 PreToolUse 模拟载荷
  EDIT_PAYLOAD=$(cat <<'JSON'
{
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "scripts/lib/foo.py",
    "old_string": "a",
    "new_string": "b"
  }
}
JSON
)
}

teardown() {
  # 清理临时 worktree 与目录
  if [ -d "$MAIN_REPO/.git" ]; then
    (cd "$MAIN_REPO" && git worktree remove --force "$WORKTREE_PATH" 2>/dev/null || true)
  fi
  rm -rf "$TMP_BASE"
}

@test "protect_branch hook does not block Edit on feat branch inside worktree" {
  cd "$WORKTREE_PATH"
  # 当前分支应是 feat/req-test
  current_branch="$(git rev-parse --abbrev-ref HEAD)"
  [ "$current_branch" = "feat/req-test" ]

  # 调 hook，喂 stdin
  run bash -c "echo '$EDIT_PAYLOAD' | '$HOOK'"

  # 期望放行：rc=0
  [ "$status" -eq 0 ]
  # protect-branch 命中时会 exit 2 + 写 fd 3；这里期望 rc=0 即未触发
}

@test "protect_branch hook blocks Edit on main branch (control)" {
  cd "$MAIN_REPO"
  # 当前分支应是 main
  current_branch="$(git rev-parse --abbrev-ref HEAD)"
  [ "$current_branch" = "main" ]

  # 调 hook
  run bash -c "echo '$EDIT_PAYLOAD' | '$HOOK'"

  # 期望拦截：rc=2（pre-tool-use-guard.sh 内 exit 2 表示 BLOCKED）
  [ "$status" -eq 2 ]
}
