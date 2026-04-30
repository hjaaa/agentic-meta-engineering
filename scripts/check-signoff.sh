#!/usr/bin/env bash
# 单一职责：读 verdict 文件，按 is_signed_off 返回 0（已签）/ 1（未签）
# 任何下游判定（feature-lifecycle-manager / GATE-REVIEW-VERDICT）必须走此脚本，
# 严禁 grep / awk / jq 自行解析 human_signoff.decision。
set -e
VERDICT="${1:?usage: check-signoff.sh <path-to-verdict.json>}"
exec python3 -c '
import json, sys
sys.path.insert(0, "scripts/lib")
from check_reviews import is_signed_off
sys.exit(0 if is_signed_off(json.load(open(sys.argv[1]))) else 1)
' "$VERDICT"
