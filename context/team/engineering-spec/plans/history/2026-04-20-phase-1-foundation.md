# Phase 1 实施计划 · 基础设施 + 上下文文档

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Agentic Engineering 骨架的基础设施层——根配置、Hook、StatusLine、完整的 `context/` 文档树——让仓库在 clone 后立即呈现"开箱体验"的 50%（状态行、分支保护、全套团队文档可读）。

**Architecture:** 文件分四组——(1) 根配置（`CLAUDE.md` / `README.md` / `.gitignore` / `.claude/settings.json` / `.mcp.json`）；(2) 脚本（3 Hooks + StatusLine）；(3) 体系自身规范（`context/team/engineering-spec/`）；(4) 团队知识与落地（`context/team/{git-workflow,tool-chain,ai-collaboration,onboarding,rollout}`）。所有内容严格遵守设计文档第 1-7 节。

**Tech Stack:** Bash（hooks / statusline）、Markdown（全部文档）、YAML（meta / feedback-log）、JSON（settings / mcp）。

**Reference:** 全部内容依据 `context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md`。每个 Task 标注 `[Spec §X.Y]` 指向设计文档对应章节。

**Phase 1 完成标准:**
- `git clone` 后打开 Claude Code，状态行能显示分支信息
- 在 `main` 分支上尝试 `Edit` 操作会被 Hook 阻止
- `context/` 目录可被完整阅读，Agent 可检索到团队知识
- 无 Command / Skill / Agent 功能（留给 Phase 2/3）

---

## 文件结构映射

本 Phase 创建的全部文件：

```
根配置（5 个）
├── .gitignore
├── README.md
├── CLAUDE.md
├── .claude/settings.json
├── .claude/settings.local.json.example
└── .mcp.json

脚本（4 个）
├── .claude/hooks/protect-branch.sh
├── .claude/hooks/auto-progress-log.sh
├── .claude/hooks/stop-session-save.sh
└── .claude/statusline.sh

Context 树 INDEX（6 个）
├── context/INDEX.md
├── context/team/INDEX.md
├── context/project/INDEX.md
├── context/team/engineering-spec/INDEX.md
├── context/team/experience/INDEX.md
└── requirements/INDEX.md

团队通用知识（4 个）
├── context/team/git-workflow.md
├── context/team/tool-chain.md
├── context/team/ai-collaboration.md
└── context/team/feedback-log.yaml

体系自身规范（8 个）
├── context/team/engineering-spec/design-guidance/four-layer-hierarchy.md
├── context/team/engineering-spec/design-guidance/context-engineering.md
├── context/team/engineering-spec/design-guidance/compounding.md
├── context/team/engineering-spec/tool-design-spec/command-spec.md
├── context/team/engineering-spec/tool-design-spec/skill-spec.md
├── context/team/engineering-spec/tool-design-spec/subagent-spec.md
└── context/team/engineering-spec/iteration-sop.md

（specs/ 下已有本次设计文档）

入门指南 + 学习路径（9 个）
├── context/team/onboarding/agentic-engineer-guide.md
└── context/team/onboarding/learning-path/
    ├── 01-environment.md
    ├── 02-first-conversation.md
    ├── 03-command-skill-agent.md
    ├── 04-first-requirement.md
    ├── 05-code-review.md
    ├── 06-knowledge-sinking.md
    ├── 07-custom-command.md
    └── 08-custom-skill.md

团队落地（2 个）
├── context/team/rollout/four-phase-strategy.md
└── context/team/rollout/embedded-push-playbook.md
```

**合计：38 个文件**

---

## Task 1：初始化 `.gitignore`

**Files:**
- Create: `.gitignore`

**Reference:** Spec §6.6

- [ ] **Step 1：创建 `.gitignore`**

```
# 个人 Claude Code 配置覆盖（不入库）
.claude/settings.local.json

# 代码审查运行态临时文件（每次 /code-review 会重写）
.review-scope.json

# macOS
.DS_Store

# 编辑器
.idea/
.vscode/
*.swp
```

- [ ] **Step 2：验证**

```bash
cat .gitignore
```

应看到上述 4 段注释标题。

- [ ] **Step 3：Commit**

```bash
git add .gitignore
git commit -m "chore: 初始化 .gitignore"
```

---

## Task 2：创建 `README.md`（面向团队）

**Files:**
- Create: `README.md`

**Reference:** Spec §0.1（目标）+ §8.3（入门指南要点）

- [ ] **Step 1：创建 `README.md`**

内容（逐字写入）：

```markdown
# AgenticMetaEngineering

基于 Claude Code 的团队级 Agentic Engineering 工程骨架。`git clone` 即获得全部能力。

## 这是什么

一套让 AI Agent 承担需求全生命周期研发工作的工程体系，对齐文章《认知重建之后，步入 Agentic Engineering 的工程革命》的最终成型版。

核心能力（Phase 1 完成后逐步可用）：

- 8 阶段需求生命周期管理（含强制门禁）
- 多 Agent 并行代码审查（7 专项 checker + 1 综合裁决）
- 三层记忆系统（工作 / 溢出 / 长期）与跨会话恢复
- 团队知识沉淀与复利
- 保护分支 Hook / StatusLine / 开箱即用的 MCP

## 快速开始（新人 30 分钟）

1. 克隆仓库：`git clone <repo-url>`
2. 读 30 秒版入门：`context/team/onboarding/agentic-engineer-guide.md`
3. 依次完成前 6 阶段学习：`context/team/onboarding/learning-path/01-environment.md` → `06-knowledge-sinking.md`
4. 遇到问题运行 `/agentic:help`

## 设计文档

- 骨架设计：`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md`
- 体系自身规范：`context/team/engineering-spec/`
- 迭代方式：`context/team/engineering-spec/iteration-sop.md`

## 反馈

运行 `/agentic:feedback`，会追加到 `context/team/feedback-log.yaml`。

## 目录结构

完整结构见设计文档第 2 节。简要：

- `.claude/` — Claude Code 扩展（Command / Skill / Agent / Hook / StatusLine）
- `context/` — 知识库（team / project / engineering-spec）
- `requirements/` — 需求产出物（全部入库）
- `.mcp.json` — MCP 配置（公开 MCP 开箱，内部 MCP 占位）
```

- [ ] **Step 2：验证**

```bash
wc -l README.md
head -5 README.md
```

期望：< 60 行；第一行是 `# AgenticMetaEngineering`。

- [ ] **Step 3：Commit**

```bash
git add README.md
git commit -m "docs: 添加 README 作为团队入口"
```

---

## Task 3：创建 `.claude/settings.json`

**Files:**
- Create: `.claude/settings.json`
- Create: `.claude/settings.local.json.example`

**Reference:** Spec §7.4

- [ ] **Step 1：创建 `.claude/settings.json`**

内容（逐字写入）：

```json
{
  "permissions": {
    "allow": [
      "Bash(git status)",
      "Bash(git diff:*)",
      "Bash(git log:*)",
      "Bash(git branch:*)",
      "Bash(git checkout:*)",
      "Bash(ls:*)",
      "Read",
      "Grep",
      "Glob"
    ],
    "ask": [
      "Bash(git push:*)",
      "Bash(git commit:*)",
      "Edit",
      "Write"
    ],
    "deny": [
      "Bash(rm -rf:*)",
      "Bash(git reset --hard:*)",
      "Bash(git push --force:*)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write",
        "hooks": [{"type": "command", "command": ".claude/hooks/protect-branch.sh"}]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|Bash",
        "hooks": [{"type": "command", "command": ".claude/hooks/auto-progress-log.sh"}]
      }
    ],
    "Stop": [
      {
        "hooks": [{"type": "command", "command": ".claude/hooks/stop-session-save.sh"}]
      }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": ".claude/statusline.sh"
  }
}
```

- [ ] **Step 2：创建 `.claude/settings.local.json.example`**

```json
{
  "// 说明": "这是个人级覆盖模板。复制为 settings.local.json（已 gitignore）后按需修改。",
  "model": "sonnet",
  "env": {
    "// 示例": "设置自定义环境变量供 Hook 使用",
    "// CLAUDE_PROTECTED_BRANCHES": "main,master,release"
  }
}
```

- [ ] **Step 3：验证 JSON 合法**

```bash
python3 -m json.tool .claude/settings.json > /dev/null && echo "settings.json OK"
python3 -m json.tool .claude/settings.local.json.example > /dev/null && echo "example OK"
```

两个都应输出 OK。

- [ ] **Step 4：Commit**

```bash
git add .claude/settings.json .claude/settings.local.json.example
git commit -m "feat(claude-code): 添加项目级 settings 和个人覆盖模板"
```

---

## Task 4：创建 `.mcp.json`

**Files:**
- Create: `.mcp.json`

**Reference:** Spec §7.5

- [ ] **Step 1：创建 `.mcp.json`**

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@context7/mcp-server"]
    },
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp"]
    }
  }
}
```

注：JSON 不支持注释，所以内部/商业 MCP 占位改放在 `README.md` 和 `context/team/onboarding/01-environment.md`。

- [ ] **Step 2：验证 JSON 合法**

```bash
python3 -m json.tool .mcp.json > /dev/null && echo "OK"
```

- [ ] **Step 3：Commit**

```bash
git add .mcp.json
git commit -m "feat(mcp): 默认启用 context7 和 chrome-devtools"
```

---

## Task 5：Hook - `protect-branch.sh`（TDD）

**Files:**
- Create: `.claude/hooks/protect-branch.sh`
- Create: `.claude/hooks/tests/test_protect-branch.sh`

**Reference:** Spec §7.1 / §7.2

**⚠️ Hook 输入机制注意**：Claude Code 实际用 **stdin JSON** 向 Hook 传递工具信息。为了便于测试，本 Hook 同时支持环境变量 `CLAUDE_HOOK_TOOL_NAME`（测试路径）和 stdin JSON（生产路径）。实现时优先读环境变量，空时 fallback 到 stdin JSON 的 `.tool_name` 字段。执行本 Task 时请核对最新 Claude Code Hook 文档调整 stdin 解析字段名。

- [ ] **Step 1：写失败的测试**

创建 `.claude/hooks/tests/test_protect-branch.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

HOOK=".claude/hooks/protect-branch.sh"
PASS=0
FAIL=0

assert_exit() {
    local expected=$1
    local actual=$2
    local name=$3
    if [ "$expected" = "$actual" ]; then
        echo "✓ $name"
        PASS=$((PASS+1))
    else
        echo "✗ $name (expected exit=$expected, got $actual)"
        FAIL=$((FAIL+1))
    fi
}

# 准备：建临时仓库并切到 main
TMPDIR=$(mktemp -d)
cd "$TMPDIR"
git init -q -b main
echo "a" > a.txt && git add a.txt && git commit -q -m init

# Test 1: main 分支 + Edit 工具 → exit 2
export CLAUDE_HOOK_TOOL_NAME="Edit"
set +e
bash -c "cd $TMPDIR && bash $OLDPWD/$HOOK"
actual=$?
set -e
assert_exit 2 $actual "main + Edit 应被阻止"

# Test 2: feature 分支 + Edit → exit 0
git checkout -q -b feat/test
set +e
bash -c "cd $TMPDIR && bash $OLDPWD/$HOOK"
actual=$?
set -e
assert_exit 0 $actual "feature 分支 + Edit 应放行"

# Test 3: main + Read 类工具 → exit 0（非写操作）
git checkout -q main
export CLAUDE_HOOK_TOOL_NAME="Read"
set +e
bash -c "cd $TMPDIR && bash $OLDPWD/$HOOK"
actual=$?
set -e
assert_exit 0 $actual "main + Read 应放行"

echo ""
echo "Passed: $PASS / Failed: $FAIL"
[ "$FAIL" = "0" ] || exit 1
```

加执行权限：

```bash
chmod +x .claude/hooks/tests/test_protect-branch.sh
```

- [ ] **Step 2：运行测试，确认失败**

```bash
OLDPWD=$(pwd) bash .claude/hooks/tests/test_protect-branch.sh
```

期望：无 hook 文件，失败。

- [ ] **Step 3：实现 `protect-branch.sh`**

```bash
#!/usr/bin/env bash
# PreToolUse hook: 阻止在受保护分支上直接做写操作
set -euo pipefail

# 受保护分支可通过环境变量覆盖
PROTECTED=${CLAUDE_PROTECTED_BRANCHES:-"main,master"}

# 获取工具名：优先环境变量（便于测试），否则解析 stdin JSON
TOOL=${CLAUDE_HOOK_TOOL_NAME:-}
if [ -z "$TOOL" ] && [ ! -t 0 ]; then
    # stdin 非 tty（被管道喂数据）时解析 JSON
    STDIN=$(cat)
    TOOL=$(echo "$STDIN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
fi

# 非写工具直接放行
case "$TOOL" in
    Edit|Write|MultiEdit) ;;
    Bash)
        # Bash 只拦写操作（简化：靠命令匹配关键词不可靠，这里保守放行；
        # 更严格的命令拦截依赖 settings.json 的 deny 规则）
        exit 0
        ;;
    *) exit 0 ;;
esac

# 取当前分支
BRANCH=$(git branch --show-current 2>/dev/null || echo "")
if [ -z "$BRANCH" ]; then
    exit 0  # 不在 git 仓库，放行
fi

# 分支匹配检查
IFS=',' read -ra BRANCHES <<< "$PROTECTED"
for b in "${BRANCHES[@]}"; do
    if [ "$BRANCH" = "$b" ]; then
        echo "❌ 禁止在受保护分支 [$BRANCH] 上直接写操作。" >&2
        echo "   请先切换到 feature 分支：/requirement:new 会自动建分支" >&2
        exit 2
    fi
done

exit 0
```

加执行权限：

```bash
chmod +x .claude/hooks/protect-branch.sh
```

- [ ] **Step 4：运行测试，确认通过**

```bash
OLDPWD=$(pwd) bash .claude/hooks/tests/test_protect-branch.sh
```

期望：`Passed: 3 / Failed: 0`。

- [ ] **Step 5：Commit**

```bash
git add .claude/hooks/protect-branch.sh .claude/hooks/tests/test_protect-branch.sh
git commit -m "feat(hooks): 添加保护分支 hook，阻止 main 上的直接写操作"
```

---

## Task 6：Hook - `auto-progress-log.sh`（TDD）

**Files:**
- Create: `.claude/hooks/auto-progress-log.sh`
- Create: `.claude/hooks/tests/test_auto-progress-log.sh`

**Reference:** Spec §7.1 / §6.3

此 Hook 在 `PostToolUse`（Edit/Write/Bash）时触发，如果当前分支对应某个需求，追加一行到该需求的 `process.txt`。

**⚠️ 同 Task 5**：工具名同时支持环境变量 `CLAUDE_HOOK_TOOL_NAME`（测试）和 stdin JSON 的 `.tool_name` 字段（生产）。

- [ ] **Step 1：写失败的测试**

创建 `.claude/hooks/tests/test_auto-progress-log.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail

HOOK=".claude/hooks/auto-progress-log.sh"
PASS=0; FAIL=0

assert() {
    if eval "$1"; then echo "✓ $2"; PASS=$((PASS+1)); else echo "✗ $2"; FAIL=$((FAIL+1)); fi
}

TMPDIR=$(mktemp -d)
REPO=$TMPDIR/repo
mkdir -p "$REPO/requirements/REQ-001"
cat > "$REPO/requirements/REQ-001/meta.yaml" <<EOF
id: REQ-001
phase: definition
branch: feat/req-001
EOF
touch "$REPO/requirements/REQ-001/process.txt"

cd "$REPO"
git init -q -b feat/req-001
git add . && git commit -q -m init

# Test 1: 在对应分支上调用 hook，process.txt 应增加一行
export CLAUDE_HOOK_TOOL_NAME="Edit"
bash "$OLDPWD/$HOOK" > /dev/null 2>&1 || true
assert '[ $(wc -l < requirements/REQ-001/process.txt) -ge 1 ]' "process.txt 应被追加"

# Test 2: 分支和 meta.yaml 不匹配 → 不写
git checkout -q -b feat/other
lines_before=$(wc -l < requirements/REQ-001/process.txt)
bash "$OLDPWD/$HOOK" > /dev/null 2>&1 || true
lines_after=$(wc -l < requirements/REQ-001/process.txt)
assert "[ $lines_after -eq $lines_before ]" "分支不匹配时不应写 process.txt"

# Test 3: hook 失败不应阻塞（退出码 0）
cd /tmp  # 离开 git 仓库
set +e; bash "$OLDPWD/$HOOK"; rc=$?; set -e
assert "[ $rc -eq 0 ]" "非 git 仓库时应优雅退出"

echo ""; echo "Passed: $PASS / Failed: $FAIL"
[ $FAIL -eq 0 ] || exit 1
```

```bash
chmod +x .claude/hooks/tests/test_auto-progress-log.sh
```

- [ ] **Step 2：运行测试，确认失败**

```bash
OLDPWD=$(pwd) bash .claude/hooks/tests/test_auto-progress-log.sh
```

- [ ] **Step 3：实现**

```bash
#!/usr/bin/env bash
# PostToolUse hook: 追加进度日志到当前需求的 process.txt
set -uo pipefail

# 获取工具名：优先环境变量，否则解析 stdin JSON
TOOL=${CLAUDE_HOOK_TOOL_NAME:-}
if [ -z "$TOOL" ] && [ ! -t 0 ]; then
    STDIN=$(cat)
    TOOL=$(echo "$STDIN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
fi
TOOL=${TOOL:-unknown}

# 只对写类工具记录
case "$TOOL" in
    Edit|Write|MultiEdit|Bash) ;;
    *) exit 0 ;;
esac

# 取当前分支
BRANCH=$(git branch --show-current 2>/dev/null || echo "")
[ -z "$BRANCH" ] && exit 0

# 反查 requirements/*/meta.yaml 中 branch 字段匹配当前分支的目录
REQ_DIR=""
for meta in requirements/*/meta.yaml; do
    [ -f "$meta" ] || continue
    META_BRANCH=$(grep -E '^branch:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
    if [ "$META_BRANCH" = "$BRANCH" ]; then
        REQ_DIR=$(dirname "$meta")
        break
    fi
done

[ -z "$REQ_DIR" ] && exit 0

# 取当前 phase
PHASE=$(grep -E '^phase:' "$REQ_DIR/meta.yaml" 2>/dev/null | head -1 | awk '{print $2}')
PHASE=${PHASE:-unknown}

# 追加日志
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
echo "$TS [$PHASE] tool=$TOOL" >> "$REQ_DIR/process.txt"

exit 0
```

```bash
chmod +x .claude/hooks/auto-progress-log.sh
```

- [ ] **Step 4：运行测试，确认通过**

```bash
OLDPWD=$(pwd) bash .claude/hooks/tests/test_auto-progress-log.sh
```

期望：`Passed: 3 / Failed: 0`

- [ ] **Step 5：Commit**

```bash
git add .claude/hooks/auto-progress-log.sh .claude/hooks/tests/test_auto-progress-log.sh
git commit -m "feat(hooks): 添加 auto-progress-log hook 自动记录需求进度"
```

---

## Task 7：Hook - `stop-session-save.sh`（TDD）

**Files:**
- Create: `.claude/hooks/stop-session-save.sh`
- Create: `.claude/hooks/tests/test_stop-session-save.sh`

**Reference:** Spec §7.1 / §6.3

会话结束时打 `SESSION_END` 标记到 `process.txt`。

- [ ] **Step 1：写失败的测试**

创建 `.claude/hooks/tests/test_stop-session-save.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
HOOK=".claude/hooks/stop-session-save.sh"
PASS=0; FAIL=0
assert() { if eval "$1"; then echo "✓ $2"; PASS=$((PASS+1)); else echo "✗ $2"; FAIL=$((FAIL+1)); fi; }

TMPDIR=$(mktemp -d); REPO=$TMPDIR/repo
mkdir -p "$REPO/requirements/REQ-001"
cat > "$REPO/requirements/REQ-001/meta.yaml" <<EOF
id: REQ-001
phase: testing
branch: feat/req-001
EOF
touch "$REPO/requirements/REQ-001/process.txt"

cd "$REPO"; git init -q -b feat/req-001; git add . && git commit -q -m init

bash "$OLDPWD/$HOOK" > /dev/null 2>&1 || true

assert 'grep -q "SESSION_END" requirements/REQ-001/process.txt' "应写入 SESSION_END 标记"

echo ""; echo "Passed: $PASS / Failed: $FAIL"
[ $FAIL -eq 0 ] || exit 1
```

```bash
chmod +x .claude/hooks/tests/test_stop-session-save.sh
```

- [ ] **Step 2：运行测试，确认失败**

```bash
OLDPWD=$(pwd) bash .claude/hooks/tests/test_stop-session-save.sh
```

- [ ] **Step 3：实现**

```bash
#!/usr/bin/env bash
# Stop hook: 会话结束时打 SESSION_END 标记
set -uo pipefail

BRANCH=$(git branch --show-current 2>/dev/null || echo "")
[ -z "$BRANCH" ] && exit 0

for meta in requirements/*/meta.yaml; do
    [ -f "$meta" ] || continue
    META_BRANCH=$(grep -E '^branch:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
    if [ "$META_BRANCH" = "$BRANCH" ]; then
        REQ_DIR=$(dirname "$meta")
        PHASE=$(grep -E '^phase:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
        TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        echo "$TS [${PHASE:-unknown}] SESSION_END" >> "$REQ_DIR/process.txt"
        break
    fi
done

exit 0
```

```bash
chmod +x .claude/hooks/stop-session-save.sh
```

- [ ] **Step 4：运行测试，确认通过**

- [ ] **Step 5：Commit**

```bash
git add .claude/hooks/stop-session-save.sh .claude/hooks/tests/test_stop-session-save.sh
git commit -m "feat(hooks): 添加 stop-session-save hook 标记会话结束"
```

---

## Task 8：StatusLine 脚本（TDD）

**Files:**
- Create: `.claude/statusline.sh`
- Create: `.claude/tests/test_statusline.sh`

**Reference:** Spec §7.3

输出格式：`[REQ-ID·阶段中文·N/8] 分支 ⬆ N ahead  |  🤖 模型`
无需求时：`[no-requirement] 分支`

- [ ] **Step 1：写失败的测试**

创建 `.claude/tests/test_statusline.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT=".claude/statusline.sh"
PASS=0; FAIL=0
assert() { if eval "$1"; then echo "✓ $2"; PASS=$((PASS+1)); else echo "✗ $2"; FAIL=$((FAIL+1)); fi; }

TMPDIR=$(mktemp -d); REPO=$TMPDIR/repo
mkdir -p "$REPO/requirements/REQ-001"
cat > "$REPO/requirements/REQ-001/meta.yaml" <<EOF
id: REQ-001
phase: detail-design
branch: feat/req-001
EOF

cd "$REPO"; git init -q -b feat/req-001; touch a && git add . && git commit -q -m init

# Test 1: 匹配到需求时应输出 REQ-001 和中文阶段名
out=$(bash "$OLDPWD/$SCRIPT" 2>/dev/null || echo "")
assert '[[ "$out" == *"REQ-001"* ]]' "应显示需求 ID"
assert '[[ "$out" == *"详细设计"* ]]' "应显示中文阶段名"
assert '[[ "$out" == *"5/8"* ]]' "应显示阶段进度 5/8"

# Test 2: 切换到无匹配的分支
git checkout -q -b feat/other
out=$(bash "$OLDPWD/$SCRIPT" 2>/dev/null || echo "")
assert '[[ "$out" == *"no-requirement"* ]]' "无需求时应显示 no-requirement"

echo ""; echo "Passed: $PASS / Failed: $FAIL"
[ $FAIL -eq 0 ] || exit 1
```

```bash
chmod +x .claude/tests/test_statusline.sh
```

- [ ] **Step 2：运行测试，确认失败**

- [ ] **Step 3：实现 `statusline.sh`**

```bash
#!/usr/bin/env bash
# StatusLine: [REQ-ID·阶段中文·N/8] 分支 ⬆ N ahead | 🤖 模型
set -uo pipefail

# 阶段英文 → 中文 + 序号
phase_info() {
    case "$1" in
        bootstrap)       echo "初始化·1/8" ;;
        definition)      echo "需求定义·2/8" ;;
        tech-research)   echo "技术预研·3/8" ;;
        outline-design)  echo "概要设计·4/8" ;;
        detail-design)   echo "详细设计·5/8" ;;
        task-planning)   echo "任务规划·6/8" ;;
        development)     echo "开发实施·7/8" ;;
        testing)         echo "测试验收·8/8" ;;
        *)               echo "未知·?/8" ;;
    esac
}

BRANCH=$(git branch --show-current 2>/dev/null || echo "")

# 查找匹配需求
REQ_ID=""; PHASE=""
if [ -n "$BRANCH" ]; then
    for meta in requirements/*/meta.yaml; do
        [ -f "$meta" ] || continue
        MB=$(grep -E '^branch:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
        if [ "$MB" = "$BRANCH" ]; then
            REQ_ID=$(grep -E '^id:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
            PHASE=$(grep -E '^phase:' "$meta" 2>/dev/null | head -1 | awk '{print $2}')
            break
        fi
    done
fi

# 领先 commit 数
AHEAD=0
if git remote get-url origin > /dev/null 2>&1; then
    AHEAD=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)
fi

# 模型（从 CLAUDE_MODEL 环境变量，默认 unknown）
MODEL=${CLAUDE_MODEL:-sonnet}

# 组装
if [ -n "$REQ_ID" ] && [ -n "$PHASE" ]; then
    PI=$(phase_info "$PHASE")
    LEFT="[${REQ_ID}·${PI}]"
else
    LEFT="[no-requirement]"
fi

AHEAD_PART=""
[ "$AHEAD" != "0" ] && AHEAD_PART=" ⬆ ${AHEAD} ahead"

echo "${LEFT} ${BRANCH:-detached}${AHEAD_PART}  |  🤖 ${MODEL}"
```

```bash
chmod +x .claude/statusline.sh
```

- [ ] **Step 4：运行测试**

```bash
OLDPWD=$(pwd) bash .claude/tests/test_statusline.sh
```

期望：`Passed: 4 / Failed: 0`

- [ ] **Step 5：Commit**

```bash
git add .claude/statusline.sh .claude/tests/test_statusline.sh
git commit -m "feat(statusline): 实现需求感知的状态行"
```

---

## Task 9：Context 树 INDEX 文件（6 个占位索引）

**Files:**
- Create: `context/INDEX.md`
- Create: `context/team/INDEX.md`
- Create: `context/project/INDEX.md`
- Create: `context/team/engineering-spec/INDEX.md`
- Create: `context/team/experience/INDEX.md`
- Create: `requirements/INDEX.md`

**Reference:** Spec §2 / §3.3

INDEX.md 的作用是\"先索引后深入\"的入口，禁止盲目搜索的前提（Spec §6.5）。

- [ ] **Step 1：创建 `context/INDEX.md`**

```markdown
# Context 知识库根索引

本目录是团队和 AI Agent 共用的长期记忆。

## 子目录

- [`team/`](team/INDEX.md) — 团队通用知识（Git / 工具链 / AI 协作规范 / 体系规范 / 入门 / 落地）
- [`project/`](project/INDEX.md) — 项目级知识，每个业务项目一个子目录

## 原则

详见 `team/engineering-spec/design-guidance/`。四条硬原则：

1. 文档即记忆：人和 AI 读同一份 Markdown
2. 位置即语义：路径承载分类信息，不依赖元数据
3. 渐进式披露：INDEX 先行，按需深入
4. 工具封装知识，不封装流程
```

- [ ] **Step 2：创建 `context/team/INDEX.md`**

```markdown
# 团队通用知识索引

## 基础规范

- [`git-workflow.md`](git-workflow.md) — 分支策略 / 提交规范 / PR 规范
- [`tool-chain.md`](tool-chain.md) — 团队通用工具链约定
- [`ai-collaboration.md`](ai-collaboration.md) — 和 AI 协作的基本准则（刨根问底 / 渐进输出）

## 体系自身

- [`engineering-spec/`](engineering-spec/INDEX.md) — 体系自身规范（设计指导 / 工具规范 / 迭代 SOP）

## 入门与落地

- [`onboarding/agentic-engineer-guide.md`](onboarding/agentic-engineer-guide.md) — 新人入门指南
- [`onboarding/learning-path/`](onboarding/learning-path/) — 8 阶段学习路径
- [`rollout/four-phase-strategy.md`](rollout/four-phase-strategy.md) — 团队落地四阶段策略
- [`rollout/embedded-push-playbook.md`](rollout/embedded-push-playbook.md) — 嵌入式推进手册

## 经验沉淀

- [`experience/`](experience/INDEX.md) — 跨项目沉淀的经验文档

## 运行态

- `feedback-log.yaml` — /agentic:feedback 写入位置（结构化条目）
```

- [ ] **Step 3：创建 `context/project/INDEX.md`**

```markdown
# 项目级知识索引

当前无任何业务项目知识入库。新项目的第一个需求开发过程中，Agent 会自动向 `context/project/<项目名>/` 沉淀架构、业务规则、接口约定等。

## 如何创建新项目

1. 用 `/requirement:new` 创建第一个需求时，在 `meta.yaml` 的 `project` 字段指定项目名
2. 开发过程中 Agent 将自动在 `context/project/<项目名>/` 下创建 INDEX.md 和初始知识文件
3. 需求验收后通过 `/knowledge:extract-experience` 把关键知识从 `requirements/<id>/notes.md` 转化为长期记忆
```

- [ ] **Step 4：创建 `context/team/engineering-spec/INDEX.md`**

```markdown
# 体系自身规范索引

本目录是 Agentic Engineering 骨架的"元"知识——关于体系本身如何设计、如何迭代。

## 设计指导（不可随意修改，改动需全员评审）

- [`design-guidance/four-layer-hierarchy.md`](design-guidance/four-layer-hierarchy.md) — 四层设计层级与自主权边界
- [`design-guidance/context-engineering.md`](design-guidance/context-engineering.md) — 上下文工程原则
- [`design-guidance/compounding.md`](design-guidance/compounding.md) — 复利工程原则

## 工具设计规范

- [`tool-design-spec/command-spec.md`](tool-design-spec/command-spec.md) — Command 硬约束（< 100 行）
- [`tool-design-spec/skill-spec.md`](tool-design-spec/skill-spec.md) — Skill 硬约束（SKILL.md < 2k token）
- [`tool-design-spec/subagent-spec.md`](tool-design-spec/subagent-spec.md) — Subagent 硬约束（返回 < 2k token，禁止嵌套）

## 迭代方式

- [`iteration-sop.md`](iteration-sop.md) — 项目迭代 SOP

## 历史设计文档

- [`specs/`](specs/) — 所有重要设计决定的存档
```

- [ ] **Step 5：创建 `context/team/experience/INDEX.md`**

```markdown
# 跨项目经验索引

初始为空。随团队开发经验积累，每条沉淀为一个 Markdown 文件。

## 什么值得沉淀

仅当以下条件至少一条成立时创建经验文档：

- 跨项目重复出现的知识
- AI 反复犯同类错误的场景
- 跨会话/跨人需要保留的状态

## 反面：不要沉淀的

- 偶发问题（只踩过一次）
- 简单自然对话就能传递的信息
- 只对单个需求有价值的细节（留在该需求的 `notes.md`）

## 格式约定

每份文件：
- 文件名 `kebab-case.md`，描述具体场景（如 `mysql-lock-wait-timeout-in-long-transaction.md`）
- 正文不超过 200 字
- 必须包含：问题、根因、解法、验证方法
```

- [ ] **Step 6：创建 `requirements/INDEX.md`**

```markdown
# 需求索引

本目录承载全部需求的全生命周期产出物。入 git，是团队资产。

## 当前无活跃需求

用 `/requirement:new` 创建你的第一个需求。

## 目录结构（每个需求一个子目录）

```
requirements/REQ-YYYY-NNN/
├── meta.yaml         # 元信息：阶段、分支、服务、门禁历史
├── plan.md           # 阶段级计划
├── process.txt       # 进度日志（Hook 自动追加）
├── notes.md          # 随手笔记
└── artifacts/
    ├── requirement.md          # 需求文档（阶段 2）
    ├── tech-feasibility.md     # 技术预研（阶段 3）
    ├── outline-design.md       # 概要设计（阶段 4）
    ├── detailed-design.md      # 详细设计（阶段 5）
    ├── features.json           # 功能点清单
    ├── tasks/<feature-id>.md   # 任务拆分（阶段 6）
    ├── review-YYYYMMDD-HHMMSS.md   # 代码审查报告（阶段 7）
    └── test-report.md          # 测试报告（阶段 8）
```
```

- [ ] **Step 7：验证所有 6 个文件存在且非空**

```bash
for f in context/INDEX.md context/team/INDEX.md context/project/INDEX.md \
         context/team/engineering-spec/INDEX.md context/team/experience/INDEX.md \
         requirements/INDEX.md; do
    [ -s "$f" ] && echo "✓ $f" || echo "✗ $f"
done
```

全部应为 `✓`。

- [ ] **Step 8：Commit**

```bash
git add context/INDEX.md context/team/INDEX.md context/project/INDEX.md \
        context/team/engineering-spec/INDEX.md context/team/experience/INDEX.md \
        requirements/INDEX.md
git commit -m "docs(context): 建立 Context 树骨架与 6 个索引文件"
```

---

## Task 10：`context/team/git-workflow.md`

**Files:**
- Create: `context/team/git-workflow.md`

**Reference:** Spec §7（受保护分支）+ 用户全局 CLAUDE.md §Git 规范

- [ ] **Step 1：创建文件**

内容：

```markdown
# Git 工作流规范

## 分支策略

- `main` — 受保护分支，禁止直接提交（由 `.claude/hooks/protect-branch.sh` 拦截）
- `feat/<requirement-id>` — 功能分支，`/requirement:new` 自动创建
- `hotfix/*` — 紧急修复
- `release/*` — 发版分支

## 提交规范（Conventional Commits）

格式：`<type>(<scope>): <subject>`

常用 type：

| type | 含义 |
|---|---|
| feat | 新功能 |
| fix | Bug 修复 |
| docs | 文档 |
| refactor | 重构（无行为变化） |
| test | 测试 |
| chore | 构建/配置 |

subject 用祈使句、简体中文、不超过 50 字符。

## PR 规范

- 标题 = 一句话描述，遵循上面的 Conventional Commits 格式
- 正文包含：**变更摘要 / 影响范围 / 验证方式 / 风险与回滚**（与全局 CLAUDE.md §11 一致）
- 至少 1 个 reviewer 通过才能合入
- 合入方式：Squash merge（保持 main 线性历史）

## 禁用操作

以下操作被 `.claude/settings.json` 的 deny 规则直接阻止：

- `rm -rf` 类批量删除
- `git reset --hard`
- `git push --force`

如确需，改到 feature 分支上本地操作，不允许在 main 上进行。
```

- [ ] **Step 2：Commit**

```bash
git add context/team/git-workflow.md
git commit -m "docs(team): 添加 Git 工作流规范"
```

---

## Task 11：`context/team/tool-chain.md`

**Files:**
- Create: `context/team/tool-chain.md`

- [ ] **Step 1：创建文件**

```markdown
# 团队工具链规范

由于团队是多栈环境，本文件只记录**通用工具**约定。语言/框架专属约定请在 `context/project/<项目>/` 下维护。

## 通用

- 所有仓库提供 `README.md`、`.gitignore`、`CLAUDE.md`
- `.mcp.json` 列出该项目使用的 MCP Server
- `requirements/` 目录用于需求管理（见 `requirements/INDEX.md`）

## Git

见 [`git-workflow.md`](git-workflow.md)

## Claude Code

- 入口文件：`CLAUDE.md`（项目级）
- 配置：`.claude/settings.json`（团队共享）+ `.claude/settings.local.json`（个人覆盖，不入库）
- MCP：`.mcp.json` 默认启用 `context7`、`chrome-devtools`
- 自定义能力：`.claude/commands/`（意图入口）+ `.claude/skills/`（知识包）+ `.claude/agents/`（独立同事）

## 语言栈

当前空。新项目第一个需求开发时，由 Agent 沉淀到 `context/project/<项目名>/lang-<语言>.md`。

## 文档与图表

- Markdown（Obsidian / GitHub Flavor）
- 图表：Mermaid 优先（嵌入 Markdown）；复杂图用 excalidraw/draw.io 导出 SVG
```

- [ ] **Step 2：Commit**

```bash
git add context/team/tool-chain.md
git commit -m "docs(team): 添加通用工具链规范"
```

---

## Task 12：`context/team/ai-collaboration.md`

**Files:**
- Create: `context/team/ai-collaboration.md`

**Reference:** Spec §5.1（刨根问底 + 渐进式输出）+ §8.3（认知转变）

- [ ] **Step 1：创建文件**

```markdown
# 和 AI 协作的基本准则

本文档是所有人和所有 Agent 共享的协作规范。Agent 会自动引用；人类第一次读一次即可。

## 核心认知转变

你的核心工作从"写代码"变成"引导上下文 + 验证结果"。

```
代码输出质量 = AI 能力 × 上下文质量
```

瓶颈在**上下文**，不在 AI。规范已预制，无需告诉 AI "怎么做"，只需告诉它"做什么"和"业务背景"。

## 两条硬规则（Agent 必须遵守）

### 规则一：刨根问底（Source-or-Mark）

Agent 写入 `requirements/<id>/artifacts/*.md` 的每条关键信息必须属于三种状态之一：

| 状态 | 处理 |
|---|---|
| 有项目内引用 | 直接引用，格式 `路径:行号` |
| 无引用但可确认 | 标记 `[待用户确认]` 并列入待澄清清单 |
| 完全无法确认 | 标记 `[待补充]`，给出假设（内容/依据/风险/验证时机） |

**不允许第四种状态**："没来源但看起来合理就写了"。这是幻觉的来源。

### 规则二：渐进式输出（Progressive Disclosure）

文档类输出必须分步：

1. 先输出 **3-5 条关键确认点**（摘要 / 决策点 / 待确认项）
2. 等用户确认方向后再输出正式文档

禁止一次性输出完整长文档。

## 人的最小行动路径（5 步）

1. **说出场景** — "我要开发一个新需求" / "继续之前的需求" / "帮我审查一下这段代码"
2. **提供业务上下文** — Jira/TAPD 链接、关键业务规则、关注的代码位置
3. **让 AI 按规范推进** — 它会自动阶段检查、更新状态
4. **验证与纠偏** — 检查输出，有问题就具体反馈（不要"感觉不对"，要"在 X 文件 Y 行，期望 Z 但看到 W"）
5. **确认沉淀** — `notes.md` 和 `context/` 是否按需更新了

## 验证清单（每次重要输出后）

- [ ] 能编译（若涉及代码）
- [ ] 测试通过
- [ ] 核心逻辑符合预期
- [ ] 边界条件处理了
- [ ] 无安全隐患
- [ ] 日志足够定位问题且不泄露敏感

## 纠偏示范

❌ 不好：「这段代码有问题，改一下」
✅ 好：「在 `service/UserService.java:42`，当 userId 为 null 时会 NPE。期望返回空列表。要求最小改动修复，不要重构其他逻辑。」

## 成长路径参考

| 阶段 | 时间 | 标志 |
|---|---|---|
| 入门 | 1-2 周 | 能用 AI 完成简单需求，流程顺畅 |
| 熟练 | 1-2 月 | 复杂需求也能高效完成，project 级上下文丰富 |
| 精通 | 3+ 月 | 能优化规范、设计可复用 Skill、帮助团队成员上手 |
```

- [ ] **Step 2：Commit**

```bash
git add context/team/ai-collaboration.md
git commit -m "docs(team): 添加 AI 协作基本准则"
```

---

## Task 13：`context/team/feedback-log.yaml`

**Files:**
- Create: `context/team/feedback-log.yaml`

**Reference:** Spec §7.6（降级实现）+ 决策 mm（YAML 结构化）

- [ ] **Step 1：创建文件**

```yaml
# /agentic:feedback 写入位置。结构化条目。
# 每条 feedback 的 schema:
#   - id:         自增（yyyymmdd-seq）
#     at:         ISO 8601 时间戳
#     user:       git config user.email 或 CLAUDE_USER
#     type:       praise | complaint | suggestion | bug
#     target:     agent | skill | command | hook | docs | other
#     target_ref: 具体目标的 ID（如 skill:managing-requirement-lifecycle）
#     body:       正文（简体中文）
#     resolved:   true | false | pending
#     resolution: 解决情况描述（resolved 后填）

entries: []
```

- [ ] **Step 2：验证 YAML 合法**

```bash
python3 -c "import yaml; yaml.safe_load(open('context/team/feedback-log.yaml'))" && echo OK
```

- [ ] **Step 3：Commit**

```bash
git add context/team/feedback-log.yaml
git commit -m "feat(feedback): 初始化结构化反馈日志"
```

---

## Task 14：`engineering-spec/design-guidance/` 三份设计指导

**Files:**
- Create: `context/team/engineering-spec/design-guidance/four-layer-hierarchy.md`
- Create: `context/team/engineering-spec/design-guidance/context-engineering.md`
- Create: `context/team/engineering-spec/design-guidance/compounding.md`

**Reference:** Spec §1.1 / §4.3（四层架构）/ §6.5

- [ ] **Step 1：创建 `four-layer-hierarchy.md`**

```markdown
# 四层设计层级与自主权边界

本体系的变更分为四层，不同层级对应不同的变更风险和决策权限。

## 四层

```
1. 设计指导（Why）        ← 核心原则，稳定不变      ❌ Agent 不可自主修改
    │
    ├── 2. 功能预期（What）     ← 系统能做什么        ⚠️ Agent 可提议，需人工确认
    │
    └── 3. 场景规范（约束）     ← Agent 必须遵守什么  ✅ Agent 可自主完成，建议评审
            │
            └── 4. 工具（产物）   ← 能力的封装        ✅ Agent 可自主完成
```

## 每层的说明

### 1. 设计指导（Why）

本目录下的三份文件：`four-layer-hierarchy.md` / `context-engineering.md` / `compounding.md`。
一旦改错会影响整个体系方向，必须人来审慎决策。PR 必须全团队评审。

### 2. 功能预期（What）

决定"系统能做什么"。典型：8 阶段生命周期定义、门禁规则、工具清单。位置：`specs/` 下的设计文档。

Agent 可以在需求开发中发现某能力缺失并**提议**改动，但实际修改必须人类确认后才进行。

### 3. 场景规范（约束）

Agent 在具体任务中必须遵守的行为。典型：`skill-spec.md` 里的硬约束（< 2k token）、`command-spec.md` 里的 < 100 行。

Agent 可以自主改动（比如发现 checker 的命名模式不统一，提 PR 统一），建议有人类 review。

### 4. 工具（产物）

具体的 Command / Skill / Agent 定义文件，位于 `.claude/`。

Agent 可以自主完成——这是最高频的修改层，建议但不强制 PR review。

## 为什么分层

这四层的分层不是权限管理，是**变更风险的自然梯度**。设计指导改一条影响整个体系，工具改一条只影响单个能力。自主权边界跟着风险走。
```

- [ ] **Step 2：创建 `context-engineering.md`**

```markdown
# 上下文工程原则

整个体系是围绕一个简单公式设计的：

```
AI 输出质量 = AI 能力 × 上下文质量
```

AI 能力由模型决定，我们能控制的是**上下文质量**。

## 四条核心原则

### 1. 文档即记忆

人和 AI 读**同一份** Markdown。不维护双轨（给人的 Wiki + 给 AI 的向量库）。原因：

- 避免版本漂移（改了一份忘另一份）
- 高频使用对抗腐化：文档过时 → AI 出错 → 立刻被发现并修正
- 团队协作的知识对齐零成本：`git clone` 即获得完整记忆

### 2. 位置即语义

文件放在哪个目录，Agent 就知道它是什么：

- `context/team/` — 团队通用
- `context/project/<X>/` — 项目 X 专属
- `context/team/engineering-spec/` — 体系自身
- `requirements/<id>/artifacts/` — 单个需求的全周期产出

不使用元数据标签、不使用外部索引数据库。路径本身承载分类信息。

### 3. 渐进式披露（Agentic Search）

入口轻量，按需深入。

- `CLAUDE.md` < 200 行（根索引）
- `SKILL.md` < 2k token（技能入口）
- 详细知识放 `reference/`，真需要才读

目的：**主对话上下文是稀缺资源**，任何预加载的信息都在消耗认知带宽。

### 4. 工具封装知识，不封装流程

Skill 给 Agent 的是"做什么 + 注意什么"，不是"第一步…第二步…"。

- ❌ "1. 读 requirement.md → 2. 找 services 字段 → 3. 对每个 service 运行 git diff"
- ✅ "定义 ReviewScope：它包含哪些字段、每个字段的语义、禁止遗漏的约束"

把 Agent 当有判断力的同事，不是 shell 脚本。

## 禁止盲目搜索

`universal-context-collector` 这个 Agent 的硬规则：**先读 INDEX.md，决定读什么，再读**。不允许 glob 一口气拉进来所有 `context/**/*.md`。

## 检索优先级

```
1. context/project/<当前项目>/*
2. context/project/<当前项目>/INDEX.md（先索引后深入）
3. context/team/engineering-spec/（体系规范）
4. context/team/*（团队通用）
5. 历史 requirements/*/artifacts/（类似需求参考）
6. 外部 WebSearch / WebFetch（最后手段，设计阶段禁用）
```
```

- [ ] **Step 3：创建 `compounding.md`**

```markdown
# 复利工程原则

Vibe Coding 是"用一次算一次"，Agentic Engineering 是"每一次使用都在积累"。

## 核心判断

每次 AI 犯错都是知识原料。不记下来，下次还得付学费；记下来，下一次 Agent 自动避开。

## 沉淀路径

```
需求开发中产生新知识（AI 犯错、用户纠偏、新业务概念）
    ↓ notes.md 随手记（Agent 自动 + /note 命令）
    ↓
需求验收后（/knowledge:extract-experience）
    ↓
context/project/<X>/ 或 context/team/experience/ 长期记忆
    ↓
下一个需求的 universal-context-collector 自动检索到
```

## 什么值得沉淀（必要条件）

- 跨需求/跨项目重复出现
- AI 反复犯同类错误
- 团队内部口口相传的经验

**至少满足一条**才沉淀。

## 什么不值得沉淀（反向过滤）

- 偶发问题（只踩过一次）
- 简单自然对话能传递的
- 只对当前需求有意义

偶发问题写 `notes.md`，不升级到 `context/`。

## 粒度规则

"粒度对了"的判断：**下次需求是否能用到**。
- 太粗：`"Apollo 有特殊格式"` → AI 还是会写错
- 太细：`"某个字段某种极端场景下要 xxx"` → 下次需求用不到，反而占上下文
- 合适：`"Apollo 的 When 条件用 GRL DSL：前缀必须 FactModule.，参数单引号，日期冒号分隔"`

## 单仓库 + git 的天然复利

`context/` 是团队公共资产。团队里任何人 clone 仓库后都自动站在所有人积累的台阶上。PR 流程让新沉淀经评审后合入，腐化时也能 PR 清理。

**知识的流转方式从"藏在个人脑子里的隐性经验"变成"版本化管理的团队公共资产"——这才是工程革命的实质。**
```

- [ ] **Step 4：Commit**

```bash
git add context/team/engineering-spec/design-guidance/
git commit -m "docs(spec): 添加三份设计指导（四层架构 / 上下文工程 / 复利工程）"
```

---

## Task 15：`engineering-spec/tool-design-spec/` 三份工具规范

**Files:**
- Create: `context/team/engineering-spec/tool-design-spec/command-spec.md`
- Create: `context/team/engineering-spec/tool-design-spec/skill-spec.md`
- Create: `context/team/engineering-spec/tool-design-spec/subagent-spec.md`

**Reference:** Spec §4.2 / §4.4

- [ ] **Step 1：创建 `command-spec.md`**

```markdown
# Command 设计规范

**Command 是意图快捷入口，不是流程执行器。**

## 硬约束

| 约束 | 数值 | 理由 |
|---|---|---|
| 单文件行数 | < 100 行 | 避免把领域逻辑塞进 Command |
| 职责 | 仅预检 + 委托给 Skill | 逻辑集中在 Skill，Command 改了不动 Skill |
| 同领域多 Command | 委托**同一个**伞形 Skill | `/requirement:new` / `:continue` / `:next` / ... 全部委托 `managing-requirement-lifecycle` |

## 为什么这样分

同领域的多个命令（如 7 个 `/requirement:*`）背后共享**同一套领域知识**。如果每个 Command 都把逻辑重复写一遍，改一条规则要同时改 7 个文件。维护成本从 O(n) 降到 O(1)。

## 文件结构

```
.claude/commands/
├── <name>.md                    根命令
└── <namespace>/
    └── <name>.md                命名空间命令 → /<namespace>:<name>
```

## Command 文件骨架

```markdown
---
description: 一句话说这个命令做什么
argument-hint: <参数提示（可选）>
---

## 用途

一段话描述触发时机和使用场景。

## 预检

1. [前置条件 1]
2. [前置条件 2]

预检不通过直接返回错误，不进入 Skill 流程。

## 委托

使用 Skill `<skill-name>` 的 `<动作>` 流程。
```

## 正面示例

见 `.claude/commands/requirement/new.md`（Phase 2 创建）。

## 反面：Command 不应该做的事

- 直接写业务逻辑（应该在 Skill 里）
- 直接调用多个 Agent 编排（应该在 Skill 里）
- 定义数据结构、模板、规则（应该在 Skill 的 reference/ 里）
```

- [ ] **Step 2：创建 `skill-spec.md`**

```markdown
# Skill 设计规范

**Skill 是专业知识包，不是脚本执行器。**

## 硬约束

| 约束 | 数值 | 理由 |
|---|---|---|
| `SKILL.md` 大小 | < 2k token（约 500 汉字 + 代码） | Skill 进主对话上下文，必须轻量 |
| 内容类型 | 指令（灵活指导）/ 代码（确定性操作）/ 资源（模板） | 三种各司其职 |
| 资源层级 | "一跳可达" | 从 SKILL.md 直接链接到 reference/ 文件，不允许深层嵌套 |
| 默认假设 | "Claude 已经很聪明" | 只补充 Claude 没有的信息，不重复常识 |

## 渐进式披露架构

```
.claude/skills/<skill-name>/
├── SKILL.md          ← 入口 < 2k token。进入主对话上下文
├── reference/        ← 详细知识，Agent 按需读取
│   ├── rule-xxx.md
│   └── field-spec.md
├── templates/        ← 模板文件，复制-填值使用
│   └── xxx.md
└── scripts/          ← 确定性脚本
    └── validate.sh
```

## `SKILL.md` 骨架

```markdown
---
name: <skill-name>
description: 一句话说这个 Skill 做什么 + 在什么场景被触发
---

## 什么时候用这个 Skill

触发条件。和其他 Skill 的边界。

## 核心流程

三步以内概括。细节引用 reference/。

## 硬约束

3-5 条必须遵守的规则，用 ❌/✅ 对比显式给出。

## 参考资源

- [`reference/xxx.md`](reference/xxx.md) — 详细 X
- [`templates/yyy.md`](templates/yyy.md) — 模板 Y
```

## 三种内容类型

### 指令（Prose Instructions）

写在 SKILL.md 和 reference/*.md 里。告诉 Agent "做什么 + 注意什么"，不规定具体步骤。

### 代码（Deterministic Scripts）

写在 scripts/ 下。用于确定性操作（JSON 校验、文件格式转换、git 命令组合）。当步骤明确且可自动化时用脚本，比让 AI 推理可靠。

### 资源（Templates & References）

- templates/ — 让 AI 复制并填值（如 `requirement.md` 的骨架）
- reference/ — 让 AI 查（如字段类型表、枚举值表）

## 反面：Skill 不应该做的事

- 封装流程（"先做 A 再做 B 再做 C"）—— 应该封装知识
- 假设 AI 不懂常识（"如何写 Markdown" 之类）
- 跨 Skill 调用（Skill 之间通过主 Agent 协调）
```

- [ ] **Step 3：创建 `subagent-spec.md`**

```markdown
# Subagent（Agent）设计规范

**Agent 是独立上下文中的专业同事，不是被动的脚本执行器。**

## 硬约束

| 约束 | 数值 | 理由 |
|---|---|---|
| 返回内容 | < 2k token | 保护主对话上下文不被淹没 |
| 嵌套调用 | **禁止**（Agent 之间不相互调用） | 编排由主 Agent / Skill 完成 |
| 上下文 | 独立（不继承主对话） | 避免信息污染；只看 SKILL.md 里传的输入 |

## 按任务类型分五类

| 类别 | 模型档位 | 示例 |
|---|---|---|
| 初始化类（创建资源） | 轻量（sonnet） | `requirement-bootstrapper` |
| 准备类（收集信息） | 轻量 | `universal-context-collector` |
| 评审类（评估质量） | 高能力（opus） | `requirement-quality-reviewer` / `code-quality-reviewer` |
| 执行类（生成代码） | 中等（sonnet） | 7 个代码审查 checker |
| 维护类（更新文档） | 轻量 | `documentation-batch-updater` |

不同类别推荐不同模型——让一次完整操作既全面又经济。

## 文件位置

```
.claude/agents/<agent-name>.md
```

单文件，frontmatter 里声明 model 和 tools。

## Agent 文件骨架

```markdown
---
name: <agent-name>
description: 一句话。第三方能准确理解什么时候该调用这个 Agent。
model: opus | sonnet | haiku
tools: Read, Grep, Bash, ...
---

## 你的职责

简述。

## 输入

你会收到什么信息。

## 输出契约

必须以什么格式返回。返回 < 2k token。

## 行为准则

- 禁止嵌套调用其他 Agent
- 禁止污染主对话（直接写文件前要明确原因）
- 评审类 Agent 不读源码本身，只读结构化输入（避免重复）
```

## 反面：Agent 不应该做的事

- 返回超长原始数据（切记 < 2k token）
- 调用其他 Agent（让主 Agent 编排）
- 期待"继承"主对话的状态（写清楚你需要什么输入）
- 修改 `.claude/` 或 `context/team/engineering-spec/`（这属于设计层）
```

- [ ] **Step 4：Commit**

```bash
git add context/team/engineering-spec/tool-design-spec/
git commit -m "docs(spec): 添加 Command / Skill / Subagent 三份工具设计规范"
```

---

## Task 16：`engineering-spec/iteration-sop.md`

**Files:**
- Create: `context/team/engineering-spec/iteration-sop.md`

**Reference:** Spec §4.3

- [ ] **Step 1：创建文件**

```markdown
# 项目迭代 SOP

本 SOP 是"体系怎么改"的压缩算法。所有对 `.claude/`、`context/team/engineering-spec/`、`CLAUDE.md` 的改动都应走这棵决策树。

## 决策点 1：发生了什么？

| 触发场景 | 关键操作 |
|---|---|
| 用户需要新能力 | 定层级（见决策点 2），加到对应层 |
| Agent 行为出错 | 定位问题层级（设计 / 功能预期 / 场景规范 / 工具），改最窄的层 |
| 业务场景变化 | 更新 `context/project/<X>/`，可能升级到 `context/team/experience/` |
| 用户反馈建议 | 读 `feedback-log.yaml`，分类处理 |
| 新人上手困难 | 更新 `onboarding/` 或 `learning-path/` |
| 模型 / 平台能力升级 | 可能触发设计层变更，需全团队评审 |

## 决策点 2：改哪一层？

见 `design-guidance/four-layer-hierarchy.md`。四层自上而下：

1. 设计指导（不可 Agent 自主） — 体系根原则
2. 功能预期（Agent 提议，人确认） — 8 阶段生命周期、工具清单等
3. 场景规范（Agent 可自主，建议评审） — 具体约束
4. 工具（Agent 可自主） — .claude/ 下的具体定义

## 决策点 3：是否应该工具化？

用以下 6 条判断：

| # | 应工具化的特征 | 例 |
|---|---|---|
| 1 | 强制约束（不可跳过） | 追溯链检查 |
| 2 | 易错环节（Agent 经常遗漏） | 需求"来源标注" |
| 3 | 高频重复（> 每周） | 代码审查 |
| 4 | 跨多个需求/项目 | 风险评估 |
| 5 | 需要独立上下文（输出大） | 综合代码审查 |
| 6 | 需要特定模型档位 | 评审类用 opus |

**反面：不应工具化的**

- 一次性约束
- 高度灵活的任务（每次情况不同）
- 需要人类判断的决策

写在规范里就够了，不做成 Skill/Agent。

## 决策点 4：迭代检查清单

完成任何变更后，对照：

- [ ] 功能预期是否更新？（specs/ 或 CLAUDE.md）
- [ ] 设计追溯表的正向/反向索引是否同步？
- [ ] 场景规范是否需要补充？（engineering-spec/）
- [ ] 工具是否需要升级？（.claude/）
- [ ] 相关 INDEX.md 是否更新？
- [ ] 如涉及场景变更，场景全景是否更新？

**这份清单保证变更是"系统性"的，而非"打补丁"。**

## 规范瘦身（定期）

每条规则都回答一次："它被违反的频率有多高？"

- 高频违反 → 保留
- 极少触发 → 极端 case → 删除或合并

规则越多，Agent 越容易"走神"。宁可少一条规则，不要多一条事无巨细的约束。

## 反模式警告

不要让体系变成"又一个要维护的系统"。如果团队开始抱怨"维护 context/ 比写代码还累"，说明沉淀的颗粒度太细。

沉淀的三条必要条件（见 `design-guidance/compounding.md`）：

- 跨需求/跨项目重复出现
- AI 反复犯同类错误
- 跨会话/跨人需要保留的状态

**没有一条命中就不沉淀**。
```

- [ ] **Step 2：Commit**

```bash
git add context/team/engineering-spec/iteration-sop.md
git commit -m "docs(spec): 添加项目迭代 SOP"
```

---

## Task 17：`onboarding/agentic-engineer-guide.md`

**Files:**
- Create: `context/team/onboarding/agentic-engineer-guide.md`

**Reference:** Spec §8.3

- [ ] **Step 1：创建文件**

```markdown
# Agentic 工程师入门指南

30 分钟读完；一周内跑通第一个需求。

## 一个认知转变

你的核心工作从"写代码"变成"引导上下文 + 验证结果"。

```
代码输出质量 = AI 能力 × 上下文质量
```

规范已预制在本仓库。你**不需要**告诉 AI "怎么做"——只需要告诉它"做什么"和"业务背景"。

## 一条最小行动路径（5 步）

1. **说出场景** — "我要开发一个新需求" / "继续之前的需求" / "帮我审查一下这段代码"
2. **提供业务上下文** — Jira/TAPD 链接、业务规则、关注的代码位置
3. **让 AI 按规范推进** — 它会自动阶段检查、更新状态
4. **验证与纠偏** — 看输出，有问题就**具体**反馈（不是"感觉不对"，要"在 X 文件 Y 行，期望 Z 但看到 W"）
5. **确认沉淀** — `notes.md` 和 `context/` 按需更新了吗

## 第一周目标

用这个流程完成 **1 个小需求**（< 1 人天）。不追求用上所有功能。

## 第一次跑起来（Phase 1 完成后可执行）

### 环境（5 分钟）

1. 安装 Claude Code（官方文档）
2. 克隆本仓库
3. 打开终端，进入仓库目录，运行 `claude`

### 验证

- 终端底部应有状态行显示 `[no-requirement] <branch>`
- 输入 `/agentic:help` 应看到帮助（Phase 2 后）

### 第一条练习

**Phase 1 阶段**：只能读文档。跟着 `learning-path/01-environment.md` 做。
**Phase 2 阶段后**：运行 `/requirement:new` 开始你的第一个小需求。

## 之后去哪

按顺序完成：

- [`learning-path/01-environment.md`](learning-path/01-environment.md) — 环境准备
- [`learning-path/02-first-conversation.md`](learning-path/02-first-conversation.md) — 和 AI 对话的基本法
- [`learning-path/03-command-skill-agent.md`](learning-path/03-command-skill-agent.md) — 三级工具区别
- [`learning-path/04-first-requirement.md`](learning-path/04-first-requirement.md) — 完整跑通 8 阶段（Phase 2/3 后）
- [`learning-path/05-code-review.md`](learning-path/05-code-review.md) — 代码审查（Phase 2/3 后）
- [`learning-path/06-knowledge-sinking.md`](learning-path/06-knowledge-sinking.md) — 知识沉淀（Phase 2/3 后）

前 6 阶段必修。走完即具备独立使用能力。

## 哪里遇到问题

1. 先运行 `/agentic:help` 看 FAQ
2. 读 `ai-collaboration.md`
3. 问有经验的同事
4. `/agentic:feedback` 把问题提给团队（会写入 `context/team/feedback-log.yaml`）
```

- [ ] **Step 2：Commit**

```bash
git add context/team/onboarding/agentic-engineer-guide.md
git commit -m "docs(onboarding): 添加 Agentic 工程师入门指南"
```

---

## Task 18：`onboarding/learning-path/` 8 个文件

**Files:** 8 个 `.md` 文件

**Reference:** Spec §8.2

每个文件逐字写入下方内容即可。前 6 阶段（01-06）是必修，后 2 阶段（07-08）是选修。后 5 个文件的"可验证动作"依赖 Phase 2/3 的能力（Command/Skill/Agent），Phase 1 完成后这些文件只是放好了，不能真的练习。

### 18.1 `01-environment.md`

- [ ] **Step 1：创建文件**

```markdown
# Stage 1 · 环境准备

**完成时间**：15-30 分钟
**前置**：无
**可验证动作**：`claude /agentic:help` 在本仓库能正常输出

## 目标

装好 Claude Code，跑通一次"读文件→改文件→运行命令"的闭环。

## 步骤

1. 装 Claude Code CLI（参考官方文档）
2. 配置 `ANTHROPIC_API_KEY`（或通过登录流程）
3. 克隆本仓库：`git clone <repo-url> && cd agenticMetaEngineering`
4. 运行 `claude` 进入会话
5. 输入：`读一下 README.md 告诉我这个仓库是做什么的`
6. 输入：`状态行显示了什么？`

## MCP 配置（可选）

本仓库默认启用 `context7`（库文档）、`chrome-devtools`（浏览器自动化）。其他 MCP（Jira / 飞书 / 企业 Wiki）未配置，需要时按以下步骤：

1. 获取对应 MCP Server（官方或团队内部分发）
2. 编辑 `.mcp.json`（**团队共享配置，改动要 PR**）或 `.claude/settings.local.json`（个人覆盖）
3. 重启 Claude Code

## 完成标志

- [ ] `claude` 能启动且状态行显示
- [ ] 能让 AI 读文件
- [ ] 知道 `.mcp.json` 在哪
```

### 18.2 `02-first-conversation.md`

- [ ] **Step 2：创建文件**

```markdown
# Stage 2 · 和 AI 对话的基本法

**完成时间**：30 分钟
**前置**：Stage 1 完成
**可验证动作**：让 AI 读懂本仓库的 README 并用一段话总结

## 两条核心规则

详见 `context/team/ai-collaboration.md`：

1. **刨根问底**：AI 输出的每条关键信息必须有引用、或标记"待确认"
2. **渐进式输出**：先输出 3-5 条关键点，用户确认后再出完整文档

## 练习

### 练习 1：场景引导

不要说："帮我看看这代码"
要说："我要理解 `.claude/statusline.sh` 里的阶段到中文的映射是怎么做的。读一遍代码后用一段话描述"

### 练习 2：上下文提供

不要说："修 bug"
要说："在 `.claude/hooks/protect-branch.sh`，当 `CLAUDE_HOOK_TOOL_NAME` 未设置时行为不明确。期望：默认放行。请最小改动修复"

### 练习 3：验证与纠偏

让 AI 写一段 10 行以内的 Bash 检查脚本。输出后：

- 能运行吗？
- 边界情况（空输入 / 权限错误）处理了吗？
- 如果有问题，具体指出"在第 X 行，Y 场景下，预期 Z"

## 完成标志

- [ ] 理解"场景引导 + 上下文提供 + 验证纠偏"三段式
- [ ] 能在一次对话里给出具体的纠偏指令
```

### 18.3 `03-command-skill-agent.md`

- [ ] **Step 3：创建文件**

```markdown
# Stage 3 · 三级工具的区别与选型

**完成时间**：30 分钟
**前置**：Stage 2 完成
**可验证动作**：读完本文能回答"什么时候用 Command / Skill / Agent"

## 三级区别

| 类型 | 上下文影响 | 场景 |
|---|---|---|
| Command | 极小（< 100 行进入主对话） | 固定操作的意图快捷入口 |
| Skill | 可控（SKILL.md < 2k token 进入主对话） | 需要领域知识的标准化工作流 |
| Agent | 隔离（独立上下文，返回 < 2k token） | 产生大量输出或独立探索的任务 |

## 决策树

```
任务会产生大量输出或需要多轮独立探索？
├── 是 → Agent
└── 否 → 需要领域知识或多步流程？
         ├── 是 → Skill
         └── 否 → 高频且固定？
                  ├── 是 → Command
                  └── 否 → 不工具化，写在规范里
```

## 伞形模式

同一领域的多个 Command（如 7 个 `/requirement:*`）委托**同一个**伞形 Skill（`managing-requirement-lifecycle`）。这是为了：

- 领域知识集中在一处
- 改一条规则只改一个 Skill
- Command 只做薄层（< 100 行）

## 阅读作业

- `context/team/engineering-spec/tool-design-spec/command-spec.md`
- `context/team/engineering-spec/tool-design-spec/skill-spec.md`
- `context/team/engineering-spec/tool-design-spec/subagent-spec.md`

## 完成标志

- [ ] 能用决策树给任一虚构场景选型
- [ ] 理解"伞形模式"的必要性
```

### 18.4 `04-first-requirement.md`

- [ ] **Step 4：创建文件**

```markdown
# Stage 4 · 跑完一个完整的 8 阶段小需求

**完成时间**：1-2 人天
**前置**：Phase 2/3 骨架完成（即 Command / Skill / Agent 已建）
**可验证动作**：成功合入 1 个 feature/req-xxx 分支到 main

## 练习需求（任选其一）

1. 给本仓库加一个 `/status-summary` 命令，输出仓库文件数/行数统计
2. 给 `.claude/statusline.sh` 加一个显示当前 Token 用量的段（如果 Claude Code 环境变量暴露了）
3. 在 `context/team/` 下加一份"如何挑选 Claude 模型档位"的规范

## 步骤

1. 运行 `/requirement:new`，填需求元信息
2. 跟随 8 阶段推进：
   - 阶段 1 初始化 → 自动
   - 阶段 2 需求定义 → 用 `requirement-doc-writer` 写需求文档
   - 阶段 3 技术预研 → 评估可行性
   - 阶段 4 概要设计 → 模块划分
   - 阶段 5 详细设计 → 接口签名
   - 阶段 6 任务规划 → 拆分功能点
   - 阶段 7 开发实施 → 编码 + `/code-review`
   - 阶段 8 测试验收 → 写测试 + 追溯链校验
3. 全部通过后合入

## 关键检查点

- [ ] 每次阶段切换都有门禁输出
- [ ] 每个阶段的 `artifacts/*.md` 都有"来源标注"
- [ ] `process.txt` 记录了全部关键动作
- [ ] 最终代码审查报告为 `approved`

## 完成标志

成功合入一个 feature 分支。
```

### 18.5 `05-code-review.md`

- [ ] **Step 5：创建文件**

```markdown
# Stage 5 · 用 /code-review 做增量审查

**完成时间**：1-2 小时
**前置**：Phase 2/3 完成
**可验证动作**：用 `/code-review` 拦截到至少 1 个真实问题

## 两种使用模式

### 独立模式（任何项目即可）

在任意 git 仓库里运行 `/code-review`。它会：

1. 取当前分支 vs master 的 diff 作为 ReviewScope
2. 并行跑 7 个 checker + 1 综合 reviewer
3. 生成审查报告

### 嵌入模式（Agentic Engineering 工作流）

阶段 7 功能点完成时，`feature-lifecycle-manager` Skill 自动调用 `/code-review`，范围限定到该功能点。

## 7 个 checker 维度

- design-consistency — 设计一致性
- security — 注入/鉴权/敏感日志
- concurrency — 并发/幂等
- complexity — 方法长度/圈复杂度
- error-handling — 异常/错误码
- auxiliary-spec — 命名/注释/格式
- performance — 热点 SQL/N+1

## 练习

1. 在本仓库切一个 feature 分支，故意引入一个违规（如 `rm -rf $HOME/..` 类 Bash 命令）
2. 提交
3. 运行 `/code-review`
4. 确认 `security-checker` 报出这个问题

## 读审查报告

报告存在 `requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`，结论分：

- `approved` — 可合入
- `needs_revision` — 需修改
- `rejected` — 驳回

## 完成标志

- [ ] 成功拦截至少 1 个真实问题
- [ ] 理解双模使用（独立 vs 嵌入）
```

### 18.6 `06-knowledge-sinking.md`

- [ ] **Step 6：创建文件**

```markdown
# Stage 6 · 知识沉淀与复利

**完成时间**：30 分钟 + 持续积累
**前置**：Stage 4 完成（跑通过一个需求）
**可验证动作**：向 `context/project/` 提交 1 份经验文档 PR

## 复利路径

```
需求中产生新知识
    ↓ /note 或 AI 自动追加到 notes.md
    ↓
需求验收后（/knowledge:extract-experience）
    ↓
context/project/<X>/ 或 context/team/experience/
    ↓
下一个需求 universal-context-collector 自动检索到
```

## 5 个 /knowledge:* 命令

- `/knowledge:extract-experience` — 从 notes.md 提取经验
- `/knowledge:generate-sop` — 生成标准操作流程
- `/knowledge:generate-checklist` — 生成检查清单
- `/knowledge:optimize-doc` — 优化已有文档结构
- `/knowledge:organize-index` — 整理 context/ 索引

## 什么值得沉淀

见 `context/team/engineering-spec/design-guidance/compounding.md`。必要条件：

- 跨需求/跨项目重复出现
- AI 反复犯同类错误
- 跨会话/跨人需要保留的状态

**至少满足一条才沉淀。**

## 练习

1. 在你刚跑完的需求的 `notes.md` 里找一条"踩过的坑"
2. 运行 `/knowledge:extract-experience`
3. 它会提议一份经验文档，让你确认落到 `context/project/<项目>/experience/` 还是 `context/team/experience/`
4. 确认后提 PR

## 完成标志

- [ ] 理解沉淀的三个必要条件
- [ ] 成功提交 1 份经验文档 PR
```

### 18.7 `07-custom-command.md`（选修）

- [ ] **Step 7：创建文件**

```markdown
# Stage 7 · 写一个自定义 Command（选修）

**完成时间**：30 分钟
**前置**：Stage 3 完成
**可验证动作**：提交 1 个 `.claude/commands/<你的>.md`

## Command 硬约束回顾

见 `context/team/engineering-spec/tool-design-spec/command-spec.md`。关键：

- < 100 行
- 只做**预检 + 委托给 Skill**，不做业务逻辑

## 练习

写一个 `/project:status` 命令：

1. 预检当前是 git 仓库
2. 委托给 Skill（可以是新建的 `managing-project-status`，也可以是已有 Skill）
3. 输出：最近 10 个 commit、modified 文件数、未跟踪文件数

## 模板

```markdown
---
description: 展示项目状态摘要
---

## 用途

用户想快速了解项目当前状态时调用。

## 预检

1. 确认在 git 仓库中：`git rev-parse` 不出错

## 委托

使用 Skill `managing-project-status` 的"摘要"流程。
```

## 完成标志

- [ ] 命令 < 100 行
- [ ] 跑 `/project:status` 能输出预期结果
- [ ] 提交 PR
```

### 18.8 `08-custom-skill.md`（选修）

- [ ] **Step 8：创建文件**

```markdown
# Stage 8 · 写一个最小 Skill（选修）

**完成时间**：1-2 小时
**前置**：Stage 7 完成
**可验证动作**：提交 1 个 `.claude/skills/<你的>/SKILL.md`

## Skill 硬约束回顾

- SKILL.md < 2k token
- 三种内容：指令 / 代码 / 资源
- 渐进式披露：入口轻量，详细知识放 reference/

## 练习

延续 Stage 7，创建 `managing-project-status` Skill：

```
.claude/skills/managing-project-status/
├── SKILL.md              # 入口
├── reference/
│   └── status-fields.md  # 每个字段的语义
└── scripts/
    └── collect.sh        # 收集 git 数据的脚本
```

## SKILL.md 模板

```markdown
---
name: managing-project-status
description: 收集并汇总项目当前状态（commit 数、变更文件、未跟踪文件等）。被 /project:status 调用。
---

## 什么时候用

用户触发 /project:status 或口头说"项目现在什么状态"时。

## 核心流程

1. 运行 `scripts/collect.sh` 获取原始数据（JSON 格式）
2. 按 reference/status-fields.md 定义的格式化方式渲染输出
3. 返回简洁 Markdown 摘要

## 硬约束

- ❌ 禁止直接调用 git 命令超过 3 次
- ❌ 禁止把原始 git log 全部塞进输出
- ✅ 只返回最近 10 条 commit + 统计数字

## 参考

- [`reference/status-fields.md`](reference/status-fields.md)
- [`scripts/collect.sh`](scripts/collect.sh)
```

## 完成标志

- [ ] SKILL.md < 2k token
- [ ] reference/ 和 scripts/ 各有至少 1 个文件
- [ ] 配合 Stage 7 的 Command 能端到端跑通
- [ ] 提交 PR
```

- [ ] **Step 9：验证 8 个文件全部存在**

```bash
for i in 01-environment 02-first-conversation 03-command-skill-agent \
         04-first-requirement 05-code-review 06-knowledge-sinking \
         07-custom-command 08-custom-skill; do
    f=context/team/onboarding/learning-path/${i}.md
    [ -s "$f" ] && echo "✓ $f" || echo "✗ $f"
done
```

- [ ] **Step 10：Commit**

```bash
git add context/team/onboarding/learning-path/
git commit -m "docs(onboarding): 添加 8 阶段学习路径（前 6 必修 + 后 2 选修）"
```

---

## Task 19：`rollout/` 两份团队落地文档

**Files:**
- Create: `context/team/rollout/four-phase-strategy.md`
- Create: `context/team/rollout/embedded-push-playbook.md`

**Reference:** Spec §8.1 / §8.4

- [ ] **Step 1：创建 `four-phase-strategy.md`**

```markdown
# 团队落地四阶段策略

| 阶段 | 核心动作 | 衡量标准 |
|---|---|---|
| 种子期 | 1 人跑通真实业务场景 + 发布 8 阶段学习知识库 | 团队至少 1 人独立走完前 3 阶段 |
| 扩散期 | `git clone` 替代培训，新人 30 分钟上手 | 2-3 人日常使用，踩坑经验自动回流 `context/` |
| 加速期 | 跑通者嵌入其他项目组打第一仗 | 每项目 `context/project/<X>/` 有第一批业务知识 |
| 常态期 | 制度化（PR 共享 / context 维护 / 新人 Onboarding） | PR 流程稳定，新人半天上手 |

## 种子期动作（第 0-4 周）

1. 选一个人（通常是本骨架的搭建者）在自己的真实业务上跑通
2. 公开展示：让同事看到**代码审查自动拦截问题** / **需求推进按流程自动化** / **AI 能直接引用 context/**
3. 同步发布 8 阶段学习路径（`context/team/onboarding/learning-path/`）
4. 结果制造好奇，知识库解决"我怎么开始"

## 扩散期动作（第 1-3 个月）

1. 有好奇者主动尝试
2. 第一个目标：一周内完成 1 个小需求
3. 踩坑经验自动回流：Agent 遇到的问题 → notes.md → context/experience/
4. PR 共享：改进任何 Skill/Command 都可 PR，让每个人的改进惠及所有人

## 加速期动作（第 3-6 个月）

1. 跑通者嵌入其他项目组（参考 `embedded-push-playbook.md`）
2. 帮项目组打穿第一个真实需求
3. 沉淀该项目的 `context/project/<项目>/`
4. 撤出后项目组能独立用 `/requirement:new` 推进

## 常态期动作（第 6 个月后）

详见本文件下方"制度化边界"。

## 制度化不等于强制化

| 该做 | 不该做 |
|---|---|
| `context/` 改动走轻量 PR review | 搞 4 级审批流程 |
| 新人半天内"老成员陪伴"上手 | 开 2 小时培训课 |
| 每个人都能提 PR 改 Skill/Agent | 限制只有少数人能改 |
| 定期清理过时 `context/` 文档 | 让文档积灰 |
| 只沉淀"跨会话/跨人/重复"的知识 | 为偶发问题写永久规则 |

## 反模式警告

如果团队开始抱怨"维护 context/ 比写代码还累"，说明沉淀颗粒度太细。回到"三个必要条件至少满足一条"的判断（见 `engineering-spec/design-guidance/compounding.md`）。
```

- [ ] **Step 2：创建 `embedded-push-playbook.md`**

```markdown
# 嵌入式推进手册

当某个项目负责人认可体系但手头需求紧、推不动第一个场景时，派一个已跑通的人**嵌入**，帮他把第一个场景打穿。

## 核心思路

不催促"抓紧用起来"，而是坐到对方旁边，用 Agentic 流程一起推进他真实的需求。完成后撤出——工具和知识都留下。

参考 Anthropic 与高盛的驻场模式。

## 嵌入者做什么（每次一样）

1. **选一个具体需求**（不是演示），和项目负责人一起用 `/requirement:new` 启动
2. **积累业务上下文**：服务架构、业务规则、技术约束——沉淀到 `context/project/<项目>/`
3. **跑通一个完整闭环**（需求 → 开发 → 代码审查 → 验收）
4. **撤出**：项目团队有了第一份业务知识库和成功案例，后续独立迭代

## 衡量标准（嵌入结束时）

- [ ] `context/project/<项目>/` 至少有 1 份架构概述 + 1 份业务规则 + 1 份技术总结
- [ ] 项目团队至少 1 人独立运行过 `/requirement:continue` 成功
- [ ] 代码审查至少拦截过 1 个真实问题（说明 checker 对这个项目有效）

## 嵌入时长建议

- 小项目（< 5 人）：1-2 周
- 中项目（5-15 人）：2-4 周
- 大项目：需拆子项目分批嵌入

## 常见陷阱

1. **试图代替对方决策**——错。嵌入者是"教练"，不是"代理"。业务决策始终由项目负责人
2. **跑 demo 而不是真需求**——错。demo 是 PPT 级证据，真需求才是流程验证
3. **沉淀太多或太少**——目标是"项目团队能独立迭代"，不是"把我脑子里所有东西都写下来"
```

- [ ] **Step 3：Commit**

```bash
git add context/team/rollout/
git commit -m "docs(rollout): 添加四阶段落地策略与嵌入式推进手册"
```

---

## Task 20：Phase 1 整体验证 + 更新 CLAUDE.md 根索引

**Files:**
- Create: `CLAUDE.md`
- Verify: 全部 Phase 1 文件

**Reference:** Spec §1.1 / §9（未实现清单）

- [ ] **Step 1：创建 `CLAUDE.md`**

必须严格 < 200 行。以 @import 方式挂载子文档，详细知识按需读。

```markdown
# 项目级 Claude Code 指令

本仓库是 Agentic Engineering 工程骨架。克隆即具备骨架能力，按 `context/team/onboarding/agentic-engineer-guide.md` 上手。

## 四条硬原则

1. **文档即记忆**：人和 AI 读同一份 Markdown
2. **位置即语义**：路径承载分类信息，不依赖元数据
3. **渐进式披露**：入口轻量，按需检索。禁止盲目 glob 全部 `context/`
4. **工具封装知识，不封装流程**

详见 @context/team/engineering-spec/design-guidance/context-engineering.md

## 通信与代码规范

- 沟通与说明：简体中文
- 代码注释：简体中文
- 遵循用户全局 CLAUDE.md §0（小步提交 / 不确定就问）

## 和 AI 协作的基本法

@context/team/ai-collaboration.md

## 团队规范

- Git：@context/team/git-workflow.md
- 工具链：@context/team/tool-chain.md

## 体系自身

- 设计指导：`context/team/engineering-spec/design-guidance/`（四层架构 / 上下文工程 / 复利工程）
- 工具规范：`context/team/engineering-spec/tool-design-spec/`（Command / Skill / Subagent）
- 迭代 SOP：`context/team/engineering-spec/iteration-sop.md`
- 完整设计：`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md`

## 记忆检索优先级（universal-context-collector 遵循）

```
1. context/project/<当前项目>/*
2. context/project/<当前项目>/INDEX.md
3. context/team/engineering-spec/
4. context/team/*
5. 历史 requirements/*/artifacts/
6. 外部 WebSearch / WebFetch（设计阶段禁用）
```

## 未实现清单（骨架留白）

以下是文章原版有、本骨架**暂不实现**的能力，避免 Agent 假设它们存在：

### Command 缺口（12 个）

全为文章原版中对应内部业务的命令，本骨架未迁移。

### Skill 缺口（17 个）

- 业务配置生成类（如 `config-gen-engine`）
- `managing-code-review`（伞形） — 当 `/code-review` 逻辑超 100 行时加
- `mcp-setup-guide`
- `ai-collaboration-primer`
- 其余按"真问题驱动才加"原则

### Agent 缺口（2 个）

文章 5.1 图表之外的阶段级 Agent。本骨架的 20 个已覆盖所有明确图表中的 Agent。

### MCP 缺口

- Jira / 飞书 / DingTalk 替换：未开箱
- 内部 TAPD / iWiki / 企微：无法外部重建

## 开发中阶段状态

当前 Phase 1 完成：基础设施 + 上下文文档。
Phase 2（Commands + Skills）和 Phase 3（Agents）未开始。

- [ ] Phase 2 — Commands 16 个 + Skills 10 个
- [ ] Phase 3 — Agents 20 个
- [ ] Phase 4 — 集成验收（跑通一个小需求）

## 反馈

`/agentic:feedback`（Phase 2 后可用）写入 `context/team/feedback-log.yaml`。
```

- [ ] **Step 2：验证 CLAUDE.md 行数**

```bash
wc -l CLAUDE.md
```

期望：< 200 行。

- [ ] **Step 3：统计 Phase 1 全部产出**

```bash
echo "=== 文件数统计 ==="
echo "根配置: $(ls .gitignore README.md CLAUDE.md 2>/dev/null | wc -l) / 3"
echo ".claude/ 配置: $(ls .claude/settings.json .claude/settings.local.json.example 2>/dev/null | wc -l) / 2"
echo ".mcp.json: $(ls .mcp.json 2>/dev/null | wc -l) / 1"
echo "Hooks: $(ls .claude/hooks/*.sh 2>/dev/null | wc -l) / 3"
echo "Hook tests: $(ls .claude/hooks/tests/*.sh 2>/dev/null | wc -l) / 3"
echo "StatusLine: $(ls .claude/statusline.sh 2>/dev/null | wc -l) / 1"
echo "INDEX.md: $(find context requirements -name INDEX.md | wc -l) / 6"
echo "Team base: $(ls context/team/git-workflow.md context/team/tool-chain.md context/team/ai-collaboration.md context/team/feedback-log.yaml 2>/dev/null | wc -l) / 4"
echo "Engineering spec: $(find context/team/engineering-spec -name '*.md' | wc -l)"
echo "Onboarding: $(ls context/team/onboarding/agentic-engineer-guide.md 2>/dev/null | wc -l) / 1"
echo "Learning path: $(ls context/team/onboarding/learning-path/*.md | wc -l) / 8"
echo "Rollout: $(ls context/team/rollout/*.md | wc -l) / 2"
```

期望全部达标。engineering spec 应至少 8 份（7 规范 + 1 specs 下的设计文档）。

- [ ] **Step 4：跑全部 hook / statusline 测试**

```bash
for t in .claude/hooks/tests/test_*.sh .claude/tests/test_*.sh; do
    [ -f "$t" ] || continue
    echo "=== $t ==="
    OLDPWD=$(pwd) bash "$t" || echo "FAIL"
done
```

期望：所有测试 Passed。

- [ ] **Step 5：验证 git 状态干净**

```bash
git status
```

应显示 `nothing to commit, working tree clean`（CLAUDE.md 还没 commit 前可能有），否则先 commit。

- [ ] **Step 6：Commit CLAUDE.md**

```bash
git add CLAUDE.md
git commit -m "docs: 添加项目级 CLAUDE.md 根索引

Phase 1 完成收尾。Phase 1 交付：
- 5 个根配置文件
- 4 个脚本（3 Hooks + StatusLine）
- 6 个 INDEX.md 建立 Context 树
- 4 份团队通用规范
- 7 份体系自身规范（设计指导 3 + 工具规范 3 + 迭代 SOP 1）
- 1 份入门指南 + 8 份学习路径
- 2 份团队落地文档

合计 38 个文件。"
```

- [ ] **Step 7：最终 git log 核对**

```bash
git log --oneline
```

应看到 ~19 个 commit，从 `docs(spec): 初始化骨架设计文档` 到 `docs: 添加项目级 CLAUDE.md 根索引`。

---

## Phase 1 完成检查清单

- [ ] Task 1-20 全部 commit 完成
- [ ] `git status` 干净
- [ ] 全部 hook/statusline 测试通过
- [ ] `CLAUDE.md` < 200 行
- [ ] `.mcp.json`、`.claude/settings.json` JSON 合法
- [ ] `feedback-log.yaml` YAML 合法
- [ ] `context/` 下共 38 个 Phase 1 新增文件

## Phase 2 预览（下一个 plan）

Phase 2 将实现：
- 16 个 Command（`.claude/commands/**/*.md`）
- 10 个 Skill（`.claude/skills/<name>/SKILL.md` + reference/ + templates/）

Phase 2 结束时：运行 `/requirement:new` 能完成前 3 个阶段（初始化、需求定义、技术预研）的流程编排（Agent 行为逻辑放 Phase 3）。
