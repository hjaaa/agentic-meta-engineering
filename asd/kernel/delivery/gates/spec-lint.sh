#!/usr/bin/env bash
# 闸门 spec-lint:spec 格式校验
# 规则:必备章节齐全;AC 以表格定义行(| AC-NN |)声明且不重复;正文不得引用未定义的 AC
# 用法: spec-lint.sh <spec.md>    (manifest 可用 ASD_MANIFEST 环境变量覆盖)
set -uo pipefail
source "$(cd "$(dirname "$0")/.." && pwd)/lib.sh"

spec=${1:?用法: spec-lint.sh <spec.md>}
fail=0
err() { echo "  ✗ $*"; fail=1; }

[ -f "$spec" ] || { echo "✗ [spec-lint] spec 不存在: $spec"; exit 1; }

# 1) 必备章节
IFS=',' read -ra secs <<<"$(mget spec_required_sections '目标,验收标准')"
for s in "${secs[@]}"; do
  grep -qE "^#{1,4} .*${s}" "$spec" || err "缺少必备章节: ${s}"
done

# 2) AC 定义行:验收标准表格中以 | AC-NN | 开头的行
defs=$(grep -E '^\|[[:space:]]*AC-[0-9]{2}[[:space:]]*\|' "$spec" | grep -oE 'AC-[0-9]{2}')
if [ -z "$defs" ]; then
  err "未找到 AC 定义行(验收标准表格需含 | AC-NN | ... | 行)"
else
  dups=$(echo "$defs" | sort | uniq -d)
  [ -n "$dups" ] && err "AC 编号重复定义: $(echo "$dups" | tr '\n' ' ')"
fi

# 3) 编号断链:正文引用了没有定义行的 AC
refs=$(grep -oE 'AC-[0-9]{2}' "$spec" | sort -u)
for r in $refs; do
  echo "$defs" | grep -q "^${r}$" || err "引用了未定义的 AC: $r"
done

if [ "$fail" -eq 0 ]; then echo "✓ [spec-lint] $spec"; else echo "✗ [spec-lint] $spec"; fi
exit "$fail"
