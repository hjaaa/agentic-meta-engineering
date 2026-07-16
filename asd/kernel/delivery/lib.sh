#!/usr/bin/env bash
# ASD delivery 共享库:manifest 读取
# manifest 是扁平 `key: value`(伪 YAML),不支持嵌套/列表

ASD_ROOT=${ASD_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
ASD_MANIFEST=${ASD_MANIFEST:-$ASD_ROOT/asd/manifest.yaml}

# mget <key> [default]:读 manifest 键值,去首尾空白与成对外层引号
mget() {
  local v
  v=$(grep -E "^$1:" "$ASD_MANIFEST" 2>/dev/null | head -1 \
      | sed -e 's/^[^:]*:[[:space:]]*//' -e 's/[[:space:]]*$//' \
            -e 's/^"\(.*\)"$/\1/')
  echo "${v:-${2:-}}"
}
