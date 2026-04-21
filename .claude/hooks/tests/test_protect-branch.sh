#!/usr/bin/env bash
set -euo pipefail

HOOK=".claude/hooks/protect-branch.sh"
PASS=0
FAIL=0

assert_exit() {
    local expected=$1
    local actual=$2
    local name=$3
    if [ "$expected" = "$actual" ]; then
        echo "✓ $name"
        PASS=$((PASS+1))
    else
        echo "✗ $name (expected exit=$expected, got $actual)"
        FAIL=$((FAIL+1))
    fi
}

# 准备：建临时仓库并切到 main
TMPDIR=$(mktemp -d)
cd "$TMPDIR"
git init -q -b main
echo "a" > a.txt && git add a.txt && git commit -q -m init

# Test 1: main 分支 + Edit 工具 → exit 2
export CLAUDE_HOOK_TOOL_NAME="Edit"
set +e
bash -c "cd $TMPDIR && bash $OLDPWD/$HOOK"
actual=$?
set -e
assert_exit 2 $actual "main + Edit 应被阻止"

# Test 2: feature 分支 + Edit → exit 0
git checkout -q -b feat/test
set +e
bash -c "cd $TMPDIR && bash $OLDPWD/$HOOK"
actual=$?
set -e
assert_exit 0 $actual "feature 分支 + Edit 应放行"

# Test 3: main + Read 类工具 → exit 0（非写操作）
git checkout -q main
export CLAUDE_HOOK_TOOL_NAME="Read"
set +e
bash -c "cd $TMPDIR && bash $OLDPWD/$HOOK"
actual=$?
set -e
assert_exit 0 $actual "main + Read 应放行"

# Test 4: develop 分支 + Edit → exit 2（新增：git-flow 集成分支也受保护）
git checkout -q -b develop
export CLAUDE_HOOK_TOOL_NAME="Edit"
set +e
bash -c "cd $TMPDIR && bash $OLDPWD/$HOOK"
actual=$?
set -e
assert_exit 2 $actual "develop + Edit 应被阻止"

# Test 5: develop + Read → exit 0（非写操作仍放行）
export CLAUDE_HOOK_TOOL_NAME="Read"
set +e
bash -c "cd $TMPDIR && bash $OLDPWD/$HOOK"
actual=$?
set -e
assert_exit 0 $actual "develop + Read 应放行"

echo ""
echo "Passed: $PASS / Failed: $FAIL"
[ "$FAIL" = "0" ] || exit 1
