#!/usr/bin/env bash
# 用途：把 stderr 归一化以做 snapshot 对比（来源：requirements/REQ-2026-002/artifacts/requirement.md:122）
# 输入：stdin
# 输出：归一化后只保留关键前缀的行（ERROR / WARNING / E### / W### / R### / CR-#）
#
# 设计权威：requirements/REQ-2026-002/artifacts/detailed-design.md §5.1
#
# 实现说明：
#   - 旧入口（scripts/check-meta.sh）与新入口（python scripts/gates/run.py --trigger=adapter
#     --legacy=check-meta）跑同一个 meta.yaml 时，stderr 会包含 ANSI / 绝对路径 / 时间戳等
#     易变信息；本脚本统一抹平，并仅保留可比对的"关键前缀行"。
#   - 不依赖 GNU sed 的 PCRE 扩展（macOS BSD sed 兼容）。
#   - 关键前缀正则用 grep -E（基础 ERE，跨平台）。

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"

# 关键前缀正则：见上方设计权威
KEY_PATTERN='(ERROR|WARNING|✗|❌|E[0-9]+|W[0-9]+|R[0-9]+|CR-[0-9]+)'

sed_ansi='s/\x1b\[[0-9;]*m//g'
sed_path="s|${REPO_ROOT}/||g"
sed_ts='s/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\} [0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}/<TS>/g'

sed -E \
    -e "${sed_ansi}" \
    -e "${sed_path}" \
    -e "${sed_ts}" \
  | grep -E "${KEY_PATTERN}" || true
