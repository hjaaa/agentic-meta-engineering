#!/usr/bin/env bash
# check-index.sh —— INDEX.md 自动校验入口
#
# 用法：
#   bash scripts/check-index.sh               # 全量，含 warning
#   bash scripts/check-index.sh --strict      # CI 用：warning 也算失败
#
# 退出码：
#   0 — 通过
#   1 — 存在 error（或 --strict 下存在 warning）
#   2 — 脚本自身异常
#
# 配置：scripts/lib/index-config.yaml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/lib/check_index.py" "$@"
