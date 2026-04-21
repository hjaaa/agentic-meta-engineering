#!/usr/bin/env bash
# 一次性迁移脚本：把仓库从 trunk-based 升级到 git-flow（引入 develop 分支）
#
# 对应 context/team/git-workflow.md 步骤 8/9/10。
# 默认 dry-run，加 --apply 才真正执行；涉及远端的命令仍需人工确认。
#
# 使用：
#   bash scripts/migrate-to-develop.sh                  # dry-run 打印将执行的命令
#   bash scripts/migrate-to-develop.sh --apply          # 执行本地操作（创建 develop 分支）
#   bash scripts/migrate-to-develop.sh --apply --push   # 额外推送到 origin
#
# 不会自动：
#   - 修改 GitHub 仓库默认分支（需 GitHub UI 或 gh api 手动执行）
#   - rebase 已有 feat/req-* 分支（打印清单，需逐个人工确认）
#
set -euo pipefail

APPLY=0
DO_PUSH=0
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        --push) DO_PUSH=1 ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) echo "未知参数：$arg" >&2; exit 1 ;;
    esac
done

run() {
    echo "+ $*"
    if [ "$APPLY" = "1" ]; then
        eval "$@"
    fi
}

header() {
    echo ""
    echo "=== $* ==="
}

### 1. 校验当前状态
header "1. 校验"

CURRENT_BRANCH=$(git branch --show-current)
echo "当前分支：$CURRENT_BRANCH"

if [ -n "$(git status --porcelain)" ]; then
    echo "❌ 工作区不干净，请先处理 uncommitted changes" >&2
    exit 1
fi

if git rev-parse --verify develop >/dev/null 2>&1; then
    echo "⚠️  本地 develop 分支已存在，跳过创建步骤"
    DEVELOP_EXISTS=1
else
    DEVELOP_EXISTS=0
fi

### 2. 创建 develop 分支（基于 main）
header "2. 创建 develop 分支"

if [ "$DEVELOP_EXISTS" = "0" ]; then
    run "git checkout main"
    run "git pull --ff-only origin main || true"
    run "git checkout -b develop"
else
    echo "（跳过，本地已有 develop）"
fi

### 3. 推送到远端
header "3. 推送 develop 到 origin"

if [ "$DO_PUSH" = "1" ]; then
    run "git push -u origin develop"
else
    echo "（未指定 --push，跳过）"
    echo "手动执行：git push -u origin develop"
fi

### 4. 列出待 rebase 的 in-flight 分支
header "4. 列出需要 rebase 的 feat/req-* 分支"

INFLIGHT=$(git branch --list 'feat/req-*' | sed 's/^[* ] //' || true)
if [ -z "$INFLIGHT" ]; then
    echo "（无在制 feat/req-* 分支）"
else
    echo "以下分支当前基于 main，建议 rebase 到 develop："
    echo "$INFLIGHT" | while read -r b; do
        [ -z "$b" ] && continue
        echo "  - $b"
        echo "    命令：git rebase --onto develop main $b"
    done
    echo ""
    echo "⚠️  rebase 会改写历史，请在每条分支上人工确认后执行。"
fi

### 5. GitHub 默认分支切换（仅提示）
header "5. GitHub 默认分支切换（手动）"

cat <<'EOF'
远程仓库设置里把默认分支改为 develop：
  - Web UI：Settings → Branches → Default branch → develop
  - 或 gh 命令（需要 admin 权限）：
      gh api -X PATCH repos/:owner/:repo -f default_branch=develop

切换后，新 PR 默认 target 变为 develop，feat/req-* → develop 的流程才正式生效。
EOF

### 6. 回归建议
header "6. 回归验证建议"

cat <<'EOF'
跑一遍 mini 需求验证端到端：
  1) /requirement:new 验证新分支是否基于 develop
  2) 开发 → /code-review
  3) /requirement:submit 验证 PR target 是否自动指向 develop
  4) 构造一个 hotfix：
       git checkout main && git checkout -b hotfix/test-migration
       （空提交也行）
       git checkout main && git merge --no-ff hotfix/test-migration
       git checkout develop && git cherry-pick <fix-commit>
EOF

echo ""
if [ "$APPLY" = "1" ]; then
    echo "✅ 本地操作已执行。远端推送与 GitHub 默认分支切换请按上文手动完成。"
else
    echo "ℹ️  Dry-run 结束。确认无误后加 --apply 重跑。"
fi
