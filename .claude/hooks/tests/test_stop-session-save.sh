#!/usr/bin/env bash
set -euo pipefail
HOOK=".claude/hooks/stop-session-save.sh"
HOOK_ABS="${OLDPWD:-$(pwd)}/$HOOK"
PASS=0; FAIL=0
assert() { if eval "$1"; then echo "✓ $2"; PASS=$((PASS+1)); else echo "✗ $2"; FAIL=$((FAIL+1)); fi; }

TMPDIR=$(mktemp -d); REPO=$TMPDIR/repo
mkdir -p "$REPO/requirements/REQ-001"
cat > "$REPO/requirements/REQ-001/meta.yaml" <<EOF
id: REQ-001
phase: testing
branch: feat/req-001
EOF
touch "$REPO/requirements/REQ-001/process.txt"

cd "$REPO"; git init -q -b feat/req-001; git add . && git commit -q -m init

bash "$HOOK_ABS" > /dev/null 2>&1 || true

assert 'grep -q "SESSION_END" requirements/REQ-001/process.txt' "应写入 SESSION_END 标记"

echo ""; echo "Passed: $PASS / Failed: $FAIL"
[ $FAIL -eq 0 ] || exit 1
