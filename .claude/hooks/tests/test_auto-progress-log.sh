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

# REQ-001：v2 布局（log_layout=split）→ Hook 应写 process.tool.log
mkdir -p "$REPO/requirements/REQ-001"
cat > "$REPO/requirements/REQ-001/meta.yaml" <<EOF
id: REQ-001
phase: definition
branch: feat/req-001
log_layout: split
EOF
touch "$REPO/requirements/REQ-001/process.txt"

# REQ-002：legacy 布局（缺字段）→ Hook 应写 process.txt（兼容老需求）
mkdir -p "$REPO/requirements/REQ-002"
cat > "$REPO/requirements/REQ-002/meta.yaml" <<EOF
id: REQ-002
phase: definition
branch: feat/req-002
EOF
touch "$REPO/requirements/REQ-002/process.txt"

cd "$REPO"
git init -q -b feat/req-001
git add . && git commit -q -m init

# Test 1: v2 分支 + Edit → process.tool.log 应被追加，process.txt 不动
export CLAUDE_HOOK_TOOL_NAME="Edit"
bash "$HOOK_ABS" > /dev/null 2>&1 || true
assert '[ -f requirements/REQ-001/process.tool.log ] && [ $(wc -l < requirements/REQ-001/process.tool.log) -ge 1 ]' \
       "v2: process.tool.log 应被追加"
assert '[ $(wc -l < requirements/REQ-001/process.txt) -eq 0 ]' \
       "v2: process.txt 不应被 Hook 写入"

# Test 2: 分支和 meta.yaml 不匹配 → 两个文件都不写
git checkout -q -b feat/other
tool_log_before=$(wc -l < requirements/REQ-001/process.tool.log)
bash "$HOOK_ABS" > /dev/null 2>&1 || true
tool_log_after=$(wc -l < requirements/REQ-001/process.tool.log)
assert "[ $tool_log_after -eq $tool_log_before ]" \
       "分支不匹配时不应写 process.tool.log"

# Test 3: legacy 分支（缺 log_layout）→ process.txt 被追加（老行为兼容）
git checkout -q -b feat/req-002
bash "$HOOK_ABS" > /dev/null 2>&1 || true
assert '[ $(wc -l < requirements/REQ-002/process.txt) -ge 1 ]' \
       "legacy: process.txt 应被追加（兼容老需求）"
assert '[ ! -f requirements/REQ-002/process.tool.log ]' \
       "legacy: 不应创建 process.tool.log"

# Test 4: hook 失败不应阻塞（退出码 0）
cd /tmp  # 离开 git 仓库
set +e; bash "$HOOK_ABS"; rc=$?; set -e
assert "[ $rc -eq 0 ]" "非 git 仓库时应优雅退出"

echo ""; echo "Passed: $PASS / Failed: $FAIL"
[ $FAIL -eq 0 ] || exit 1
