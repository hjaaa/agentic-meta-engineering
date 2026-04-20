#!/usr/bin/env bash
set -euo pipefail
SCRIPT=".claude/statusline.sh"
SCRIPT_ABS="${OLDPWD:-$(pwd)}/$SCRIPT"
PASS=0; FAIL=0
assert() { if eval "$1"; then echo "✓ $2"; PASS=$((PASS+1)); else echo "✗ $2"; FAIL=$((FAIL+1)); fi; }

TMPDIR=$(mktemp -d); REPO=$TMPDIR/repo
mkdir -p "$REPO/requirements/REQ-001"
cat > "$REPO/requirements/REQ-001/meta.yaml" <<EOF
id: REQ-001
phase: detail-design
branch: feat/req-001
EOF

cd "$REPO"; git init -q -b feat/req-001; touch a && git add . && git commit -q -m init

# Test 1: 匹配到需求时应输出 REQ-001 和中文阶段名
out=$(bash "$SCRIPT_ABS" 2>/dev/null || echo "")
assert '[[ "$out" == *"REQ-001"* ]]' "应显示需求 ID"
assert '[[ "$out" == *"详细设计"* ]]' "应显示中文阶段名"
assert '[[ "$out" == *"5/8"* ]]' "应显示阶段进度 5/8"

# Test 2: 切换到无匹配的分支
git checkout -q -b feat/other
out=$(bash "$SCRIPT_ABS" 2>/dev/null || echo "")
assert '[[ "$out" == *"no-requirement"* ]]' "无需求时应显示 no-requirement"

echo ""; echo "Passed: $PASS / Failed: $FAIL"
[ $FAIL -eq 0 ] || exit 1
