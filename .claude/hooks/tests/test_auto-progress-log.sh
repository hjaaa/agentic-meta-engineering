#!/usr/bin/env bash
set -euo pipefail

HOOK=".claude/hooks/auto-progress-log.sh"
# 在任何 cd 之前保存 hook 绝对路径，避免 cd 后 bash 内置 $OLDPWD 被覆盖
HOOK_ABS="${OLDPWD:-$(pwd)}/$HOOK"
PASS=0; FAIL=0

assert() {
    if eval "$1"; then echo "✓ $2"; PASS=$((PASS+1)); else echo "✗ $2"; FAIL=$((FAIL+1)); fi
}

TMPDIR=$(mktemp -d)
REPO=$TMPDIR/repo
mkdir -p "$REPO/requirements/REQ-001"
cat > "$REPO/requirements/REQ-001/meta.yaml" <<EOF
id: REQ-001
phase: definition
branch: feat/req-001
EOF
touch "$REPO/requirements/REQ-001/process.txt"

cd "$REPO"
git init -q -b feat/req-001
git add . && git commit -q -m init

# Test 1: 在对应分支上调用 hook，process.txt 应增加一行
export CLAUDE_HOOK_TOOL_NAME="Edit"
bash "$HOOK_ABS" > /dev/null 2>&1 || true
assert '[ $(wc -l < requirements/REQ-001/process.txt) -ge 1 ]' "process.txt 应被追加"

# Test 2: 分支和 meta.yaml 不匹配 → 不写
git checkout -q -b feat/other
lines_before=$(wc -l < requirements/REQ-001/process.txt)
bash "$HOOK_ABS" > /dev/null 2>&1 || true
lines_after=$(wc -l < requirements/REQ-001/process.txt)
assert "[ $lines_after -eq $lines_before ]" "分支不匹配时不应写 process.txt"

# Test 3: hook 失败不应阻塞（退出码 0）
cd /tmp  # 离开 git 仓库
set +e; bash "$HOOK_ABS"; rc=$?; set -e
assert "[ $rc -eq 0 ]" "非 git 仓库时应优雅退出"

echo ""; echo "Passed: $PASS / Failed: $FAIL"
[ $FAIL -eq 0 ] || exit 1
