# Phase 2b 实施计划 · 16 Command + 集成验证

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建设 16 个 Command 作为骨架的意图入口，全部为薄层委托（< 100 行，仅预检 + 委托给 Phase 2a 的 Skill）；完成后 Phase 2b 结束能运行 `/requirement:new` 跑通 bootstrap 阶段。

**Architecture:** 16 Command 分 4 组：`/requirement:*` × 7（委托 managing-requirement-lifecycle）、`/knowledge:*` × 5（委托 managing-knowledge）、`/agentic:*` × 2（自含）、`/code-review` + `/note` × 2（根命令）。Command 只做意图声明，流程逻辑在 Skill 里，改规则只改 Skill。

**Tech Stack:** Markdown + frontmatter。

**Phase 2b 完成标准:**
- `.claude/commands/` 下 16 个 Command 文件全部就位
- 每个 Command 严格 < 100 行
- 每个 Command 的"委托"指向的 Skill 在 Phase 2a 已存在
- 集成冒烟：运行 `/requirement:new` 能正确 bootstrap（建分支 / 目录 / meta.yaml）
- 所有 Command 提交（按分组 commit，共 6 次）

**Reference:**
- Skill 清单：`.claude/skills/*/SKILL.md`
- Command 规范：`context/team/engineering-spec/tool-design-spec/command-spec.md`
- 设计规范：`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md` §3.1

---

## 文件结构

Phase 2b 创建的全部文件（16 个 Command）：

```
.claude/commands/
├── requirement/
│   ├── new.md
│   ├── continue.md
│   ├── next.md
│   ├── save.md
│   ├── status.md
│   ├── rollback.md
│   └── list.md
├── knowledge/
│   ├── extract-experience.md
│   ├── generate-sop.md
│   ├── generate-checklist.md
│   ├── optimize-doc.md
│   └── organize-index.md
├── agentic/
│   ├── help.md
│   └── feedback.md
├── code-review.md
└── note.md
```

---

## Task 1：`/requirement:*` 命令族（7 个）

**Files:**
- Create: `.claude/commands/requirement/new.md`
- Create: `.claude/commands/requirement/continue.md`
- Create: `.claude/commands/requirement/next.md`
- Create: `.claude/commands/requirement/save.md`
- Create: `.claude/commands/requirement/status.md`
- Create: `.claude/commands/requirement/rollback.md`
- Create: `.claude/commands/requirement/list.md`

**Reference:** Spec §3.1；Skill `managing-requirement-lifecycle`；Command 规范 `tool-design-spec/command-spec.md`

全部 7 个 Command 都委托给 `managing-requirement-lifecycle` Skill，只是触发不同子流程。

- [ ] **Step 1: Create `requirement/new.md`**

```markdown
---
description: 创建新需求——自动建分支、目录、meta.yaml 骨架
argument-hint: <需求标题>
---

## 用途

开始一个新需求开发周期。会创建：

- 新分支 `feat/req-<ID>`（从 main 切出）
- 需求目录 `requirements/<ID>/`
- 骨架文件：`meta.yaml` / `plan.md` / `process.txt`（空）/ `notes.md`（空）

## 预检

1. 工作目录 clean（无 uncommitted changes）：`git status --porcelain` 为空
2. 当前分支为 `main` 或其他起点分支（不能从某个既有 feat/req-* 派生）
3. 参数 `<需求标题>` 非空

预检不通过立即返回错误并终止。

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **bootstrap** 流程：

- 生成唯一 REQ-ID（格式 `REQ-YYYY-NNN`，NNN 按现有 requirements/ 下序号 +1）
- 从 `templates/meta.yaml.tmpl` 和 `templates/plan.md.tmpl` 生成初始文件
- 切分支并做 bootstrap commit
- 输出需求 ID 与下一步提示
```

- [ ] **Step 2: Create `requirement/continue.md`**

```markdown
---
description: 恢复之前中断的需求上下文
argument-hint: "[需求 ID]（可选，不填则按当前分支推断）"
---

## 用途

开新会话要接着之前的需求继续工作时触发。

## 预检

1. 如用户提供了需求 ID：`requirements/<ID>/meta.yaml` 存在
2. 如未提供：当前分支能在某个 `requirements/*/meta.yaml` 的 `branch` 字段找到匹配
3. 都没找到 → 列出当前所有需求供选择

## 委托

调用 Skill `managing-requirement-lifecycle` → 再委托给 `requirement-session-restorer` Skill：

- 按顺序读 `meta.yaml` / `process.txt`（末 50 行）/ `notes.md` / `plan.md`
- 输出 < 200 字的"恢复摘要"
- 等用户确认后继续工作
```

- [ ] **Step 3: Create `requirement/next.md`**

```markdown
---
description: 前进到下一阶段（含强制门禁检查）
---

## 用途

当前阶段工作完成，要切到下一阶段。会触发该阶段切换的门禁检查。

## 预检

1. 当前分支对应 `requirements/*/meta.yaml` 存在
2. `meta.yaml.phase` 不是最终态 `completed`

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **next** 流程：

- 查 `reference/gate-checklist.md` 中"当前阶段 → 下一阶段"段的全部检查项
- 依次执行每条检查
- 任一失败 → 列出缺口并终止（不修改 phase）
- 全部通过 → 更新 `meta.yaml.phase` + `gates_passed` 追加一条
- 委托 `requirement-progress-logger` 写 `[phase-transition]` 日志
- 输出新阶段的首个动作提示
```

- [ ] **Step 4: Create `requirement/save.md`**

```markdown
---
description: 保存进度到 process.txt，为跨会话恢复准备
argument-hint: "[事件描述]（可选）"
---

## 用途

重要节点主动存档；或会话即将结束时用户显式调用。Hook 已处理工具级自动记录，这个命令用于**语义级显式节点**（例如"方案评审过了"、"发现一个阻塞"）。

## 预检

1. 当前分支对应需求存在

## 委托

调用 Skill `managing-requirement-lifecycle` → 再委托给 `requirement-progress-logger`：

- 如用户提供了事件描述：直接用作日志正文
- 如未提供：从最近对话上下文摘要一句话作日志正文
- 格式化 `ISO8601 [phase] <事件描述>`
- 追加到 process.txt
- 输出确认
```

- [ ] **Step 5: Create `requirement/status.md`**

```markdown
---
description: 查看当前需求的阶段、进度、待办概览
---

## 用途

快速了解当前需求状态，不深入细节。典型 < 5 秒读完的摘要。

## 预检

1. 当前分支对应需求存在

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **status** 流程：

- 读 `meta.yaml` → 当前阶段 + 已通过门禁列表
- 读 `process.txt` 末 3 行 → 最近动作
- 扫描 `artifacts/` → 已产出文件清单
- 如在阶段 7（development）：额外扫 `artifacts/tasks/*.md`，统计 feature 状态（pending / in-progress / done）
- 输出紧凑摘要（< 400 字）
```

- [ ] **Step 6: Create `requirement/rollback.md`**

```markdown
---
description: 回退到早期阶段，归档当前产出物
argument-hint: <目标阶段英文标识>
---

## 用途

发现前序阶段设计有问题，需要回到更早阶段重新做。

## 预检

1. 当前分支对应需求存在
2. 参数 `<目标阶段>` 是合法阶段英文标识（bootstrap / definition / tech-research / outline-design / detail-design / task-planning / development / testing）
3. 目标阶段严格**早于**当前 `meta.yaml.phase`
4. 工作目录 clean（避免回退丢失未提交改动）

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **rollback** 流程：

- 把 `artifacts/` 下所有"晚于目标阶段"的产出归档到 `artifacts/.rollback-<ISO8601>/`
- 更新 `meta.yaml.phase` = 目标阶段
- 询问用户回退原因（一句话），追加到 `notes.md`
- 委托 `requirement-progress-logger` 写 `[phase-transition] <old> → <new> (rollback)`
- 分析下游影响（哪些后续阶段的产出将作废）并输出给用户
```

- [ ] **Step 7: Create `requirement/list.md`**

```markdown
---
description: 查看所有需求的状态索引
---

## 用途

多需求并行时快速看整体进度；新人上手时了解团队当前在做什么。

## 预检

无（无需求时也能运行——输出"当前无活跃需求"）

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **list** 流程：

- 扫 `requirements/*/meta.yaml`
- 按 `created_at` 倒序
- 输出 Markdown 表格：ID / 标题 / 阶段（中文名）/ 分支 / 创建时间

| # | 列 |
|---|---|
| 1 | REQ-2026-003 \| 注册优化 \| 详细设计 \| feat/req-2026-003 \| 2026-04-18 |
```

- [ ] **Step 8: 验证每个 Command < 100 行**

```bash
for f in .claude/commands/requirement/*.md; do
    lines=$(wc -l < "$f")
    if [ "$lines" -gt 100 ]; then
        echo "⚠️  $f = $lines 行（超标）"
    else
        echo "✓  $f = $lines 行"
    fi
done
```

应全部 ✓。

- [ ] **Step 9: Commit**

```bash
git add .claude/commands/requirement/
git commit -m "feat(command): 添加 /requirement:* 命令族（7 个）"
```

---

## Task 2：`/knowledge:*` 命令族（5 个）

**Files:**
- Create: `.claude/commands/knowledge/extract-experience.md`
- Create: `.claude/commands/knowledge/generate-sop.md`
- Create: `.claude/commands/knowledge/generate-checklist.md`
- Create: `.claude/commands/knowledge/optimize-doc.md`
- Create: `.claude/commands/knowledge/organize-index.md`

**Reference:** Skill `managing-knowledge`；对应 `reference/*.md`

全部委托 `managing-knowledge`，子意图通过命令名区分。

- [ ] **Step 1: Create `knowledge/extract-experience.md`**

```markdown
---
description: 从实践数据中提取可迁移的经验
argument-hint: "[notes 文件路径]（可选，默认当前需求的 notes.md）"
---

## 用途

需求验收后或阶段性总结时，从碎片化笔记中提炼结构化经验，沉淀到 `context/`。

## 预检

1. 如用户提供路径：文件存在且非空
2. 如未提供：当前分支对应需求的 `notes.md` 存在且非空

## 委托

调用 Skill `managing-knowledge`，子意图 **extract-experience**：

- 加载 `.claude/skills/managing-knowledge/reference/extract-experience.md` 的规则
- 按"三必要条件"（跨需求/AI 反复错/跨会话需保留）筛选候选
- 渐进式输出候选清单（< 5 条+简要描述）
- 用户确认要沉淀哪几条 + 归属位置（`context/project/<X>/` 或 `context/team/experience/`）
- 落盘 + 更新对应 INDEX.md
```

- [ ] **Step 2: Create `knowledge/generate-sop.md`**

```markdown
---
description: 从实践中生成标准操作流程（SOP）
argument-hint: <目标场景名>
---

## 用途

某个操作反复出现、流程可标准化时生成 SOP 沉淀下来。

## 预检

1. 参数 `<目标场景名>` 非空
2. `context/team/experience/` 或 `requirements/*/notes.md` 下能 grep 到涉及该场景的条目（≥ 2 条才值得做 SOP）

## 委托

调用 Skill `managing-knowledge`，子意图 **generate-sop**：

- 加载 `reference/generate-sop.md` 规则
- 收集相关实践 → 识别通用步骤 + 决策点
- 起草 SOP 结构（触发条件 / 前置检查 / 主流程 / 决策点 / 完成标准）
- 先输出结构+关键步骤给用户确认
- 确认后落盘到 `context/team/engineering-spec/sop/<slug>.md` 或 `context/team/experience/`
- 更新对应 INDEX.md
```

- [ ] **Step 3: Create `knowledge/generate-checklist.md`**

```markdown
---
description: 从实践中生成检查清单
argument-hint: <目标场景名>
---

## 用途

发版 / PR 评审 / 上线等高风险环节需要防止遗漏时，从过往失败案例生成可执行的检查清单。

## 预检

1. 参数 `<目标场景名>` 非空

## 委托

调用 Skill `managing-knowledge`，子意图 **generate-checklist**：

- 加载 `reference/generate-checklist.md` 规则
- 收集失败案例 / 漏检项 → 归并去重
- 按严重度分三档：Blocker / Must / Nice-to-have
- 先输出 3-5 条关键项给用户确认
- 落盘到 `context/team/checklists/<slug>.md`
- 更新对应 INDEX.md
```

- [ ] **Step 4: Create `knowledge/optimize-doc.md`**

```markdown
---
description: 优化已有文档的结构与可读性
argument-hint: <文档路径>
---

## 用途

已有文档结构乱、信息检索难时触发整理。

## 预检

1. 参数 `<文档路径>` 非空
2. 文件存在

## 委托

调用 Skill `managing-knowledge`，子意图 **optimize-doc**：

- 加载 `reference/optimize-doc.md` 规则
- 识别问题清单（3-5 条：结构 / 冗余 / 索引不可达等）
- 每条说明：现状、建议、影响范围
- 用户确认要优化哪几条
- 实施优化，保持核心信息不变
- 文档末尾加"最近优化记录"段
- 如锚点/标题有变：更新 INDEX.md
```

- [ ] **Step 5: Create `knowledge/organize-index.md`**

```markdown
---
description: 整理指定目录的 INDEX.md 索引
argument-hint: "[目录路径]（可选，默认当前目录）"
---

## 用途

INDEX.md 与实际文件不符时（新增未列 / 重命名链接失效 / 删除遗留），触发整理。

## 预检

1. 如用户提供路径：目录存在
2. 如未提供：默认用当前需求的 `artifacts/`

## 委托

调用 Skill `managing-knowledge`，子意图 **organize-index**：

- 加载 `reference/organize-index.md` 规则
- 扫目录 + 下一级文件
- 对比 INDEX.md 与实际 → 输出 diff 报告（遗漏/腐化/重命名）
- 用户确认后修正 INDEX.md
- 对每条新增/删除写一句理由
```

- [ ] **Step 6: 验证每个 < 100 行**

```bash
for f in .claude/commands/knowledge/*.md; do
    lines=$(wc -l < "$f")
    [ "$lines" -le 100 ] && echo "✓ $f = $lines" || echo "⚠️ $f = $lines"
done
```

- [ ] **Step 7: Commit**

```bash
git add .claude/commands/knowledge/
git commit -m "feat(command): 添加 /knowledge:* 命令族（5 个）"
```

---

## Task 3：`/agentic:*` 命令族（2 个）

**Files:**
- Create: `.claude/commands/agentic/help.md`
- Create: `.claude/commands/agentic/feedback.md`

**Reference:** Spec §3.1；`context/team/feedback-log.yaml`

自含命令（不委托 Skill）。

- [ ] **Step 1: Create `agentic/help.md`**

```markdown
---
description: Agentic 工程上手引导——MCP 配置、常用流程、FAQ
argument-hint: "[topic]（可选，如 mcp / requirement / review / 空=默认）"
---

## 用途

新人上手，或老用户忘了某个流程时，快速查阅。

## 预检

无。

## 行为

不委托 Skill。根据参数输出引导内容（< 800 字）：

### 无参数（默认）

输出：

- **核心链接**（按顺序读）：
  - 入门：`context/team/onboarding/agentic-engineer-guide.md`
  - 8 阶段学习路径：`context/team/onboarding/learning-path/`
  - 设计文档：`context/team/engineering-spec/specs/`
- **3 个最常用命令**：
  - `/requirement:new <标题>` — 开始新需求
  - `/code-review` — 多 Agent 并行审查
  - `/note <内容>` — 随手记录
- **有问题就 `/agentic:feedback <type> <target> <body>`**

### topic=mcp

读 `.mcp.json`，列出已启用 MCP；参考 `learning-path/01-environment.md` 里的配置指引，引导用户如何补充。

### topic=requirement

列 7 个 `/requirement:*` 命令及简短用途说明。

### topic=review

介绍 `/code-review` 双模（独立 / 嵌入）+ 7 个 checker 维度名。

## 硬约束

- 输出 < 800 字
- 不执行任何改文件动作（纯只读 + 输出）
```

- [ ] **Step 2: Create `agentic/feedback.md`**

```markdown
---
description: 把反馈写入 feedback-log.yaml（praise / complaint / suggestion / bug）
argument-hint: <type> <target> <body>
---

## 用途

团队成员日常有问题/建议时快速记录。

## 预检

1. `context/team/feedback-log.yaml` 存在且 YAML 合法
2. 3 个参数：
   - `type` ∈ {praise, complaint, suggestion, bug}（必填）
   - `target` 格式形如 `agent:<name>` / `skill:<name>` / `command:<name>` / `hook:<name>` / `docs` / `other`（必填）
   - `body` 简体中文正文（必填）
3. `body` 不含敏感信息（简单 regex 扫 `password|token|api[_-]?key|secret`）——命中则阻止并提示

## 行为

不委托 Skill：

1. 生成 entry id：`YYYYMMDD-NNN`（NNN 按当日已有条目数 +1）
2. 读 `git config user.email` 作为 `user`
3. 构造 YAML entry：
   ```yaml
   - id: <id>
     at: <ISO8601>
     user: <email>
     type: <type>
     target: <target>
     body: <body>
     resolved: false
     resolution: null
   ```
4. append 到 `context/team/feedback-log.yaml` 的 `entries` 列表
5. `python3 -c "import yaml; yaml.safe_load(open('context/team/feedback-log.yaml'))"` 验证
6. Commit：
   ```
   git add context/team/feedback-log.yaml
   git commit -m "feedback(<type>): <target> — <body 首 30 字符>"
   ```
7. 输出条目 ID 给用户

## 硬约束

- 敏感信息扫描必须做，命中即拒绝写入
- commit 前必须 YAML 合法
```

- [ ] **Step 3: 验证 < 100 行**

```bash
wc -l .claude/commands/agentic/*.md
```

- [ ] **Step 4: Commit**

```bash
git add .claude/commands/agentic/
git commit -m "feat(command): 添加 /agentic:help 和 /agentic:feedback"
```

---

## Task 4：`/code-review` 根命令

**Files:**
- Create: `.claude/commands/code-review.md`

**Reference:** Spec §5；Skill `code-review-prepare` / `code-review-report`

- [ ] **Step 1: Create `code-review.md`**

```markdown
---
description: 多 Agent 并行代码审查（双模：独立 / 嵌入）
argument-hint: "[scope]（可选，默认 git diff main..HEAD）"
---

## 用途

- **独立模式**：任意项目运行 `/code-review`，审当前分支 vs main 的增量
- **嵌入模式**：阶段 7 `feature-lifecycle-manager` 在 feature 完成时自动调用，scope 限定到该 feature

## 预检

1. 在 git 仓库内（`git rev-parse` 无错）
2. 工作区 clean 或变更已 stash（不审查 uncommitted 内容）
3. 增量行数 < 2000（超了引导用户先拆小）

## 流程

本命令编排顺序流（不委托单一 Skill，自身协调三步）：

### 1. 预检：`code-review-prepare` Skill

- 识别模式（embedded / standalone）
- 取 diff / 确定 services / 写 `.review-scope.json`
- 输出预检摘要，用户确认继续

### 2. 并行审查

**Phase 3 启用**：主 Agent 在一条消息里并行调用 7 个专项 checker Agent + 1 综合 reviewer：

- `design-consistency-checker`
- `security-checker`
- `concurrency-checker`
- `complexity-checker`
- `error-handling-checker`
- `auxiliary-spec-checker`
- `performance-checker`
- `code-quality-reviewer`（综合裁决）

**Phase 2b 降级**：上述 Agent 未就位时，主 Agent 按 7 个维度**顺序**做审查（每维度摘要 < 200 字）。由 `code-review-report` Skill 在报告中标注"⚠️ 未运行独立 checker Agent，主 Agent 顺序审查"。

### 3. 报告：`code-review-report` Skill

- 合并 issue（去重 + 严重度分层）
- 应用综合裁决结论（approved / needs_revision / rejected）
- 写入文件：
  - 嵌入：`requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`
  - 独立：`/tmp/code-review-YYYYMMDD-HHMMSS.md`
- 主对话只输出结论 + critical 列表 + 报告文件路径
```

- [ ] **Step 2: 验证 < 100 行**

```bash
wc -l .claude/commands/code-review.md
```

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/code-review.md
git commit -m "feat(command): 添加 /code-review（含 Phase 2b 顺序降级）"
```

---

## Task 5：`/note` 根命令

**Files:**
- Create: `.claude/commands/note.md`

**Reference:** Spec §5.3

日常最高频命令。

- [ ] **Step 1: Create `note.md`**

```markdown
---
description: 追加笔记到当前需求的 notes.md
argument-hint: <内容>
---

## 用途

开发过程中随手记录发现、坑、想法。是日常最高频的命令，直接 append 不触发任何 Skill。

## 预检

1. 当前分支对应 `requirements/*/meta.yaml` 存在（需要 notes.md 归属）
2. 参数 `<内容>` 非空
3. `<内容>` 长度 < 500 字符（超了引导用户分多次 `/note`）

## 行为

不委托 Skill。直接执行：

1. 反查 `requirements/*/meta.yaml` 找到 branch 匹配的需求
2. 读 `meta.yaml.phase`
3. 追加到 `requirements/<id>/notes.md` 末尾：
   ```
   - [<ISO8601>] [<phase>] <内容>
   ```
4. 输出简短确认（< 50 字）：`已追加到 requirements/<id>/notes.md`
5. **不 commit**—— notes.md 会在 `/requirement:save` 或合适节点由开发者统一提交

## 硬约束

- 单次内容 < 500 字符
- 不 commit
- 格式固定：`- [ISO8601] [phase] <内容>`
```

- [ ] **Step 2: 验证 < 100 行**

```bash
wc -l .claude/commands/note.md
```

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/note.md
git commit -m "feat(command): 添加 /note 命令"
```

---

## Task 6：集成验证 + plans/README 更新

**Files:**
- Modify: `context/team/engineering-spec/plans/README.md`

- [ ] **Step 1: Command 数量校验**

```bash
echo "=== Command 文件总数 ==="
find .claude/commands -name '*.md' -type f | wc -l
# 期望：16
```

- [ ] **Step 2: 每个 Command < 100 行**

```bash
echo "=== 逐 Command 行数校验 ==="
for f in $(find .claude/commands -name '*.md' -type f); do
    lines=$(wc -l < "$f")
    if [ "$lines" -gt 100 ]; then
        echo "⚠️  $f = $lines 行（超标）"
    else
        echo "✓  $f = $lines"
    fi
done
```

所有应为 ✓。

- [ ] **Step 3: Skill 委托引用校验**

```bash
echo "=== Command 委托的 Skill 必须存在 ==="
for f in $(find .claude/commands -name '*.md' -type f); do
    grep -oE 'Skill `[^`]+`' "$f" | grep -oE '`[^`]+`' | tr -d '`' | sort -u | while read skill; do
        if [ -d ".claude/skills/$skill" ]; then
            echo "✓ $f → $skill"
        else
            echo "✗ $f → $skill（Skill 不存在）"
        fi
    done
done
```

所有应为 ✓（或为自含命令时无委托，无输出）。

- [ ] **Step 4: 预期 Command 清单比对**

```bash
echo "=== 必备的 16 个 Command ==="
expected=(
    "requirement/new.md" "requirement/continue.md" "requirement/next.md"
    "requirement/save.md" "requirement/status.md" "requirement/rollback.md"
    "requirement/list.md"
    "knowledge/extract-experience.md" "knowledge/generate-sop.md"
    "knowledge/generate-checklist.md" "knowledge/optimize-doc.md"
    "knowledge/organize-index.md"
    "agentic/help.md" "agentic/feedback.md"
    "code-review.md" "note.md"
)
for e in "${expected[@]}"; do
    f=".claude/commands/$e"
    if [ -f "$f" ]; then echo "✓ $e"; else echo "✗ $e 缺失"; fi
done
```

全部 ✓。

- [ ] **Step 5: 冒烟测试——简单解析 frontmatter 合法**

```bash
echo "=== 每个 Command 必须有 frontmatter + description ==="
for f in $(find .claude/commands -name '*.md' -type f); do
    if head -1 "$f" | grep -q '^---$' && grep -q '^description:' "$f"; then
        echo "✓ $f"
    else
        echo "✗ $f frontmatter 不完整"
    fi
done
```

- [ ] **Step 6: 更新 plans/README.md**

把 Phase 2b 状态改为已完成：

```markdown
| 2b | 16 Command + 集成验证 | [phase-2b-commands](./2026-04-20-phase-2b-commands.md) | ✅ 已完成（6 Tasks · 分支 `setup/phase-2b-commands`） |
```

- [ ] **Step 7: 最终 commit**

```bash
git add context/team/engineering-spec/plans/README.md
git commit -m "docs(plan): Phase 2b 状态改为已完成"
```

- [ ] **Step 8: git log 核对**

```bash
git log --oneline main..setup/phase-2b-commands
```

应看到 6 个 commit（对应 Task 1-6 各一个）。

---

## Phase 2b 完成检查清单

- [ ] 16 个 Command 文件全部创建
- [ ] 每个 Command < 100 行
- [ ] 每个 Command 委托的 Skill 存在
- [ ] 每个 Command 有合法 frontmatter + description
- [ ] 6 个 commit（按分组）

## Phase 3 预览

Phase 3 将实现：

- 20 个 Agent（`.claude/agents/*.md`）
  - 跨阶段 4（universal-context-collector / documentation-batch-updater / engineering-spec-retriever / engineering-spec-curator）
  - 阶段专属 8（bootstrap / input-normalizer / quality-reviewer × 3 / tech-feasibility / test-runner / traceability-consistency）
  - 代码审查 8（7 checker + code-quality-reviewer）

Phase 3 结束时：`/code-review` 的并行审查机制启用；8 阶段门禁的 Agent 侧校验全部生效。

## Phase 4 预览

集成验收——用一个简单的"给 CLAUDE.md 加一段 FAQ"小需求跑通 8 阶段，验证骨架端到端可用。
