#!/usr/bin/env bash
# 迁移工具：抓旧入口基线（exit code + 归一化关键前缀行）
#
# 用途：在把旧 .sh 改写为薄壳 exec runner 之前，先用本脚本抓基线，
#       之后跑新入口，用 normalize-stderr.sh 归一化后与基线 diff 验证行为等价。
#
# 用法：
#   bash scripts/gates/migration/capture-baseline.sh <old-entry> [input-args...] > baseline.txt
#
#   示例（meta-schema）：
#     bash scripts/gates/migration/capture-baseline.sh \
#       scripts/check-meta.sh --all 2>&1 > baselines/check-meta.txt
#
#   示例（adapter 模式对比）：
#     # 1. 抓旧入口基线
#     bash scripts/gates/migration/capture-baseline.sh \
#       scripts/check-meta.sh requirements/REQ-2026-001/meta.yaml > baselines/check-meta-REQ-001.txt
#
#     # 2. 跑新入口并归一化对比
#     NEW_OUT=$(python3 scripts/gates/run.py \
#       --trigger=adapter --legacy=check-meta \
#       requirements/REQ-2026-001/meta.yaml 2>&1)
#     echo "exit=$?"
#     echo "$NEW_OUT" | bash scripts/gates/migration/normalize-stderr.sh
#
#     # 3. diff
#     diff baselines/check-meta-REQ-001.txt <(上述新入口输出)
#
# 输出格式：
#   exit=<rc>
#   <归一化后的关键前缀行...>
#
# 注意：
#   - 必须在 git 仓库根目录运行（或设置 REPO_ROOT 环境变量）
#   - normalize-stderr.sh 需要在 PATH 可到或本脚本同目录

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NORMALIZE="${SCRIPT_DIR}/normalize-stderr.sh"

if [[ $# -lt 1 ]]; then
  echo "用法: $0 <old-entry> [input-args...]" >&2
  exit 2
fi

OLD_ENTRY="$1"
shift

if [[ ! -f "$OLD_ENTRY" ]]; then
  echo "ERROR: 旧入口文件不存在: $OLD_ENTRY" >&2
  exit 2
fi

if [[ ! -f "$NORMALIZE" ]]; then
  echo "ERROR: normalize-stderr.sh 不存在: $NORMALIZE" >&2
  exit 2
fi

# 运行旧入口，合并 stdout+stderr，捕获 exit code
COMBINED_OUT=$(bash "$OLD_ENTRY" "$@" 2>&1) || true
RC=$?

# 输出 exit code
echo "exit=${RC}"

# 把合并输出经 normalize 后只保留关键前缀行
echo "$COMBINED_OUT" | bash "$NORMALIZE"
