#!/usr/bin/env bash
# pre-commit-rename-guard.sh — 阻止新增 requirements/REQ- 字面量引用
#
# 触发：git pre-commit hook（由 scripts/git-hooks/pre-commit 或直接调用）
# 行为契约：
#   - git diff --cached 中新增（+行）含 requirements/REQ- 字面量 → exit 2 + stderr 提示
#   - 命中白名单路径 → 放行（exit 0）
#   - *.md 文件中 markdown 引用块（> ...）或代码块（``` ``` ```）内的字面量 → 放行
#   - 设置 CLAUDE_GATES_GLOBAL_BYPASS="<reason（≥8字符）>" → 绕过并记录
#
# 安装方式（详见 context/team/engineering-spec/migration/2026-05-runs-rename.md）：
#   # 方式一：symlink（推荐，与主 pre-commit hook 并存）
#   ln -sf ../../scripts/git-hooks/pre-commit-rename-guard.sh .git/hooks/pre-commit-rename-guard
#
#   # 方式二：在既有 scripts/git-hooks/pre-commit 末尾追加调用
#   bash scripts/git-hooks/pre-commit-rename-guard.sh
#
# 与 .claude/hooks/pre-tool-use-guard.sh 的关系：
#   - 本脚本是 git pre-commit hook，拦截 git commit 操作
#   - pre-tool-use-guard.sh 是 Claude Code tool hook，拦截 AI Edit/Write/Bash
#   - BYPASS 口径相同（reason ≥ 8 字符），但各自独立触发

set -uo pipefail

# ============================================================================
# 常量
# ============================================================================

readonly HOOK_NAME="pre-commit-rename-guard"

# 内置白名单路径前缀或 pattern（bash extglob 格式）
# 命中时放行，不阻止 commit
readonly -a WHITELIST_PATTERNS=(
    "requirements/INDEX.md"
    "context/team/engineering-spec/migration/"
    "scripts/lib/migrate_requirements_to_runs.py"
    "scripts/git-hooks/pre-commit-rename-guard.sh"
    "tests/tools/test_migrate_requirements.py"
    "tests/tools/fixtures/migrate_requirements/"
)

# ============================================================================
# 工具函数
# ============================================================================

# 检测路径是否命中白名单
is_whitelisted() {
    local file_path="$1"
    for pattern in "${WHITELIST_PATTERNS[@]}"; do
        if [[ "$file_path" == "$pattern"* ]] || [[ "$file_path" == *"$pattern"* ]]; then
            return 0
        fi
    done
    # plan.md 历史 ADR 文件（requirements/REQ-*/plan.md）
    if [[ "$file_path" =~ ^requirements/REQ-[^/]+/plan\.md$ ]]; then
        return 0
    fi
    # archived 目录
    if [[ "$file_path" =~ \.archived/ ]]; then
        return 0
    fi
    return 1
}

# 检测行是否在 markdown 引用块（> ...）内
is_md_quote_line() {
    local line="$1"
    # 去掉 diff 前缀（+），取正文
    local content="${line:1}"
    # 去前置空格
    content="${content#"${content%%[![:space:]]*}"}"
    [[ "$content" == ">"* ]]
}

# 检测行是否在 markdown 代码块内（简化：行以 ``` 开头）
# 状态由调用方的 in_code_block 变量维护
is_code_fence() {
    local line="$1"
    local content="${line:1}"
    content="${content#"${content%%[![:space:]]*}"}"
    [[ "$content" == '```'* ]] || [[ "$content" == '~~~'* ]]
}

# ============================================================================
# 全局 BYPASS 逻辑（与 pre-tool-use-guard.sh 同口径）
# ============================================================================

check_bypass() {
    local bypass="${CLAUDE_GATES_GLOBAL_BYPASS:-}"
    if [[ -z "$bypass" ]]; then
        return 1  # 未设置 bypass
    fi

    # 把换行/回车替换成空格（防注入）
    local cleaned="${bypass//$'\n'/ }"
    cleaned="${cleaned//$'\r'/ }"
    # strip 前后空白
    local stripped="${cleaned#"${cleaned%%[![:space:]]*}"}"
    stripped="${stripped%"${stripped##*[![:space:]]}"}"

    if (( ${#stripped} < 8 )); then
        cat >&2 <<EOF
[${HOOK_NAME}] BLOCKED: CLAUDE_GATES_GLOBAL_BYPASS reason 太短（strip 后 ${#stripped} 字符，要求 >= 8）。
请提供有意义的原因，例如：CLAUDE_GATES_GLOBAL_BYPASS="emergency-fix-pr-123"
EOF
        exit 2
    fi

    echo "[${HOOK_NAME}] BYPASS 生效: ${cleaned}" >&2
    exit 0
}

# ============================================================================
# 主逻辑
# ============================================================================

main() {
    # 0. 全局 BYPASS 检查
    check_bypass

    # 1. 获取 staged diff（+行 = 新增行）
    local diff_output
    diff_output="$(git diff --cached --unified=0 2>/dev/null)" || {
        # git diff 失败（非 git 仓库等）→ fail-open
        exit 0
    }

    if [[ -z "$diff_output" ]]; then
        exit 0
    fi

    # 2. 逐行扫描 diff，检测新增的 requirements/REQ- 字面量
    local current_file=""
    local in_code_block=0
    local found_violations=0
    local violation_lines=()

    while IFS= read -r raw_line; do
        # diff 文件头：+++ b/<path>
        if [[ "$raw_line" =~ ^\+\+\+[[:space:]]b/(.+)$ ]]; then
            current_file="${BASH_REMATCH[1]}"
            in_code_block=0
            continue
        fi

        # 删除行（-）和上下文行（空格开头）跳过
        if [[ "$raw_line" != "+"* ]] || [[ "$raw_line" == "+++"* ]]; then
            # 但仍需追踪 markdown 代码块状态（上下文行中的 ``` 会影响状态）
            local ctx_content="${raw_line:1}"
            ctx_content="${ctx_content#"${ctx_content%%[![:space:]]*}"}"
            if [[ "$ctx_content" == '```'* ]] || [[ "$ctx_content" == '~~~'* ]]; then
                if (( in_code_block == 0 )); then
                    in_code_block=1
                else
                    in_code_block=0
                fi
            fi
            continue
        fi

        # 新增行（+开头）：检测是否有 requirements/REQ- 字面量
        if [[ "$raw_line" != *"requirements/REQ-"* ]]; then
            # 追踪代码块状态
            if is_code_fence "$raw_line"; then
                if (( in_code_block == 0 )); then
                    in_code_block=1
                else
                    in_code_block=0
                fi
            fi
            continue
        fi

        # 命中：有 requirements/REQ- 字面量

        # 2a. 白名单放行
        if is_whitelisted "$current_file"; then
            continue
        fi

        # 2b. 代码块内放行（叙述性引用）
        if (( in_code_block == 1 )); then
            # 检查是否是代码块结束行（fence 结束后取消 in_code_block）
            if is_code_fence "$raw_line"; then
                in_code_block=0
            fi
            continue
        fi

        # 2c. markdown 引用块（> ...）内放行
        if [[ "$current_file" == *.md ]] && is_md_quote_line "$raw_line"; then
            continue
        fi

        # 2d. 追踪代码块开闭
        if is_code_fence "$raw_line"; then
            if (( in_code_block == 0 )); then
                in_code_block=1
            else
                in_code_block=0
            fi
            continue
        fi

        # 3. 确认违规
        (( found_violations++ )) || true
        violation_lines+=("  ${current_file}: ${raw_line:1}")

    done <<< "$diff_output"

    # 4. 输出结果
    if (( found_violations > 0 )); then
        cat >&2 <<EOF

[${HOOK_NAME}] BLOCKED: 检测到新增 requirements/REQ- 字面量引用（${found_violations} 处）。

迁移到 runs/ 体系后，新引用请使用 runs/REQ-... 路径。
违规位置：
$(printf '%s\n' "${violation_lines[@]}")

修复建议：
  1. 把路径改为 runs/REQ-... 形式
  2. 或用 _resolve_run_dir(req_id) 函数（双路径 loader，兼容迁移过渡期）
  3. 叙述性引用（markdown 代码块 / 引用块）无需改写，已自动放行

紧急绕过（慎用）：
  CLAUDE_GATES_GLOBAL_BYPASS="<原因（≥8字符）>" git commit ...

EOF
        exit 2
    fi

    exit 0
}

main "$@"
