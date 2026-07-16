#!/usr/bin/env bash
# ASD 交付管道:从 manifest 读步骤按序执行,任一步失败即停
# 用法: pipeline.sh [spec.md]    缺省取 asd/specs/ 下最新一份
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
source "$here/lib.sh"
GATES="$here/gates"

spec=${1:-$(ls -t "$ASD_ROOT"/asd/specs/*.md 2>/dev/null | head -1)}
[ -n "$spec" ] || { echo "✗ [pipeline] 未指定 spec 且 asd/specs/ 为空"; exit 1; }

echo "── ASD pipeline ── spec: $spec"
IFS=',' read -ra steps <<<"$(mget pipeline_steps 'spec-lint,test,ac-coverage')"
for step in "${steps[@]}"; do
  echo "▶ $step"
  case $step in
    spec-lint)   bash "$GATES/spec-lint.sh" "$spec" ;;
    ac-coverage) bash "$GATES/ac-coverage.sh" "$spec" ;;
    build|lint|test)
      cmd=$(mget "${step}_command")
      if [ -z "$cmd" ]; then echo "  - 跳过(manifest 未配置 ${step}_command)"; continue; fi
      (cd "$ASD_ROOT" && eval "$cmd") ;;
    *) echo "  ✗ 未知步骤: $step"; exit 1 ;;
  esac || { echo "✗ [pipeline] 在步骤 ${step} 失败,停止"; exit 1; }
done
echo "✓ [pipeline] 全部通过"
