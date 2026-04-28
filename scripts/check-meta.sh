#!/usr/bin/env bash
# check-meta.sh —— meta.yaml schema 校验入口（薄壳兼容层）
#
# 本脚本是薄壳 exec runner，直接委托统一门禁 runner（adapter 模式）。
# 兼容期保留，F-004 阶段才删除旧入口。
#
# 用法（不变）：
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

# 薄壳 exec runner（adapter 模式）：委托统一门禁 runner，保持旧入口行为等价
exec python3 "${SCRIPT_DIR}/gates/run.py" --trigger=adapter --legacy=check-meta "$@"
