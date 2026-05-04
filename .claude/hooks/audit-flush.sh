#!/usr/bin/env bash
# audit-flush.sh：SessionEnd hook，把 audit/.queue/*.log flush 到 JSON 桶。
# 失败完全静默——下次 SessionEnd 再试（D-005 best-effort）。
python3 scripts/lib/audit_flush.py 2>/dev/null || true
