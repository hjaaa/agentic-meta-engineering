#!/usr/bin/env bash
# 闸门 ac-coverage:spec 中每条 AC 必须有对应的"活性"测试
# 活性 = 匹配 ac_test_pattern 且所在行未被注释——测试被注释掉视为独立错误(而非"无测试")
# 用法: ac-coverage.sh <spec.md> [project-root]   (默认 project-root = ASD_ROOT)
set -uo pipefail
source "$(cd "$(dirname "$0")/.." && pwd)/lib.sh"

spec=${1:?用法: ac-coverage.sh <spec.md> [project-root]}
proj=${2:-$ASD_ROOT}
fail=0
err() { echo "  ✗ $*"; fail=1; }

test_dir="$proj/$(mget test_dir tests)"
test_glob=$(mget test_glob 'test_*.py')
pattern_tpl=$(mget ac_test_pattern 'def test_ac{nn}_')
comment=$(mget comment_prefix '#')

[ -f "$spec" ] || { echo "✗ [ac-coverage] spec 不存在: $spec"; exit 1; }
[ -d "$test_dir" ] || { echo "✗ [ac-coverage] 测试目录不存在: $test_dir"; exit 1; }

ids=$(grep -E '^\|[[:space:]]*AC-[0-9]{2}[[:space:]]*\|' "$spec" | grep -oE 'AC-[0-9]{2}' | sort -u)
[ -z "$ids" ] && { echo "✗ [ac-coverage] spec 无 AC 定义行,先修复 spec-lint"; exit 1; }

for id in $ids; do
  nn=${id#AC-}
  pat=${pattern_tpl/\{nn\}/$nn}
  matches=$(grep -RnF --include="$test_glob" "$pat" "$test_dir" 2>/dev/null || true)
  active=$(echo "$matches" | grep -vE "^[^:]+:[0-9]+:[[:space:]]*${comment}" || true)
  if [ -z "$active" ]; then
    commented=$(echo "$matches" | grep -E "^[^:]+:[0-9]+:[[:space:]]*${comment}" || true)
    if [ -n "$commented" ]; then
      err "$id 的测试存在但被注释掉: $(echo "$commented" | head -1 | cut -d: -f1,2)"
    else
      err "$id 无对应测试(期望测试匹配: ${pat})"
    fi
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "✓ [ac-coverage] $(echo "$ids" | tr '\n' ' ')全部有活性测试"
else
  echo "✗ [ac-coverage]"
fi
exit "$fail"
