#!/usr/bin/env bash
# audit-flush.sh：SessionEnd hook，把 audit/.queue/*.log flush 到 JSON 桶。
# 失败完全静默——下次 SessionEnd 再试（D-005 best-effort）。
#
# Codex P1（PR #54 round-2）：脚本路径必须锚到 hook 文件所在仓库根，否则
# SessionEnd 在 cwd≠repo 时找不到 audit_flush.py，stderr 重定向 + || true
# 把 file-not-found 静默吞掉，audit/.queue/*.log 永远不被 flush。
_HOOK_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# .claude/hooks/audit-flush.sh → repo 根 = ../../
_REPO_ROOT="$( cd "$_HOOK_DIR/../.." && pwd )"
python3 "$_REPO_ROOT/scripts/lib/audit_flush.py" 2>/dev/null || true
