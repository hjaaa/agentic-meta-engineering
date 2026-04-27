#!/usr/bin/env bash
# review save/check 端到端集成测试
#
# 用法：
#   bash tests/fixtures/reviews/run-integration.sh
#
# 退出码：
#   0 — 全部通过
#   1 — 任一断言失败
#
# 副作用：
#   - 临时建 requirements/REQ-2099-INT/，结尾自动删
#   - 不修改任何 git 跟踪文件

set -e
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"
cd "$REPO_ROOT"

REQ=REQ-2099-998
REQ_DIR="requirements/$REQ"

cleanup() {
  if [ -d "$REQ_DIR" ]; then
    find "$REQ_DIR" -type f -delete
    find "$REQ_DIR" -type d -empty -delete
  fi
}
trap cleanup EXIT

echo "== Setup 临时需求 =="
mkdir -p "$REQ_DIR"/{artifacts,reviews}
cat > "$REQ_DIR/artifacts/requirement.md" <<'EOF'
# 集成测试需求
EOF
cat > "$REQ_DIR/meta.yaml" <<EOF
# === 集成测试 meta.yaml，验证注释保留 ===
id: $REQ
title: 集成测试占位
phase: definition
created_at: "2026-04-27 11:00:00"
branch: feat/reviewer-verdict-pr1-infra
base_branch: develop
project: agentic-meta-engineering
services: []
feature_area: hooks
change_type: feature
affected_modules: []
EOF

HEAD=$(git rev-parse --short=7 HEAD)
FIXTURE="$SCRIPT_DIR/valid-definition-001.json"

assert_exit() {
  local expected=$1
  local actual=$2
  local msg=$3
  if [ "$expected" != "$actual" ]; then
    echo "FAIL: $msg (expected exit=$expected, got $actual)"
    exit 1
  fi
  echo "OK: $msg"
}

echo
echo "== T1: R001 应当 fail（无 review） =="
set +e
bash scripts/check-reviews.sh --req "$REQ" --target-phase tech-research > /dev/null 2>&1
assert_exit 1 $? "R001 fires when no review"
set -e

echo
echo "== T2: save-review 写入合法 review =="
python3 -c "
import json, sys
v = json.load(open('$FIXTURE'))
v['reviewed_commit'] = '$HEAD'
v['review_id'] = 'REV-$REQ-definition-001'
v['requirement_id'] = '$REQ'
json.dump(v, sys.stdout)
" | bash scripts/save-review.sh --req "$REQ" --phase definition --reviewer requirement-quality-reviewer > /dev/null

echo
echo "== T3: meta.yaml 注释保留 =="
first_line=$(head -1 "$REQ_DIR/meta.yaml")
if [[ "$first_line" != "# === 集成测试 meta.yaml，验证注释保留 ===" ]]; then
  echo "FAIL: 首行注释丢失（实际：$first_line）"
  exit 1
fi
echo "OK: meta.yaml 首行注释保留"

echo
echo "== T4: check-reviews happy path =="
set +e
bash scripts/check-reviews.sh --req "$REQ" --target-phase tech-research > /dev/null 2>&1
assert_exit 0 $? "check-reviews passes after valid review"
set -e

echo
echo "== T5: R005 hash drift 触发 =="
echo "drift" >> "$REQ_DIR/artifacts/requirement.md"
set +e
bash scripts/check-reviews.sh --req "$REQ" --target-phase tech-research > /dev/null 2>&1
assert_exit 1 $? "R005 fires when artifact changed"
set -e
stale=$(python3 -c "import yaml; print(yaml.safe_load(open('$REQ_DIR/meta.yaml')).get('reviews', {}).get('definition', {}).get('stale'))")
if [[ "$stale" != "True" ]]; then
  echo "FAIL: stale 未写回 meta.yaml（实际：$stale）"
  exit 1
fi
echo "OK: stale=true 已写回 meta.yaml"

echo
echo "== T6: CR-1 fixture 写入应被拒 =="
set +e
HEAD=$(git rev-parse --short=7 HEAD)
python3 -c "
import json, sys
v = json.load(open('$SCRIPT_DIR/invalid-cr1-approved-with-fixes.json'))
v['reviewed_commit'] = '$HEAD'
v['review_id'] = 'REV-$REQ-definition-002'
v['requirement_id'] = '$REQ'
json.dump(v, sys.stdout)
" | bash scripts/save-review.sh --req "$REQ" --phase definition --reviewer requirement-quality-reviewer > /dev/null 2>&1
assert_exit 1 $? "save-review rejects CR-1 violation"
set -e

echo
echo "== 全部通过 =="
