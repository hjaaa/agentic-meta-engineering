#!/usr/bin/env bash
# post-dev-verify.sh —— 开发后总门禁：feature done 前必跑（薄壳兼容层）
#
# 注意：本脚本已由 F-002 改写，核心逻辑切到统一门禁 runner。
#       兼容期保留旧参数格式，F-004 阶段才重构。
#
# 用法：
#   bash scripts/post-dev-verify.sh --requirement <REQ-ID> --feature <F-XXX>
#   bash scripts/post-dev-verify.sh --requirement <REQ-ID>           # 不指定 feature
#   bash scripts/post-dev-verify.sh                                  # 骨架自身开发
#   bash scripts/post-dev-verify.sh --skeleton-only                  # 跳过下游扩展点
#
# 策略：
#   - 不 fail-fast：每个 checker 都跑完再汇总，一次暴露所有问题
#   - 任一 error → exit 1
#   - "feature 完成"的定义 = 此脚本通过 + /code-review approved
#
# 内部调用：
#   python3 scripts/gates/run.py --trigger=post-dev [--req=REQ-ID] --strict
#   （兼容旧行为：逐步迁移，task file exists 校验保留在本脚本）
#
# 退出码：
#   0 — 全过
#   1 — 任一项失败
#   2 — 脚本自身异常

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ——— 参数解析 ———
REQ_ID=""
FEATURE_ID=""
SKELETON_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --requirement)   REQ_ID="${2:-}";     shift 2 ;;
    --feature)       FEATURE_ID="${2:-}"; shift 2 ;;
    --skeleton-only) SKELETON_ONLY=1;     shift ;;
    -h|--help)       sed -n '1,30p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

# ——— 颜色 ———
if [[ -t 1 ]]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; CYAN=$'\033[36m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  RED=""; GREEN=""; CYAN=""; BOLD=""; RESET=""
fi

PASSED=0
FAILED=0
SKIPPED=0
FAILURES=()

# run_step <name> <skip|run> <cmd...>
run_step() {
  local name="$1"; shift
  local mode="$1"; shift

  if [[ "$mode" == "skip" ]]; then
    local reason="$1"
    printf "  %s[-]%s %-26s %sskipped%s (%s)\n" "$CYAN" "$RESET" "$name" "$CYAN" "$RESET" "$reason"
    SKIPPED=$((SKIPPED + 1))
    return 0
  fi

  local start=$SECONDS
  local output
  output=$("$@" 2>&1)
  local rc=$?
  local elapsed=$((SECONDS - start))

  if [[ $rc -eq 0 ]]; then
    printf "  %s[✓]%s %-26s (%ss)\n" "$GREEN" "$RESET" "$name" "$elapsed"
    PASSED=$((PASSED + 1))
  else
    printf "  %s[✗]%s %-26s (%ss)  %sexit=%d%s\n" "$RED" "$RESET" "$name" "$elapsed" "$RED" "$rc" "$RESET"
    printf '%s\n' "$output" | head -20 | sed 's/^/       /'
    FAILED=$((FAILED + 1))
    FAILURES+=("$name")
  fi
}

# ——— 头 ———
header="post-dev-verify"
[[ -n "$REQ_ID" ]]     && header="$header · $REQ_ID"
[[ -n "$FEATURE_ID" ]] && header="$header · $FEATURE_ID"
printf "%s%s%s\n\n" "$BOLD" "$header" "$RESET"

cd "$REPO_ROOT"

# ——— 1. feature task.md 存在校验（保留旧行为；runner 的 workspace_clean 处理工作区） ———
if [[ -n "$FEATURE_ID" ]]; then
  if [[ -n "$REQ_ID" ]]; then
    task_file="requirements/${REQ_ID}/artifacts/tasks/${FEATURE_ID}.md"
    run_step "task file exists" run test -f "$task_file"
  else
    run_step "task file exists" skip "需要 --requirement 才能定位"
  fi
fi

# ——— 2. 统一门禁 runner（post-dev trigger，切到 runner 是 F-002 核心改造） ———
RUNNER_ARGS=(python3 scripts/gates/run.py --trigger=post-dev --strict)
[[ -n "$REQ_ID" ]] && RUNNER_ARGS+=(--req "$REQ_ID")

run_step "gate-runner (post-dev)" run "${RUNNER_ARGS[@]}"

# ——— 3. 下游项目扩展点 ———
if [[ $SKELETON_ONLY -eq 0 ]]; then
  if [[ -x scripts/project-verify.sh ]]; then
    run_step "project-verify" run bash scripts/project-verify.sh
  else
    run_step "project-verify" skip "scripts/project-verify.sh 不存在（下游项目可扩展）"
  fi
fi

# ——— 汇总 ———
printf "\n"
printf "%sSummary:%s %d passed, %d failed, %d skipped\n" "$BOLD" "$RESET" "$PASSED" "$FAILED" "$SKIPPED"

if [[ $FAILED -gt 0 ]]; then
  printf "%s失败项：%s %s\n" "$RED" "$RESET" "${FAILURES[*]}"
  exit 1
fi

exit 0
