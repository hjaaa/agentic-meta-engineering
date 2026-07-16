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

# 运行器结局校验(python):静态匹配之外,每条 AC 必须有至少一个测试被
# unittest discover 真实执行且结局为 ok——未收集(顶层/嵌套 def)、被跳过
# (方法级/类级/多行 skip)、失败,都不算覆盖。运行时真相优先于文本分析
collect_on=0
outcomes=""
id_tpl=$(mget ac_id_pattern 'test_ac{nn}_')
if [ "$(mget language)" = "python" ]; then
  collect_on=1
  outcomes=$(cd "$proj" && python3 "$(cd "$(dirname "$0")/.." && pwd)/run-unittest.py" \
    "$(mget test_dir tests)" "$test_glob" 2>/dev/null || true)
fi

# skip_deco <file> <line>:检查 def 行上方紧邻的装饰器里有无 skip 族。
# 跳过空行/注释;用括号深度追踪识别跨多行的装饰器调用(向上扫描时深度>0
# 说明仍处于某个多行调用体内,继续上溯直到找到打头的 @ 行)
skip_deco() {
  awk -v n="$2" 'NR < n { buf[NR] = $0 }
    END {
      depth = 0
      for (i = n - 1; i >= 1; i--) {
        line = buf[i]
        if (line ~ /^[[:space:]]*$/ || line ~ /^[[:space:]]*#/) continue
        op = gsub(/\(/, "(", line); cl = gsub(/\)/, ")", line)
        if (line ~ /^[[:space:]]*@/) {
          if (line ~ /@([A-Za-z_.]*\.)?(skip|skipIf|skipif|skipUnless)[( ]?/) { print "SKIPPED"; exit }
          depth += cl - op
          if (depth < 0) depth = 0
          continue
        }
        depth += cl - op
        if (depth > 0) continue
        break
      }
    }' "$1"
}

for id in $ids; do
  nn=${id#AC-}
  pat=${pattern_tpl/\{nn\}/$nn}
  matches=$(grep -RnF --include="$test_glob" "$pat" "$test_dir" 2>/dev/null || true)
  # 行首锚定(允许缩进):散文/文档字符串中段提及的模式不算测试定义;
  # 锚定后天然排除注释行(注释行去缩进后以注释符开头,不以 pat 开头)
  active=""
  while IFS= read -r m; do
    [ -z "$m" ] && continue
    content=${m#*:}; content=${content#*:}
    trimmed=${content#"${content%%[![:space:]]*}"}
    case $trimmed in "$pat"*) active="${active}${m}"$'\n' ;; esac
  done <<<"$matches"
  active=${active%$'\n'}
  if [ -z "$active" ]; then
    commented=$(echo "$matches" | grep -E "^[^:]+:[0-9]+:[[:space:]]*${comment}" || true)
    if [ -n "$commented" ]; then
      err "$id 的测试存在但被注释掉: $(echo "$commented" | head -1 | cut -d: -f1,2)"
    else
      err "$id 无对应测试(期望测试匹配: ${pat})"
    fi
    continue
  fi
  # 活性还要求未被 skip 装饰器禁用——被 skip 的测试套件照样 exit 0,等于从未执行。
  # 任一匹配活性即算覆盖(允许遗留 skip 测试与替代测试并存),全部被禁才红
  live=""
  while IFS= read -r m; do
    [ -z "$m" ] && continue
    if [ "$(skip_deco "$(echo "$m" | cut -d: -f1)" "$(echo "$m" | cut -d: -f2)")" != "SKIPPED" ]; then
      live=$m
      break
    fi
  done <<<"$active"
  if [ -z "$live" ]; then
    err "$id 的测试全部被 skip 装饰器禁用: $(echo "$active" | head -1 | cut -d: -f1,2)"
    continue
  fi
  if [ "$collect_on" -eq 1 ]; then
    frag=${id_tpl/\{nn\}/$nn}
    rows=$(echo "$outcomes" | grep -F "$frag" || true)
    if ! echo "$rows" | grep -q ' ok$'; then
      if echo "$rows" | grep -q ' skipped$'; then
        err "$id 的测试在运行器下被跳过(方法级/类级 skip): $(echo "$live" | cut -d: -f1,2)"
      elif echo "$rows" | grep -qE ' (failed|error)$'; then
        err "$id 的测试在运行器下未通过: $(echo "$live" | cut -d: -f1,2)"
      else
        err "$id 的测试未被测试运行器收集(unittest 只执行 TestCase 方法): $(echo "$live" | cut -d: -f1,2)"
      fi
    fi
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "✓ [ac-coverage] $(echo "$ids" | tr '\n' ' ')全部有活性测试"
else
  echo "✗ [ac-coverage]"
fi
exit "$fail"
