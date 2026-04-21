# Phase 2a 实施计划 · 10 个 Skill

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Phase 1 基础设施之上，建设骨架的 10 个 Skill——需求生命周期（5 个）、代码审查（2 个）、门禁（1 个）、功能点（1 个）、知识管理（1 个）。每个 Skill 遵守 `SKILL.md < 2k token` 硬约束，详细知识拆到 `reference/`、模板到 `templates/`、脚本到 `scripts/`。

**Architecture:** 三层一致性——Command（Phase 2b）调用 Skill；Skill 编排流程并在需要时调用 Agent（Phase 3）。Phase 2a 完成后，Skill 可由主 Agent 直接按 SKILL.md 执行；等 Phase 3 Agent 建好后自动获得多 Agent 并行能力。

**Tech Stack:** Markdown（SKILL.md + reference + templates）、Bash（scripts/）、YAML（meta.yaml 模板）。

**Phase 2a 完成标准:**
- `.claude/skills/` 下 10 个子目录（每个 Skill 一个）
- 全部 `SKILL.md` 文件 ≤ 2k token（约 500 汉字 + 代码）
- 每个 Skill 的依赖资源（reference / templates / scripts）齐备
- 主 Agent 读 SKILL.md 后能按指令执行，不依赖 Phase 3 的 Subagent（使用 fallback 行为或标记未实现）
- 所有 Skill 提交各一个 commit

**Reference:**
- 设计文档：`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md`
- Skill 规范：`context/team/engineering-spec/tool-design-spec/skill-spec.md`
- 工作原则：`context/team/ai-collaboration.md`

**预置分支:** `setup/phase-2a-skills`（从 `setup/phase-1-foundation` 切出或合并 Phase 1 后从 `main` 切出）

---

## 文件结构总览

Phase 2a 创建的全部文件（共 **约 24 个**）：

```
.claude/skills/
├── managing-requirement-lifecycle/
│   ├── SKILL.md
│   ├── reference/
│   │   ├── phase-rules.md
│   │   └── gate-checklist.md
│   └── templates/
│       ├── meta.yaml.tmpl
│       └── plan.md.tmpl
│
├── requirement-doc-writer/
│   ├── SKILL.md
│   ├── reference/sourcing-rules.md
│   └── templates/requirement.md.tmpl
│
├── requirement-session-restorer/
│   └── SKILL.md
│
├── requirement-progress-logger/
│   └── SKILL.md
│
├── task-context-builder/
│   ├── SKILL.md
│   └── reference/extract-rules.md
│
├── code-review-prepare/
│   ├── SKILL.md
│   └── reference/scope-schema.md
│
├── code-review-report/
│   ├── SKILL.md
│   └── templates/review-report.md.tmpl
│
├── traceability-gate-checker/
│   └── SKILL.md
│
├── feature-lifecycle-manager/
│   ├── SKILL.md
│   ├── reference/feature-states.md
│   └── templates/feature-task.md.tmpl
│
└── managing-knowledge/
    ├── SKILL.md
    └── reference/
        ├── extract-experience.md
        ├── generate-sop.md
        ├── generate-checklist.md
        ├── optimize-doc.md
        └── organize-index.md
```

---

## Task 1：`managing-requirement-lifecycle` Skill

**Files:**
- Create: `.claude/skills/managing-requirement-lifecycle/SKILL.md`
- Create: `.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md`
- Create: `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md`
- Create: `.claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl`
- Create: `.claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl`

**Reference:** Spec §3.2 / §4.1 / §4.2 / §4.4

此 Skill 是 7 个 `/requirement:*` 命令的伞形——所有命令都委托到这里，通过意图识别路由到具体动作。

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: managing-requirement-lifecycle
description: 需求全生命周期管理伞形 Skill，被 7 个 /requirement:* 命令共用。负责阶段切换、门禁校验、状态持久化。
---

## 什么时候用

用户通过 `/requirement:*` 命令，或口头说"新建需求 / 继续需求 / 下一阶段 / 保存进度 / 查看状态 / 回退 / 列出需求"时。

## 核心流程

1. **识别意图**：映射到 7 个子动作之一
   - 新建 → bootstrap（创建分支+目录+meta.yaml）
   - 继续 → 委托 `requirement-session-restorer`
   - 下一阶段 → 门禁校验（见 `reference/phase-rules.md`）→ 更新 phase
   - 保存 → 委托 `requirement-progress-logger`
   - 查看状态 → 读 meta.yaml 输出阶段+最近动作
   - 回退 → 归档当前 artifacts + 改 phase + 写 notes.md
   - 列出 → 扫 `requirements/*/meta.yaml`，输出需求索引

2. **状态持久化**：每次阶段变更必须更新 `meta.yaml` 的 `phase` + 追加 `gates_passed`

3. **门禁校验**：阶段切换前必走 `reference/gate-checklist.md`

## 硬约束

- ❌ 禁止跳过门禁（例：从 `definition` 直接跳 `detail-design`）
- ❌ 禁止在非功能分支上 bootstrap（会被 Hook 拦截）
- ✅ `meta.yaml` 更新必须原子：先写临时文件再 mv（避免中间状态）
- ✅ 未知意图必须向用户澄清，不得"猜测"后擅自推进

## 参考资源

- [`reference/phase-rules.md`](reference/phase-rules.md) — 8 阶段定义 + 切换规则
- [`reference/gate-checklist.md`](reference/gate-checklist.md) — 各阶段门禁具体检查项
- [`templates/meta.yaml.tmpl`](templates/meta.yaml.tmpl) — 新建需求的 meta.yaml 模板
- [`templates/plan.md.tmpl`](templates/plan.md.tmpl) — 新建需求的 plan.md 模板
```

- [ ] **Step 2: Create reference/phase-rules.md**

```markdown
# 8 阶段规则

## 阶段标识（meta.yaml 的 `phase` 字段）

| # | 英文标识 | 中文名 | 做什么 |
|---|---|---|---|
| 1 | `bootstrap` | 初始化 | 命名、建分支、建目录 |
| 2 | `definition` | 需求定义 | 输入清洗、上下文收集、文档撰写、评审 |
| 3 | `tech-research` | 技术预研 | 可行性评估、风险预判 |
| 4 | `outline-design` | 概要设计 | 架构方案、模块划分、评审 |
| 5 | `detail-design` | 详细设计 | 接口签名、数据结构、时序图、评审 |
| 6 | `task-planning` | 任务规划 | 功能点拆分、进入开发门禁 |
| 7 | `development` | 开发实施 | 编码、代码审查、提交 |
| 8 | `testing` | 测试验收 | 测试用例生成、执行、追溯链校验 |

## 合法切换

只允许**相邻**前进（除 bootstrap 外）：

```
bootstrap → definition → tech-research → outline-design → detail-design
         → task-planning → development → testing → completed
```

回退允许跨阶段，但必须执行回退流程（归档 artifacts + 写 notes.md）。

## 各阶段必产出

| 阶段 | 必备 artifacts |
|---|---|
| bootstrap | meta.yaml, plan.md 存在 |
| definition | artifacts/requirement.md |
| tech-research | artifacts/tech-feasibility.md |
| outline-design | artifacts/outline-design.md |
| detail-design | artifacts/detailed-design.md + features.json |
| task-planning | artifacts/tasks/*.md（每 feature 一个） |
| development | 代码已推送到 feature 分支 + 每 feature 有 review 报告 |
| testing | artifacts/test-report.md + 追溯链报告 |
```

- [ ] **Step 3: Create reference/gate-checklist.md**

```markdown
# 阶段门禁检查清单

每次 `/requirement:next` 切阶段时，必须全部通过。失败则阻止切换并列出缺口。

## bootstrap → definition

- [ ] `meta.yaml` 存在且合法
- [ ] 当前分支 = `meta.yaml.branch`
- [ ] `plan.md` 存在

## definition → tech-research

- [ ] `artifacts/requirement.md` 存在
- [ ] 需求评审结论 ≠ `rejected`（由 `requirement-quality-reviewer` Agent 产生，Phase 2 可先跳过此校验，标记 "reviewer pending"）
- [ ] 所有"待用户确认"项已处理（无 `[待用户确认]` 遗留标记）

## tech-research → outline-design

- [ ] `artifacts/tech-feasibility.md` 存在
- [ ] 风险评估段落非空

## outline-design → detail-design

- [ ] `artifacts/outline-design.md` 存在
- [ ] 概要设计评审结论 ≠ `rejected`

## detail-design → task-planning

- [ ] `artifacts/detailed-design.md` 存在
- [ ] `artifacts/features.json` 合法 JSON + 每条 feature 有 `id`、`title`、`description`
- [ ] 详细设计评审结论 ≠ `rejected`

## task-planning → development

- [ ] 每个 `features.json` 里的 feature_id 在 `artifacts/tasks/` 下有对应 .md 文件
- [ ] 每个任务文件初始状态为 `status: pending`

## development → testing

- [ ] 每个 feature_id 状态为 `done`
- [ ] 每个 feature_id 有对应的代码审查报告（`artifacts/review-*.md` 提到）
- [ ] 所有代码已 commit（无 uncommitted changes）

## testing → completed

- [ ] `artifacts/test-report.md` 存在
- [ ] `traceability-gate-checker` Skill PASS
```

- [ ] **Step 4: Create templates/meta.yaml.tmpl**

```yaml
# 替换 __PLACEHOLDER__ 为真实值
id: __REQ_ID__                 # 例：REQ-2026-001
title: __TITLE__
phase: bootstrap
created_at: __ISO8601__
branch: __BRANCH__             # 例：feat/req-2026-001
project: __PROJECT__           # 关联 context/project/<project>/
services: []                   # 涉及的服务仓库
gates_passed: []
```

- [ ] **Step 5: Create templates/plan.md.tmpl**

```markdown
# __REQ_ID__ · __TITLE__

## 目标

一句话描述本需求要交付什么业务价值。

## 范围

- 包含：
- 不包含：

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | |
| tech-research | |
| outline-design | |
| detail-design | |
| task-planning | |
| development | |
| testing | |

## 风险

- 风险 1：描述 / 应对
```

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/managing-requirement-lifecycle/
git commit -m "feat(skill): 添加 managing-requirement-lifecycle 伞形 Skill"
```

- [ ] **Step 7: Verify**

```bash
wc -w .claude/skills/managing-requirement-lifecycle/SKILL.md
ls -R .claude/skills/managing-requirement-lifecycle/
```

SKILL.md 字数 < 700（约 2k token）。目录下应有 5 个文件。

---

## Task 2：`requirement-doc-writer` Skill

**Files:**
- Create: `.claude/skills/requirement-doc-writer/SKILL.md`
- Create: `.claude/skills/requirement-doc-writer/reference/sourcing-rules.md`
- Create: `.claude/skills/requirement-doc-writer/templates/requirement.md.tmpl`

**Reference:** Spec §5.1（刨根问底）

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: requirement-doc-writer
description: 撰写 artifacts/requirement.md（阶段 2 产出物），严格执行"刨根问底"——每条关键信息必须有来源、或标记待确认/待补充。
---

## 什么时候用

在 `definition` 阶段，用户要求撰写或修订需求文档时。

## 核心流程

1. **调用 `universal-context-collector` Agent**（Phase 3 前：主 Agent 自己按 `context/team/engineering-spec/design-guidance/context-engineering.md` 的优先级检索）
2. **先输出 3-5 条关键确认点**（见 `ai-collaboration.md` 渐进式输出规则）：
   - 已获取的关键上下文来源
   - 需要用户确认的信息
   - 涉及选择的决策点
3. **用户确认后**，基于 `templates/requirement.md.tmpl` 撰写正式文档
4. **刨根问底**：按 `reference/sourcing-rules.md` 的三态规则标注每条关键信息

## 硬约束

- ❌ 禁止出现"没来源但看起来合理就写了"的第四种状态
- ❌ 禁止一次性输出完整长文档（必须先出关键确认点）
- ✅ 每条事实性信息必须是三态之一：有引用 / `[待用户确认]` / `[待补充]`
- ✅ `[待补充]` 必须附假设（内容、依据、风险、验证时机）

## 参考资源

- [`reference/sourcing-rules.md`](reference/sourcing-rules.md) — 三态规则与示例
- [`templates/requirement.md.tmpl`](templates/requirement.md.tmpl) — 需求文档模板
```

- [ ] **Step 2: Create reference/sourcing-rules.md**

```markdown
# 刨根问底三态规则

需求文档里的每条**关键事实信息**（业务规则、接口约定、数据结构、性能指标等）必须属于以下三态之一：

## 状态 1：有引用 ✅

有项目内文件或外部官方来源可以追溯。

**格式**：在事实后紧跟引用 `（来源：context/project/X/api-spec.md:42）`

**示例**：
> 用户登录失败后需延迟 5 秒再允许重试（来源：context/project/auth-service/security.md:88）。

## 状态 2：[待用户确认] ⚠️

业务规则合理但无项目内来源，需用户提供依据或确认。

**格式**：事实后加 `[待用户确认]`，并在文档末尾"待澄清清单"列出。

**示例**：
> 密码长度不少于 12 位 [待用户确认]。

**文档末尾清单**：
```
## 待澄清清单

1. 密码长度 12 位的依据（是公司统一安全规范还是本需求独有？）
```

## 状态 3：[待补充] 🚧

连假设依据都不清晰，但如果无此条件则无法推进。必须给出完整"假设记录"。

**格式**：
```markdown
> 本需求假设 QPS 峰值不超过 1000 [待补充]
> - 内容：QPS ≤ 1000
> - 依据：类似业务场景的历史经验估算
> - 风险：如实际 > 5000，当前架构无法支撑
> - 验证时机：灰度发布首周
```

## 严格禁止的第四态 ❌

**"没来源但看起来合理就写了"** —— 这是幻觉的来源。评审时发现即标记 `needs_revision`。

## 评审依据

`requirement-quality-reviewer` Agent（Phase 3）会扫描文档里所有关键信息是否标注了三态之一。Phase 2 期间由主 Agent 自检。
```

- [ ] **Step 3: Create templates/requirement.md.tmpl**

```markdown
---
id: __REQ_ID__
title: __TITLE__
created_at: __ISO8601__
refs-requirement: true   # 供 traceability-gate-checker 识别
---

# __REQ_ID__ · __TITLE__

## 背景

（一段话描述业务背景和问题。每条关键事实按三态标注。）

## 目标

- 主目标：
- 次要目标：

## 用户场景

### 场景 1：__场景名__
- 角色：
- 前置：
- 主流程：
- 期望结果：

## 非功能需求

- 性能：
- 兼容性：
- 安全/合规：

## 范围

- 包含：
- 不包含：

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|

## 待澄清清单

（列出所有 `[待用户确认]` 和 `[待补充]` 条目）

1.
```

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/requirement-doc-writer/
git commit -m "feat(skill): 添加 requirement-doc-writer（刨根问底规则）"
```

---

## Task 3：`requirement-session-restorer` Skill

**Files:**
- Create: `.claude/skills/requirement-session-restorer/SKILL.md`

**Reference:** Spec §6.4

纯指令 Skill，无 reference。

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: requirement-session-restorer
description: 跨会话恢复上下文。读 meta.yaml + process.txt + notes.md + plan.md，输出 < 200 字的"恢复摘要"，等用户确认后继续工作。
---

## 什么时候用

用户触发 `/requirement:continue` 或口头说"继续之前的需求"时。

## 核心流程

1. **定位需求**：
   - 如果用户指定了需求 ID，用它
   - 否则扫 `requirements/*/meta.yaml`，找当前分支匹配的（`git branch --show-current`）
   - 都找不到 → 请用户指定

2. **读取四个文件**（**按顺序**）：
   - `meta.yaml` → 知道阶段
   - `process.txt` 末尾 50 行 → 最近动作
   - `notes.md` → 已发现的坑/待澄清
   - `plan.md` → 当前计划

3. **输出恢复摘要**（< 200 字）：
   ```
   你在 [需求 ID] 的【[阶段中文名]】阶段，
   上次做到 [最近一个关键动作]，
   卡在 [notes.md 最后一条未解决项]（见 notes.md 第 N 行）。
   ```

4. **等用户确认**：
   - "继续" → 按当前阶段的标准流程推进
   - "先看 X 文件" → 打开 X 文件展示给用户

## 硬约束

- ❌ 禁止不读 process.txt 就直接推进（会漏掉关键上下文）
- ❌ 禁止把 4 个文件全部粘到主对话（会污染上下文）
- ✅ 摘要严格 < 200 字
- ✅ 必须等用户确认才开始新动作
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/requirement-session-restorer/
git commit -m "feat(skill): 添加 requirement-session-restorer"
```

---

## Task 4：`requirement-progress-logger` Skill

**Files:**
- Create: `.claude/skills/requirement-progress-logger/SKILL.md`

**Reference:** Spec §6.3

纯指令 Skill，无 reference。Hook 已在 Phase 1 处理自动记录；此 Skill 给 Command 显式调用用。

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: requirement-progress-logger
description: 追加进度日志到 requirements/<id>/process.txt。追加式（append-only），用于关键节点显式记录。Hook 已处理工具级自动记录，此 Skill 用于阶段切换、评审结论等语义级事件。
---

## 什么时候用

- `/requirement:save` 命令调用
- 阶段切换完成后（由 `managing-requirement-lifecycle` 调用）
- 评审结论产生后（由 `requirement-quality-reviewer` 等 Agent 间接触发）
- 用户主动说"记录一下 [事件]"

## 核心流程

1. **定位 `requirements/<id>/process.txt`**：
   - 从 meta.yaml 的 branch 匹配当前分支
   - 或从上下文中的需求 ID

2. **格式化日志行**：
   ```
   ISO8601 [phase] 事件描述
   ```
   例：
   ```
   2026-04-20T11:02:08Z [review:pending] requirement-quality-reviewer 结论 needs_revision（3 条 major）
   2026-04-20T11:16:00Z [phase-transition] definition → tech-research
   ```

3. **追加到文件末尾**（**绝不覆盖**）

## 硬约束

- ❌ 禁止覆盖写入（只能 `>>` append）
- ❌ 禁止缺 ISO8601 时间戳
- ✅ `phase` 字段必须与 `meta.yaml.phase` 一致（阶段切换时单次例外：写 `phase-transition`）
- ✅ 每行一条事件，事件描述 < 100 字符

## 已知场景标签

- `[phase-transition]` — 阶段切换
- `[review:<result>]` — 评审结论（result = approved/needs_revision/rejected）
- `[gate:<pass|fail>]` — 门禁检查结果
- `[SESSION_END]` — 会话结束（Hook 自动写）
- `[tool=<名>]` — 工具级自动日志（Hook 自动写）
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/requirement-progress-logger/
git commit -m "feat(skill): 添加 requirement-progress-logger"
```

---

## Task 5：`task-context-builder` Skill

**Files:**
- Create: `.claude/skills/task-context-builder/SKILL.md`
- Create: `.claude/skills/task-context-builder/reference/extract-rules.md`

**Reference:** Spec §5.4

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: task-context-builder
description: 阶段 7 开发实施时，为单个 feature_id 构建精准的开发上下文——从 features.json、detailed-design.md、相关代码中按规则提取关键信息，避免把整份设计塞给 AI 导致走神。
---

## 什么时候用

阶段 7（开发实施）中，开发者开始做某个 feature_id 时。

## 核心流程

1. **读取输入**：feature_id（来自 features.json 或用户指定）
2. **三源提取**（按 `reference/extract-rules.md` 规则）：
   - `artifacts/features.json` → 该 feature 的 title、description、接口清单
   - `artifacts/detailed-design.md` → 匹配 feature_id 的设计段落（用 `@feature:id` 锚点或标题匹配）
   - 代码库 → 该 feature 可能触及的文件（通过 grep 接口名/数据结构）
3. **输出精简上下文**：
   - 目标：Agent 开发该 feature 所需的所有信息
   - 非目标：整份设计文档、整个代码库结构

## 硬约束

- ❌ 禁止提取与当前 feature_id 无关的内容（会浪费上下文）
- ❌ 禁止直接把大文件整段拉进主对话
- ✅ 摘要总长 < 3000 token（主 Agent 主对话预算的一部分）
- ✅ 所有引用带文件路径+行号，方便 Agent 按需深入

## 参考资源

- [`reference/extract-rules.md`](reference/extract-rules.md) — 提取规则与示例
```

- [ ] **Step 2: Create reference/extract-rules.md**

```markdown
# 提取规则

## 从 features.json 提取

JSON 结构约定：
```json
{
  "features": [
    {
      "id": "F-001",
      "title": "用户注册",
      "description": "支持邮箱+密码注册，自动发送验证邮件",
      "interfaces": [
        {"name": "POST /api/users", "schema_ref": "detailed-design.md#user-create-api"}
      ],
      "dependencies": ["email-service"],
      "notes": "邮件模板和 email-service 对齐"
    }
  ]
}
```

提取：`features.json` 中 `id == feature_id` 的那条完整对象（JSON stringify 即可）。

## 从 detailed-design.md 提取

匹配规则（优先级降序）：

1. HTML 锚点匹配：`schema_ref` 中的 `#xxx` 部分 → grep `<a id="xxx">` 或 `{#xxx}`
2. 标题匹配：查找包含 feature_id 的章节标题（如 `## F-001: 用户注册`）
3. 注释匹配：`<!-- @feature:F-001 -->` 块

提取整个段落（直到下一个同级标题）。

## 从代码库提取

**仅在开发阶段需要时**提取：

- grep 接口路径（如 `/api/users`）的现有实现
- grep 数据结构名（如 `UserCreateRequest`）
- `features.json` 的 `dependencies` 字段列出的模块

**不要**：

- 全量 `ls` 代码目录
- 读整个大文件

## 输出格式

```markdown
# F-001 · 用户注册 — 开发上下文

## 需求描述

支持邮箱+密码注册，自动发送验证邮件。

## 接口

### POST /api/users

- 请求：`UserCreateRequest { email, password }`
- 响应：`UserCreateResponse { id, verificationSent }`
- 设计详情：see `artifacts/detailed-design.md:L120-L145`

## 依赖模块

- `email-service` — 邮件发送（已有接口 `SendEmail(template, to, data)`）

## 相关现有代码

- 用户实体：`src/entity/User.java:15`
- 邮箱验证旧流程（参考）：`src/service/EmailVerifier.java:88`

## 注意事项

邮件模板和 email-service 对齐（来自 features.json.notes）
```
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/task-context-builder/
git commit -m "feat(skill): 添加 task-context-builder"
```

---

## Task 6：`code-review-prepare` Skill

**Files:**
- Create: `.claude/skills/code-review-prepare/SKILL.md`
- Create: `.claude/skills/code-review-prepare/reference/scope-schema.md`

**Reference:** Spec §5.2

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: code-review-prepare
description: /code-review 的预检 Skill。识别审查模式（独立/嵌入）、确定范围、取 diff，生成 .review-scope.json 供并行 checker 消费。
---

## 什么时候用

用户触发 `/code-review` 或 `feature-lifecycle-manager` 在 feature 完成时自动调用。

## 核心流程

1. **识别模式**：
   - **嵌入模式**：当前分支在某个 `requirements/*/meta.yaml.branch` 中 → 从 `meta.yaml.services` 取服务列表
   - **独立模式**：否则 → 审当前分支 vs `main` 的增量

2. **取增量 diff**：
   - 嵌入：`git diff main...HEAD -- <services>`
   - 独立：`git diff main...HEAD`

3. **统计增量规模**：
   - 修改文件数
   - 增加/删除行数
   - 涉及的顶级目录

4. **写 `.review-scope.json`**（根目录，`.gitignore` 已覆盖）：
   按 `reference/scope-schema.md` 的 schema。

5. **输出预检摘要给用户**：模式、范围、增量规模，确认继续后触发并行审查。

## 硬约束

- ❌ 禁止审查超过 2000 行的 diff（建议用户先拆小）
- ❌ 禁止审查未提交的 uncommitted 变化（必须先 commit 到当前分支）
- ✅ `.review-scope.json` 必须合法 JSON（预检阶段 `python3 -m json.tool` 验证）
- ✅ 独立模式必须输出"当前在独立模式，审查范围为 X"告知用户

## 参考资源

- [`reference/scope-schema.md`](reference/scope-schema.md) — ReviewScope JSON schema
```

- [ ] **Step 2: Create reference/scope-schema.md**

```markdown
# ReviewScope JSON Schema

路径：项目根目录 `.review-scope.json`（运行时临时文件）

## Schema

```json
{
  "mode": "embedded" | "standalone",
  "requirement_id": "REQ-2026-001",
  "feature_id": "F-001",
  "base_sha": "abc1234",
  "head_sha": "def5678",
  "base_branch": "main",
  "current_branch": "feat/req-2026-001",
  "services": ["service-a", "service-b"],
  "stats": {
    "files_changed": 12,
    "insertions": 320,
    "deletions": 45
  },
  "diff_summary": "path/to/file1.go (+12 -3)\npath/to/file2.java (+200 -0)",
  "timestamp": "2026-04-20T15:30:00Z"
}
```

## 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| mode | 是 | embedded / standalone |
| requirement_id | 嵌入模式必填 | 当前需求 ID |
| feature_id | 嵌入+逐 feature 模式可填 | 限定单个 feature 范围 |
| base_sha / head_sha | 是 | Git SHA |
| base_branch | 是 | 对比基线，默认 `main` |
| current_branch | 是 | 当前分支 |
| services | 嵌入模式必填 | 涉及的服务仓库/目录 |
| stats | 是 | diff 统计 |
| diff_summary | 是 | 文件列表+增量（供 checker 快速扫） |

## 生成命令示例

```bash
python3 <<'EOF'
import json, subprocess, os
from datetime import datetime, timezone

base = "main"
head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
base_sha = subprocess.check_output(["git", "rev-parse", base], text=True).strip()
branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()

stat = subprocess.check_output(["git", "diff", "--shortstat", f"{base}...HEAD"], text=True)
diff = subprocess.check_output(["git", "diff", "--stat", f"{base}...HEAD"], text=True)

scope = {
    "mode": "standalone",
    "base_sha": base_sha,
    "head_sha": head_sha,
    "base_branch": base,
    "current_branch": branch,
    "services": [],
    "stats": {"raw": stat.strip()},
    "diff_summary": diff.strip(),
    "timestamp": datetime.now(timezone.utc).isoformat()
}
with open(".review-scope.json", "w") as f:
    json.dump(scope, f, indent=2, ensure_ascii=False)
print(f".review-scope.json written ({scope['stats']['raw']})")
EOF
```
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/code-review-prepare/
git commit -m "feat(skill): 添加 code-review-prepare"
```

---

## Task 7：`code-review-report` Skill

**Files:**
- Create: `.claude/skills/code-review-report/SKILL.md`
- Create: `.claude/skills/code-review-report/templates/review-report.md.tmpl`

**Reference:** Spec §5.2 / §5.4

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: code-review-report
description: 聚合 7 个专项 checker + code-quality-reviewer 的输出，生成统一 Markdown 审查报告，按严重度分类归档。
---

## 什么时候用

由主 Agent 在收到所有 checker + 综合 reviewer 结果后自动调用。

## 核心流程

1. **收集输入**：
   - 7 份 checker 输出（design-consistency / security / concurrency / complexity / error-handling / auxiliary-spec / performance）
   - 1 份综合裁决（code-quality-reviewer）
   - `.review-scope.json`（范围元信息）

2. **合并 issue**：
   - 同一行同一问题 → 合并（保留原始 checker 来源作为 tags）
   - 按严重度分层：critical / major / minor

3. **应用综合裁决结论**：approved / needs_revision / rejected

4. **生成报告**：用 `templates/review-report.md.tmpl`

5. **写入文件**：
   - 嵌入模式：`requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`
   - 独立模式：`/tmp/code-review-YYYYMMDD-HHMMSS.md`

6. **主对话输出**：只粘结论行 + critical 问题列表，其余链接到报告文件

## 硬约束

- ❌ 禁止把完整报告粘到主对话（只粘结论+critical）
- ❌ 禁止遗漏 checker（所有 7 份都要合并，缺失的标记 `⚠️ 未运行`）
- ✅ 报告必须带时间戳（文件名中）
- ✅ 每个 issue 必须有 `file:line` 引用

## 参考资源

- [`templates/review-report.md.tmpl`](templates/review-report.md.tmpl) — 报告模板
```

- [ ] **Step 2: Create templates/review-report.md.tmpl**

```markdown
# 代码审查报告 · __REQ_ID__ · __TIMESTAMP__

## 结论

**__CONCLUSION__** · __N_CRIT__ critical / __N_MAJ__ major / __N_MIN__ minor

- `approved` — 可合入
- `needs_revision` — 需修改后复审
- `rejected` — 驳回，方向性问题

## Critical（必须修复）

### [__tag__] __file__:__line__

__description__

**建议**：__suggestion__

## Major（强烈建议修复）

### [__tag__] __file__:__line__

...

## Minor（改进建议）

### [__tag__] __file__:__line__

...

## 未运行的 checker（如有）

- ⚠️ __checker_name__（原因：__reason__）

## 审查元信息

- **审查范围**：__scope_summary__（__files_changed__ 文件，+__ins__ -__del__ 行）
- **并行 checker**：__n_checkers__，总耗时 __elapsed__s
- **综合模型**：__quality_reviewer_model__
- **Base SHA**：__base_sha__
- **Head SHA**：__head_sha__
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/code-review-report/
git commit -m "feat(skill): 添加 code-review-report"
```

---

## Task 8：`traceability-gate-checker` Skill

**Files:**
- Create: `.claude/skills/traceability-gate-checker/SKILL.md`

**Reference:** Spec §4.3 / §4.2

纯指令 Skill。Phase 2 阶段只做静态检查；Phase 3 后调用 `traceability-consistency-checker` Agent 做深度检查。

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: traceability-gate-checker
description: 测试阶段切换前的追溯链门禁——校验需求→设计→代码→测试链完整。Phase 2 先做静态检查，Phase 3 后调用 traceability-consistency-checker Agent 做深度校验。
---

## 什么时候用

由 `managing-requirement-lifecycle` 在切换到 `testing` 阶段之前自动调用。

## 核心流程（Phase 2 静态检查版）

1. **读 `features.json`**，列出所有 feature_id
2. **对每个 feature_id，检查**：
   - **出现在 `detailed-design.md`**（grep `@feature:<id>` 或章节标题匹配）
   - **出现在代码变更中**（grep `@feature:<id>` 注解 / commit 消息 / branch 历史）
   - **出现在 `test-report.md`**（每个 feature 至少 1 个测试用例）
3. **收集缺口**：哪些 feature_id 在哪环缺失
4. **输出结论**：
   - 全链完整 → `PASS`，允许进入测试阶段
   - 任一环缺失 → `FAIL`，列出具体缺口 + 阻止切换

## 核心流程（Phase 3 增强版）

上述基础上，调用 `traceability-consistency-checker` Agent 做语义级深度校验：

- 同名接口在设计和代码中的签名一致性
- 测试用例是否覆盖了设计中的所有分支
- 变更范围是否偏离了需求描述

调用方式（Phase 3 起可用）：
```
Task tool (subagent_type=traceability-consistency-checker):
  input: {
    requirement_id: "REQ-001",
    features_json_path: "requirements/REQ-001/artifacts/features.json"
  }
```

## 硬约束

- ❌ 禁止在任一环缺失时输出 PASS
- ❌ 禁止放宽规则（"差不多就行"）
- ✅ FAIL 必须列出具体的缺失 feature_id + 缺失位置（设计/代码/测试）
- ✅ Phase 2 阶段如无法深度校验，输出 "static-pass (deep check pending Phase 3 agent)"

## 输出格式

```
结论: PASS | FAIL | static-pass
缺口（FAIL 时）:
  - F-001: 未在代码中出现 @feature:F-001
  - F-003: 未在 test-report.md 中找到测试用例
```
```

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/traceability-gate-checker/
git commit -m "feat(skill): 添加 traceability-gate-checker（Phase 2 静态版）"
```

---

## Task 9：`feature-lifecycle-manager` Skill

**Files:**
- Create: `.claude/skills/feature-lifecycle-manager/SKILL.md`
- Create: `.claude/skills/feature-lifecycle-manager/reference/feature-states.md`
- Create: `.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl`

**Reference:** Spec §4.1（阶段 6）

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: feature-lifecycle-manager
description: 阶段 6（任务规划）拆分 features.json 为功能点任务；阶段 7（开发实施）管理每个 feature_id 的状态流转（pending → in-progress → done）。Done 转换时触发 /code-review scoped 到该 feature。
---

## 什么时候用

- **阶段 6**：用户进入任务规划阶段，或说"拆分功能点"时
- **阶段 7**：用户说"F-xxx 开始做 / F-xxx 完成了"时

## 核心流程

### 阶段 6：任务拆分

1. 读 `artifacts/features.json`
2. 对每个 feature_id，基于 `templates/feature-task.md.tmpl` 生成 `artifacts/tasks/<id>.md`，状态初始化为 `pending`
3. 更新 `meta.yaml` 切阶段到 `task-planning` 完成状态

### 阶段 7：feature 生命周期

状态流转（严格，见 `reference/feature-states.md`）：

```
pending → in-progress → done
```

**完成触发**：

当用户说 "F-xxx 完成"：
1. 调 `task-context-builder` 确认当前 feature 代码已 commit
2. 触发 `/code-review` scope = 该 feature
3. 审查结果：
   - `approved` → 更新 task 文件 status 到 `done`，记录 review 报告路径
   - `needs_revision` / `rejected` → status 保持 `in-progress`，通知用户修改

## 硬约束

- ❌ 禁止跳过状态（不允许 pending 直接 done）
- ❌ 禁止在 `done` 后再退回（如需修改，走 `/requirement:rollback`）
- ✅ 每个 task 文件必须有 `status`、`created_at`、`updated_at` 字段
- ✅ `done` 必须附代码审查报告路径

## 参考资源

- [`reference/feature-states.md`](reference/feature-states.md) — 状态定义与流转
- [`templates/feature-task.md.tmpl`](templates/feature-task.md.tmpl) — 任务文件模板
```

- [ ] **Step 2: Create reference/feature-states.md**

```markdown
# Feature 状态定义

## 状态枚举

| 状态 | 含义 | 进入条件 |
|---|---|---|
| `pending` | 尚未开始 | 阶段 6 拆分时默认 |
| `in-progress` | 开发中 | 用户明确开始（或开始 commit 涉及该 feature 的代码） |
| `done` | 已完成且过审 | 代码 commit + /code-review approved |

## 合法流转

```
pending ──开始开发──→ in-progress ──审查通过──→ done
               │                     │
               └──（不可逆回退）────────┘
```

不允许：
- `pending` 直接到 `done`
- `done` 回退到 `in-progress`（需走 `/requirement:rollback`）
- `pending` 跳到 `in-progress` 但无代码变更（至少要有一次提及该 feature_id 的 commit）

## task 文件 frontmatter

```yaml
---
feature_id: F-001
title: 用户注册
status: pending
created_at: 2026-04-20T10:00:00Z
updated_at: 2026-04-20T10:00:00Z
review_report: null   # done 时填 artifacts/review-*.md 路径
---
```

## 状态变更时同步动作

| 变更 | 同步动作 |
|---|---|
| → `in-progress` | 更新 `updated_at`；写 `process.txt` [development] F-001 开始 |
| → `done` | 更新 `updated_at` + 填 `review_report`；写 `process.txt` [development] F-001 完成（review: xxx.md） |
```

- [ ] **Step 3: Create templates/feature-task.md.tmpl**

```markdown
---
feature_id: __FEATURE_ID__
title: __TITLE__
status: pending
created_at: __ISO8601__
updated_at: __ISO8601__
review_report: null
---

# __FEATURE_ID__ · __TITLE__

## 需求描述

（从 features.json 的 description 复制）

## 接口/数据结构

（从 features.json 的 interfaces 复制）

## 依赖

（从 features.json 的 dependencies 复制）

## 开发笔记

（开发过程中随手记）

## 完成自检

- [ ] 接口实现符合详细设计
- [ ] 单元测试覆盖主流程
- [ ] 边界条件处理
- [ ] 无明显安全/并发问题
- [ ] `/code-review` 通过
```

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/feature-lifecycle-manager/
git commit -m "feat(skill): 添加 feature-lifecycle-manager"
```

---

## Task 10：`managing-knowledge` Skill（伞形）

**Files:**
- Create: `.claude/skills/managing-knowledge/SKILL.md`
- Create: `.claude/skills/managing-knowledge/reference/extract-experience.md`
- Create: `.claude/skills/managing-knowledge/reference/generate-sop.md`
- Create: `.claude/skills/managing-knowledge/reference/generate-checklist.md`
- Create: `.claude/skills/managing-knowledge/reference/optimize-doc.md`
- Create: `.claude/skills/managing-knowledge/reference/organize-index.md`

**Reference:** Spec §5.3

- [ ] **Step 1: Create SKILL.md**

```markdown
---
name: managing-knowledge
description: 知识管理伞形 Skill，5 个 /knowledge:* 命令共用。根据子意图（extract-experience / generate-sop / generate-checklist / optimize-doc / organize-index）分发到对应 reference/ 文件的规则执行。
---

## 什么时候用

用户触发 5 个 `/knowledge:*` 命令之一，或口头说"提炼经验 / 生成 SOP / 生成检查清单 / 优化文档 / 整理索引"时。

## 核心流程

1. **识别子意图**（5 选 1）
2. **加载对应规则**：`reference/<sub>.md`
3. **执行规则**：每个 sub 的流程不同，见对应 reference
4. **输出候选产物**（渐进式：先给结构+几条样例，等用户确认再出完整内容）
5. **确认后落盘**：写入 `context/project/` 或 `context/team/experience/`

## 硬约束

- ❌ 禁止跳过"渐进式确认"直接写文件
- ❌ 禁止沉淀不满足"三必要条件"的内容（见 `compounding.md`）
- ✅ 每次沉淀都要问：跨需求重复？AI 反复错？跨会话需保留？— 至少满足一条
- ✅ 新写的文件必须更新对应 `INDEX.md`

## 参考资源（按子命令）

- [`reference/extract-experience.md`](reference/extract-experience.md) — 从 notes.md 提取经验
- [`reference/generate-sop.md`](reference/generate-sop.md) — 从实践生成 SOP
- [`reference/generate-checklist.md`](reference/generate-checklist.md) — 生成检查清单
- [`reference/optimize-doc.md`](reference/optimize-doc.md) — 优化已有文档
- [`reference/organize-index.md`](reference/organize-index.md) — 整理目录索引
```

- [ ] **Step 2: Create reference/extract-experience.md**

```markdown
# 从 notes.md 提取经验

## 输入

- `requirements/<id>/notes.md`（或指定 notes 文件）

## 步骤

1. **扫描 notes.md**，找出"踩坑/教训/发现"类条目
2. **对每条候选**，按三必要条件评估：
   - 跨需求会重复出现？
   - AI 反复犯此类错？
   - 跨会话/跨人需要保留？
3. **至少满足一条**才进入候选清单
4. **输出候选清单**给用户：
   ```
   候选经验（N 条）：
   1. <标题> [满足条件：A/B/C] — 简要描述
   2. ...
   ```
5. **用户确认要沉淀哪几条**
6. **对每条，决定归属**：
   - 项目特有 → `context/project/<X>/experience/<slug>.md`
   - 跨项目 → `context/team/experience/<slug>.md`
7. **写文件**（格式见下）
8. **更新对应 INDEX.md**

## 文件格式

```markdown
# <标题>

**沉淀原因**：满足 A / B / C（至少一条）

## 问题

（场景描述，< 100 字）

## 根因

（< 100 字）

## 解法

（具体操作或规范，< 100 字）

## 验证方法

（如何确认问题不再出现）

## 引用来源

- `requirements/<id>/notes.md:<行号>`
```

## 反例（不应沉淀）

- 偶发问题（只发生过一次且无再现风险）
- 纯常识
- 只与当前需求相关、无复用价值
```

- [ ] **Step 3: Create reference/generate-sop.md**

```markdown
# 生成 SOP

## 输入

- 用户指定的"目标场景"（如"线上紧急修复流程"、"新 MCP 接入流程"）
- `requirements/*/notes.md` 或 `context/team/experience/` 中的相关实践

## 步骤

1. **收集相关实践**：grep 涉及场景的 notes/experience
2. **识别通用步骤**：出现 ≥ 2 次的操作
3. **识别变化点**：各实践中不同的部分 → 决策点
4. **起草 SOP 结构**：
   ```
   # <场景名> SOP

   ## 触发条件
   ## 前置检查
   ## 主流程
   步骤 1 → 步骤 2 → ... → 步骤 N
   ## 决策点
   ## 完成标准
   ```
5. **先输出结构+几个关键步骤**给用户确认
6. **用户确认后**，写入 `context/team/engineering-spec/sop/<slug>.md`（或 `context/team/experience/`，视适用范围）
7. **更新对应 INDEX.md**

## 硬约束

- SOP 必须包含"完成标准"（可验证的结束条件）
- 步骤必须是可执行的祈使句
- 禁止写成"应该考虑 X"之类的模糊建议
```

- [ ] **Step 4: Create reference/generate-checklist.md**

```markdown
# 生成检查清单

## 输入

- 用户指定的"目标场景"（如"发版前检查"、"PR 评审清单"）
- 相关实践文档

## 步骤

1. **收集失败案例**：过去发版/PR 中漏掉的检查点
2. **归并去重**：相同检查合并
3. **按严重度分组**：
   - Blocker（不过即拒）
   - Must（强烈建议）
   - Nice-to-have
4. **起草清单结构**
5. **先输出 3-5 条关键项**给用户确认
6. **用户确认后**，写 `context/team/checklists/<slug>.md`

## 输出格式

```markdown
# <场景名> 检查清单

## Blocker

- [ ] 项 1（配套说明：违反时典型后果）
- [ ] 项 2

## Must

- [ ] 项 1
- [ ] 项 2

## Nice-to-have

- [ ] 项 1
```

## 硬约束

- 每条检查项必须是可验证的（有明确的"如何验证"方式）
- 禁止写含糊项如"代码风格良好"——要具体到"函数 < 60 行"
```

- [ ] **Step 5: Create reference/optimize-doc.md**

```markdown
# 优化已有文档

## 触发

用户指定某份文档（路径），要求优化结构/可读性。

## 步骤

1. **读目标文档**，分析现状：
   - 结构层级是否清晰？
   - 是否有冗余？
   - 关键信息是否一跳可达？
2. **识别问题清单**（3-5 条）
3. **输出问题清单给用户**，每条说明：
   - 现状
   - 建议
   - 影响范围（会修改的章节）
4. **用户确认要优化哪几条**
5. **实施优化**：
   - 保持核心信息不变
   - 改动要明显标注（文档末尾加"最近优化记录"）
6. **更新 INDEX.md**（如果标题/锚点变了）

## 硬约束

- ❌ 禁止未经用户确认就大改结构
- ❌ 禁止删除有外部引用的锚点（先检查 grep 其他文件是否引用了本文档）
- ✅ 每次优化留下 diff 说明
```

- [ ] **Step 6: Create reference/organize-index.md**

```markdown
# 整理目录索引

## 触发

用户说"整理 context/ 索引"，或某个 INDEX.md 内容和目录实际不符时。

## 步骤

1. **定位目标 INDEX.md**（用户指定或默认当前所在目录的）
2. **扫描同级 + 下一级文件**
3. **对比 INDEX.md 与实际文件**：
   - 实际存在但 INDEX 未列 → 遗漏
   - INDEX 列了但文件不存在 → 腐化
   - 文件重命名导致链接失效 → 腐化
4. **输出 diff 报告**
5. **用户确认后**，修正 INDEX.md

## 硬约束

- ❌ 禁止自动删除 INDEX 里的条目（可能有故意保留的"未来占位"）
- ✅ 修正前必须让用户确认
- ✅ 对每个新增/删除条目写一句理由
```

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/managing-knowledge/
git commit -m "feat(skill): 添加 managing-knowledge 伞形 + 5 份子规则"
```

---

## Task 11：Phase 2a 整体验证

**Files:**
- Modify: `context/team/engineering-spec/plans/README.md`（更新 Phase 2a 状态）

- [ ] **Step 1: 文件结构核查**

```bash
echo "=== Skill 目录数 ==="
find .claude/skills -maxdepth 1 -mindepth 1 -type d | wc -l
# 期望：10

echo "=== 每个 Skill 的 SKILL.md 存在 ==="
for d in .claude/skills/*/; do
    if [ -f "${d}SKILL.md" ]; then
        echo "✓ ${d}SKILL.md"
    else
        echo "✗ ${d}SKILL.md 缺失"
    fi
done
# 期望：10 个 ✓
```

- [ ] **Step 2: SKILL.md 字数校验（硬约束 < 2k token ≈ < 700 汉字）**

```bash
echo "=== SKILL.md 字数（建议 < 2000 字符 ≈ < 700 中文字） ==="
for f in .claude/skills/*/SKILL.md; do
    size=$(wc -c < "$f")
    if [ "$size" -gt 2500 ]; then
        echo "⚠️  $f = $size 字符（超标）"
    else
        echo "✓  $f = $size 字符"
    fi
done
```

如任一 SKILL.md 超标，回看是否应把内容移到 reference/。

- [ ] **Step 3: 引用完整性**

```bash
# 每个 SKILL.md 里提到的 reference/* 和 templates/* 必须存在
for f in .claude/skills/*/SKILL.md; do
    dir=$(dirname "$f")
    grep -oE '\[`[^`]+`\]\(([^)]+)\)' "$f" | grep -oE '\([^)]+\)' | tr -d '()' | while read ref; do
        if [ -f "$dir/$ref" ]; then
            echo "✓ $dir/$ref"
        else
            echo "✗ $f 引用 $ref 但不存在"
        fi
    done
done
```

所有引用必须为 ✓。

- [ ] **Step 4: 更新 plans/README.md**

修改第二张表格，把 Phase 2 拆分为 2a / 2b 并标记状态：

```markdown
| Phase | 范围 | Plan 文档 | 状态 |
|---|---|---|---|
| 1 | 基础设施 + 上下文文档 | [phase-1-foundation](./2026-04-20-phase-1-foundation.md) | ✅ 已完成 |
| 2a | 10 Skill（伞形 + 专项） | [phase-2a-skills](./2026-04-20-phase-2a-skills.md) | ✅ 已完成 |
| 2b | 16 Command + 集成验证 | 待 Phase 2a 完成后撰写 | ⏸ 未开始 |
| 3 | 20 Agent | 待 Phase 2b 完成后撰写 | ⏸ 未开始 |
| 4 | 集成验收 + 示例需求跑通 | 待 Phase 3 完成后撰写 | ⏸ 未开始 |
```

- [ ] **Step 5: 最终 commit**

```bash
git add context/team/engineering-spec/plans/README.md
git commit -m "docs(plan): Phase 2a 状态改为已完成"
```

- [ ] **Step 6: Phase 2a 最终 git log**

```bash
git log --oneline | head -15
```

应看到最后 ~11 个 commit 对应 Task 1-11。

---

## Phase 2a 完成检查清单

- [ ] 10 个 Skill 目录均创建
- [ ] 10 个 SKILL.md 均 < 2500 字符
- [ ] 全部 reference / templates / scripts 按 SKILL.md 引用齐备
- [ ] 每个 Skill 独立一个 commit
- [ ] 全部引用路径正确（Step 3 校验通过）
- [ ] `plans/README.md` 状态已更新

## Phase 2b 预览

Phase 2b 将实现：
- 16 个 Command（`.claude/commands/**/*.md`）
- `/requirement:*` × 7 / `/knowledge:*` × 5 / `/agentic:*` × 2 / `/code-review` + `/note`
- 集成验证：运行 `/requirement:new` 跑通 bootstrap 阶段

Phase 2b 结束时：可以真正运行一个小需求的前几个阶段（bootstrap → definition → tech-research），Phase 3 补齐后 8 阶段全通。
