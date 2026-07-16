#!/usr/bin/env bash
# ASD 知识检索:按关键词命中 asd/knowledge/ 下的条目并输出全文
# 用法: loader.sh "<关键词 空格分隔>"    命中为空输出提示,退出码恒为 0(检索不拦流程)
set -uo pipefail
ASD_ROOT=${ASD_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
KB=${ASD_KB:-$ASD_ROOT/asd/knowledge}

kws=${1:?用法: loader.sh "<关键词 空格分隔>"}
[ -d "$KB" ] || { echo "(知识库不存在: $KB)"; exit 0; }

hit=0
for f in "$KB"/*.md; do
  [ -e "$f" ] || break
  [ "$(basename "$f")" = "index.md" ] && continue
  for kw in $kws; do
    if grep -qi -- "$kw" "$f"; then
      echo "── 命中: $f"
      cat "$f"
      echo
      hit=1
      break
    fi
  done
done
[ "$hit" -eq 0 ] && echo "(无命中条目,关键词: $kws)"
exit 0
