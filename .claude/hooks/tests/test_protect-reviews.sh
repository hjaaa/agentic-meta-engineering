#!/usr/bin/env bash
# 测试 protect-branch.sh 对 requirements/*/reviews/*.json 路径的拦截
# 这是 PR3 D7-1 落地的"reviews/*.json 直接编辑禁令"
set -euo pipefail

HOOK_REL=".claude/hooks/protect-branch.sh"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HOOK="$REPO_ROOT/$HOOK_REL"

PASS=0
FAIL=0

run_case() {
    local name="$1" expected="$2"
    shift 2
    set +e
    "$@" >/dev/null 2>&1
    local actual=$?
    set -e
    if [ "$actual" = "$expected" ]; then
        echo "✓ $name"
        PASS=$((PASS+1))
    else
        echo "✗ $name (expected exit=$expected, got $actual)"
        FAIL=$((FAIL+1))
    fi
}

# 准备：临时仓库切到 feature 分支（避免命中受保护分支拦截）
TMPDIR=$(mktemp -d)
cd "$TMPDIR"
git init -q -b main
echo "a" > a.txt && git add a.txt && git commit -q -m init
git checkout -q -b feat/test-reviews-protect

# 1) Edit reviews/*.json 在 feature 分支应被拦（exit 2）
run_case "Edit reviews/*.json 在 feature 分支应被拦" 2 \
    env CLAUDE_HOOK_TOOL_NAME=Edit \
        CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/reviews/definition-001.json \
        bash "$HOOK"

# 2) Write reviews/*.json 应被拦（绝对路径形式也命中）
run_case "Write reviews/*.json（绝对路径）应被拦" 2 \
    env CLAUDE_HOOK_TOOL_NAME=Write \
        CLAUDE_HOOK_FILE_PATH=/abs/path/requirements/REQ-2026-007/reviews/code-F-001-001.json \
        bash "$HOOK"

# 3) MultiEdit reviews/*.json 应被拦
run_case "MultiEdit reviews/*.json 应被拦" 2 \
    env CLAUDE_HOOK_TOOL_NAME=MultiEdit \
        CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/reviews/outline-design-001.json \
        bash "$HOOK"

# 4) Bash 操作 reviews/*.json 不拦（save-review.sh 走 Bash 是合法）
run_case "Bash 操作 reviews/*.json 不拦" 0 \
    env CLAUDE_HOOK_TOOL_NAME=Bash \
        CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/reviews/definition-001.json \
        bash "$HOOK"

# 5) Edit artifacts/requirement.md 不拦（路径不命中 reviews/*.json）
run_case "Edit artifacts/requirement.md 不拦" 0 \
    env CLAUDE_HOOK_TOOL_NAME=Edit \
        CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/artifacts/requirement.md \
        bash "$HOOK"

# 6) Read reviews/*.json 不拦（非写工具）
run_case "Read reviews/*.json 不拦" 0 \
    env CLAUDE_HOOK_TOOL_NAME=Read \
        CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/reviews/definition-001.json \
        bash "$HOOK"

# 7) Edit reviews/<file>.md（非 .json）不拦——只针对 *.json
run_case "Edit reviews/*.md 不拦（仅 .json 受限）" 0 \
    env CLAUDE_HOOK_TOOL_NAME=Edit \
        CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/reviews/sketch.md \
        bash "$HOOK"

echo ""
echo "Passed: $PASS / Failed: $FAIL"
[ "$FAIL" = "0" ] || exit 1
