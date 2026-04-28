#!/usr/bin/env bash
# PreToolUse hook 薄壳层（F-003 H5 改造）。
#
# 历史：原本同时承担分支拦截 + 路径拦截 + Bash 写保护。
# 现在：所有规则下沉到 scripts/gates/plugins/ 下的两个 plugin：
#   - GATE-PROTECT-BRANCH   分支级 + Edit/Write reviews/*.json 路径级
#   - GATE-BASH-WRITE-PROTECT  Bash 写 reviews/*.json 8+ 形态拦截
# 本脚本只透传 stdin 给 triggers/pre_tool_use.sh，由它调统一 runner。
#
# 为何保留这个文件：.claude/hooks/ 路径是 Claude Code Hook 的固定锚点，
# 不能改名；薄壳化让规则升级不需要动 .claude 配置。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

exec bash "${REPO_ROOT}/scripts/gates/triggers/pre_tool_use.sh" "$@"
