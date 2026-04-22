#!/usr/bin/env bash
# check-meta.sh —— meta.yaml schema 校验入口
#
# 用法：
#   bash scripts/check-meta.sh requirements/REQ-2026-001/meta.yaml
#   bash scripts/check-meta.sh --all
#   bash scripts/check-meta.sh --all --strict
#
# 退出码：
#   0 — 通过
#   1 — 存在 error（或 --strict 下存在 warning）
#   2 — 脚本自身异常
#
# 事实源：context/team/engineering-spec/meta-schema.yaml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/lib/check_meta.py" "$@"
