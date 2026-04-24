---
title: Agentic Engineering 骨架设计
date: 2026-04-20
status: draft（待用户审阅）
source: 对齐文章《认知重建之后，步入 Agentic Engineering 的工程革命》（腾讯技术工程 rickyshou，2026-03-30）最终成型版
scope: 方案 A（骨架全量重建）· 选项 2（只落地文章明确命名 + 强推断工具）
---

# Agentic Engineering 骨架设计

## 0. 元信息与目标

### 0.1 目标

在本仓库（`/Users/richardhuang/learnspace/agenticMetaEngineering`）搭建一套对标参考文章最终形态的 Agentic Engineering 工程骨架，供团队通过 `git clone` 获得**开箱即用**的 AI 辅助研发能力。核心交付物包括：

- 8 阶段需求全生命周期管理体系（含强制门禁）
- 多 Agent 并行代码审查能力（8 专项 checker + 1 综合裁决）
- 三层记忆系统（工作记忆 / 溢出区 / 长期记忆）
- 跨会话恢复机制
- 团队落地的 8 阶段学习路径

### 0.2 和文章原版的已确认偏差

| 项 | 文章原版 | 本骨架 | 理由 |
|---|---|---|---|
| 根入口文件 | `AGENTS.md` | `CLAUDE.md` | 用户确认：只用 Claude Code |
| CLI 扩展目录 | `.codebuddy/` | `.claude/` | 用户确认：只用 Claude Code，不兼容 CodeBuddy |
| 内部 MCP（TAPD / iWiki / 企微 / QTA） | 开箱即用 | 注释占位，留接口 | 腾讯内部能力无法外部复现 |
| 业务 Skill（如 `config-gen-engine`） | 基于活动配置业务 | 不建，留未实现清单 | 无对应业务 |
| Skill / Agent 数量 | 27 / 22 | 10 / 20 | 选项 2：只落地有依据的工具，缺口等真问题驱动 |
| Command 数量 | 28 | 16 | 同上 |

### 0.3 工具数量最终版

- Command：**16** 个（文章明确命名 + 命名空间齐全）
- Skill：**10** 个（9 个文章明确 + 1 个强推断）
- Agent：**20** 个（所有来自文章 5.1 图表、5.2 架构描述、5.3 / 5.4 正文）

---

## 1. 核心原则

### 1.1 四条硬原则（写入 `CLAUDE.md` 根索引）

1. **文档即记忆**
   人和 AI 读同一份 Markdown。不维护给 AI 的向量库，不维护给人的 Wiki。`context/**` 和 `requirements/**` 同时是人类阅读材料和 Agent 检索材料。

2. **位置即语义**
   文件放在哪个目录，Agent 就知道它是什么。不使用元数据标签、不使用外部索引系统。路径本身承载分类信息。

3. **渐进式披露（Agentic Search）**
   `CLAUDE.md` 和所有 `SKILL.md` 都必须轻量（< 2k token），作为入口；详细知识放 `reference/` 下，按需检索。这是文章 3.5 节推翻场景路由后得出的核心教训——**推送规范 → 拉取工具**。

4. **工具封装知识，而非脚本步骤**
   Skill 给 Agent 的是"做什么 + 注意什么"，不是"第一步…第二步…"。把 Agent 当有判断力的同事，不是当 shell 脚本。

### 1.2 三层顶层架构

```
团队智能体层  (.claude/agents/, .claude/skills/, .claude/commands/)
    ↓ 消费
平台能力层    (Claude Code 原生: Command / Skill / Subagent / Hook / MCP)
    ↓ 基于
基础设施层    (git 仓库 / 文件系统 / 外部 MCP)
```

### 1.3 明确不做的事（关键负向约束）

| 不做 | 理由 |
|---|---|
| 场景路由系统 | 文章 3.5 明确推翻；用 Claude Code 原生 Skill / Command 自动匹配替代 |
| 一次性全量规范 | 文章 9.2 反思的"规范膨胀"——骨架只含有依据的内容，缺口留 TODO |
| AGENTS.md 软链 | 用户确认不需要 |
| 根目录 `scripts/` 或 `workspace/` 等额外目录 | 文章 3.2 "位置即语义"；不新增未被明确语义化的目录 |
| 双 CLI 兼容（CodeBuddy + Claude Code） | 用户确认只用 Claude Code |

---

## 2. 完整目录结构

```
agenticMetaEngineering/
│
├── CLAUDE.md                          # 根入口 · 项目级 Claude Code 指令（< 200 行）
├── README.md                          # 面向团队的介绍与 Quick Start
├── .gitignore
│
├── .claude/                           # Claude Code 原生扩展目录
│   ├── settings.json                  # 项目级配置
│   ├── settings.local.json.example    # 个人覆盖模板（真本体进 .gitignore）
│   ├── agents/                        # 20 个 Subagent 定义（.md）
│   ├── skills/                        # 10 个 Skill（每个一个目录）
│   │   └── <skill-name>/
│   │       ├── SKILL.md               # 入口 < 2k token
│   │       ├── reference/             # 详细参考（按需读）
│   │       ├── templates/             # 模板文件
│   │       └── scripts/               # 可执行脚本
│   ├── commands/                      # 16 个 Command（薄层 < 100 行）
│   │   ├── requirement/               # 7 个（冒号命名空间）
│   │   ├── knowledge/                 # 5 个
│   │   ├── agentic/                   # 2 个（help / feedback）
│   │   ├── code-review.md
│   │   └── note.md
│   ├── hooks/                         # 3 个 Hook 脚本
│   │   ├── protect-branch.sh
│   │   ├── auto-progress-log.sh
│   │   └── stop-session-save.sh
│   └── statusline.sh
│
├── .mcp.json.example                  # MCP 候选模板（默认不启用；cp 为 .mcp.json 后生效，已 gitignore）
│
├── context/                           # 【长期记忆：知识库】
│   ├── INDEX.md
│   ├── team/                          # 团队通用知识
│   │   ├── INDEX.md
│   │   ├── git-workflow.md
│   │   ├── tool-chain.md
│   │   ├── ai-collaboration.md
│   │   ├── engineering-spec/          # 【体系自身的规范】
│   │   │   ├── INDEX.md
│   │   │   ├── design-guidance/
│   │   │   │   ├── four-layer-hierarchy.md
│   │   │   │   ├── context-engineering.md
│   │   │   │   └── compounding.md
│   │   │   ├── tool-design-spec/
│   │   │   │   ├── command-spec.md
│   │   │   │   ├── skill-spec.md
│   │   │   │   └── subagent-spec.md
│   │   │   ├── iteration-sop.md
│   │   │   └── specs/                 # 设计文档存档（含本文档）
│   │   ├── onboarding/
│   │   │   ├── agentic-engineer-guide.md
│   │   │   └── learning-path/         # 8 阶段学习路径（一次性写完）
│   │   │       ├── 01-environment.md
│   │   │       ├── 02-first-conversation.md
│   │   │       ├── 03-command-skill-agent.md
│   │   │       ├── 04-first-requirement.md
│   │   │       ├── 05-code-review.md
│   │   │       ├── 06-knowledge-sinking.md
│   │   │       ├── 07-custom-command.md
│   │   │       └── 08-custom-skill.md
│   │   ├── rollout/
│   │   │   ├── four-phase-strategy.md
│   │   │   └── embedded-push-playbook.md
│   │   ├── experience/
│   │   │   └── INDEX.md
│   │   └── feedback-log.yaml           # /agentic:feedback 结构化写入
│   └── project/                        # 项目级知识（初始为空）
│       └── INDEX.md
│
└── requirements/                       # 【需求全生命周期产出物 · 入 git】
    ├── INDEX.md
    └── <requirement-id>/
        ├── meta.yaml
        ├── plan.md
        ├── process.txt
        ├── notes.md
        └── artifacts/
            ├── requirement.md
            ├── tech-feasibility.md
            ├── outline-design.md
            ├── detailed-design.md
            ├── features.json
            ├── tasks/
            │   └── <feature-id>.md
            ├── review-YYYYMMDD-HHMMSS.md
            └── test-report.md
```

---

## 3. 三级工具清单

### 3.1 Command 清单（16 个）

全部为薄层（< 100 行），只做预检 + 委托给 Skill。

#### `/requirement:*` 命名空间（7 个）

| Command | 作用 | 委托给 |
|---|---|---|
| `/requirement:new` | 新建需求，自动建分支/目录/骨架 | `managing-requirement-lifecycle` |
| `/requirement:continue` | 从上次中断处恢复上下文 | `managing-requirement-lifecycle` → `requirement-session-restorer` |
| `/requirement:next` | 进入下一阶段，触发门禁检查 | `managing-requirement-lifecycle` |
| `/requirement:save` | 保存进度，为跨会话准备 | `managing-requirement-lifecycle` → `requirement-progress-logger` |
| `/requirement:status` | 查看当前阶段和完成情况 | `managing-requirement-lifecycle` |
| `/requirement:rollback` | 回退阶段，分析影响范围 | `managing-requirement-lifecycle` |
| `/requirement:list` | 查看所有需求状态概览 | `managing-requirement-lifecycle` |

#### `/knowledge:*` 命名空间（5 个）

| Command | 作用 | 委托给 |
|---|---|---|
| `/knowledge:extract-experience` | 从实践中提取可迁移经验 | `managing-knowledge` |
| `/knowledge:generate-sop` | 从实践中生成 SOP | `managing-knowledge` |
| `/knowledge:generate-checklist` | 从实践中生成检查清单 | `managing-knowledge` |
| `/knowledge:optimize-doc` | 优化已有文档结构 | `managing-knowledge` |
| `/knowledge:organize-index` | 整理 `context/` 索引 | `managing-knowledge` |

#### `/agentic:*` 命名空间（2 个）

| Command | 作用 | 委托给 |
|---|---|---|
| `/agentic:help` | 上手引导：MCP 配置、常用流程、FAQ | 自身 < 100 行处理 |
| `/agentic:feedback` | 反馈直达，写入 `context/team/feedback-log.yaml` | 自身处理 |

#### 根命令（2 个）

| Command | 作用 | 委托给 |
|---|---|---|
| `/code-review` | 多 Agent 并行代码审查（详见第 5 节） | `code-review-prepare` → 并行 Agent → `code-review-report` |
| `/note` | 追加到当前需求的 `notes.md` | 自身 < 100 行处理 |

### 3.2 Skill 清单（10 个）

所有 Skill 遵守 `SKILL.md < 2k token` 硬约束，详细知识拆到 `reference/`。

| Skill | 作用 | 内部资源 |
|---|---|---|
| `managing-requirement-lifecycle` | 伞形 Skill，被 7 个 `/requirement:*` 共用；负责意图识别、阶段检查、门禁验证 | `reference/phase-rules.md`（8 阶段规范）`templates/`（需求骨架） |
| `requirement-doc-writer` | 需求文档撰写，核心是"刨根问底"—每条信息必须"有引用 / 待确认 / 待补充" | `reference/sourcing-rules.md` `templates/requirement.md` |
| `requirement-session-restorer` | 跨会话恢复：读 `meta.yaml + process.txt + notes.md + plan.md` | 纯指令 |
| `requirement-progress-logger` | 实时记录进度到 `process.txt` | `reference/log-format.md` |
| `task-context-builder` | 为单个功能点构建开发上下文 | `reference/extract-rules.md` |
| `code-review-prepare` | 代码审查预检：识别需求、定范围、取 diff | `scripts/prepare.sh` |
| `code-review-report` | 代码审查结果汇总 | `templates/review-report.md` |
| `traceability-gate-checker` | 追溯链门禁：调用 `traceability-consistency-checker` Agent 做深度检查 | 纯指令 |
| `feature-lifecycle-manager` | 阶段 6 任务规划 + 阶段 7 功能点生命周期（拆分 / 开发中 / 完成触发 /code-review） | `reference/feature-states.md` |
| `managing-knowledge` | 伞形 Skill，被 5 个 `/knowledge:*` 共用（**强推断：套用 /requirement:* 伞形模式**） | `reference/extraction-rules.md` |

### 3.3 Agent 清单（20 个）

#### 跨阶段通用 Agent（4 个）

| Agent | 作用 | 模型 | 来源 |
|---|---|---|---|
| `universal-context-collector` | 按优先级从 `context/project/` → `context/team/` 检索，禁止盲目搜索 | sonnet（lite） | 文章 5.1 |
| `documentation-batch-updater` | 批量更新 `context/`，识别失效引用 | sonnet | 文章 5.3 |
| `engineering-spec-retriever` | 按需检索规范，减少主 Agent 上下文消耗 | sonnet | 文章 5.3 |
| `engineering-spec-curator` | 维护 `context/team/engineering-spec/` | sonnet | 文章 5.3 |

#### 需求阶段专属 Agent（8 个，对应文章 5.1 图表）

| # | 阶段 | Agent | 模型 |
|---|---|---|---|
| 1 | 初始化 | `requirement-bootstrapper` | sonnet |
| 2 | 需求定义 | `requirement-input-normalizer` | sonnet |
| 2 | 需求定义（评审） | `requirement-quality-reviewer` | opus（strong） |
| 3 | 技术预研 | `tech-feasibility-assessor` | sonnet |
| 4 | 概要设计 | `outline-design-quality-reviewer` | opus |
| 5 | 详细设计 | `detail-design-quality-reviewer` | opus |
| 8 | 测试验收 | `test-runner` | sonnet |
| 8 | 测试验收 | `traceability-consistency-checker` | sonnet |

注：阶段 6 由 Skill `feature-lifecycle-manager` 承担，无专属 Agent。

#### 代码审查 Agent（8 个，对应阶段 7）

| Agent | 维度 | 模型 |
|---|---|---|
| `design-consistency-checker` | 实现 vs 详细设计的偏离 | sonnet |
| `security-checker` | 注入 / 鉴权绕过 / 敏感日志 | sonnet |
| `concurrency-checker` | 竞态 / 幂等 / 锁 | sonnet |
| `complexity-checker` | 方法长度 / 圈复杂度 / 嵌套 | sonnet |
| `error-handling-checker` | 异常吞没 / 日志级别 / 错误码 | sonnet |
| `auxiliary-spec-checker` | 命名 / 注释 / 格式 | sonnet |
| `performance-checker` | 热点 SQL / N+1 / 不必要 IO | sonnet |
| `code-quality-reviewer` | 综合裁决：去重 + 严重度排序 + 最终结论 | opus |

---

## 4. 需求 8 阶段生命周期与门禁

### 4.1 8 阶段定义（对标文章 5.1 图表）

| # | 阶段 | 英文标识（`meta.yaml` 用） | 做什么 | 关键 Agent / Skill | 产出 |
|---|---|---|---|---|---|
| 1 | 初始化 | `bootstrap` | 命名、建分支、建目录 | Agent `requirement-bootstrapper` | 目录骨架 + `meta.yaml` |
| 2 | 需求定义 | `definition` | 输入清洗、上下文收集、文档撰写、评审 | Agent `requirement-input-normalizer` + `requirement-quality-reviewer` + Skill `requirement-doc-writer` | `requirement.md` + 评审报告 |
| 3 | 技术预研 | `tech-research` | 可行性评估、风险预判 | Agent `tech-feasibility-assessor` | `tech-feasibility.md` |
| 4 | 概要设计 | `outline-design` | 架构方案、模块划分、评审 | Agent `outline-design-quality-reviewer` | `outline-design.md` + 评审报告 |
| 5 | 详细设计 | `detail-design` | 接口签名、数据结构、时序图、评审 | Agent `detail-design-quality-reviewer` | `detailed-design.md` + `features.json` + 评审报告 |
| 6 | 任务规划 | `task-planning` | 功能点拆分、进入开发门禁 | Skill `feature-lifecycle-manager` + `task-context-builder` | `tasks/<feature-id>.md`（每点一份） |
| 7 | 开发实施 | `development` | 编码、代码审查、提交 | Agent `code-quality-reviewer` + 8 专项 checker | 代码 + 审查报告 |
| 8 | 测试验收 | `testing` | 测试用例生成、执行、追溯链校验 | Agent `test-runner` + `traceability-consistency-checker` | `test-report.md` + 追溯链报告 |

### 4.2 阶段门禁（强制）

```
[1 bootstrap] ──  目录骨架 + meta.yaml 合法 ──→ [2 definition]
[2 definition] ── requirement-quality-reviewer 非 rejected ──→ [3 tech-research]
[3 tech-research] ── tech-feasibility.md 存在且风险已评估 ──→ [4 outline-design]
[4 outline-design] ── outline-design-quality-reviewer 非 rejected ──→ [5 detail-design]
[5 detail-design] ── detail-design-quality-reviewer 非 rejected + features.json 合法 ──→ [6 task-planning]
[6 task-planning] ── tasks/ 每 feature 有文件 ──→ [7 development]
[7 development] ── 每功能点 /code-review 通过 + 所有代码已提交 ──→ [8 testing]
[8 testing] ── traceability-gate-checker Skill PASS（调用 Agent 深度校验） ──→ [结束]
```

**两个最硬门禁**：
- 进入阶段 7 前：需 `detail-design-quality-reviewer` 非 rejected
- 进入阶段 8 前：需 `traceability-gate-checker` 通过

### 4.3 追溯链机制

```
artifacts/requirement.md
    ↓ 被引用于（frontmatter: refs-requirement）
artifacts/outline-design.md
    ↓ 被引用于
artifacts/detailed-design.md → features.json（每 feature 有 id）
    ↓ feature_id 出现在
代码变更（commit 消息或代码注释中的 @feature:xxx）
    ↓ feature_id 出现在
artifacts/test-report.md（每 feature 有测试用例）
```

校验链路：`traceability-gate-checker` Skill → 调用 `traceability-consistency-checker` Agent 做深度检查 → 任一环节缺失 → 阻止进入阶段 8 + 输出具体缺口清单。

### 4.4 `meta.yaml` 结构

```yaml
id: REQ-2026-001
title: 示例需求
phase: detail-design            # 英文标识
created_at: 2026-04-20
branch: feat/req-2026-001
project: <项目名>                # 关联 context/project/<项目名>/
services:                       # 涉及的服务仓库（代码审查用）
  - service-a
  - service-b
gates_passed:                   # 门禁历史
  - phase: bootstrap
    at: 2026-04-20T10:00:00Z
  - phase: definition
    at: 2026-04-20T14:20:00Z
```

### 4.5 回退语义（`/requirement:rollback`）

1. `meta.yaml` 的 `phase` 改回早期阶段
2. 当前阶段的 `artifacts/` 归档到 `artifacts/.rollback-<timestamp>/`
3. `notes.md` 追加"回退原因"
4. 分析下游影响并提示用户

---

## 5. 多 Agent 并行代码审查

### 5.1 触发入口（三种）

- `/code-review`（显式命令）
- 对话"帮我审查一下代码"（自然触发）
- 阶段 7 功能点完成时由 `feature-lifecycle-manager` Skill 自动 invoke

### 5.2 流程

```
┌──────────────────────────────────────────────────────────────┐
│  触发  →  Skill: code-review-prepare（主上下文）                │
│           - 识别当前需求/分支                                   │
│           - 确定待审查服务仓库                                  │
│           - 获取增量 diff                                       │
│           - 输出 ReviewScope 到 .review-scope.json（根目录）    │
└──────────────────┬───────────────────────────────────────────┘
                   ↓
     ┌───────────────────┴───────────────────┐
     │  并行 8 个 Agent（独立上下文）          │
     │  主 Agent 在一条消息里同时调用所有      │
     │  checker + 综合 reviewer                │
     └───────────────────┬───────────────────┘
                         ↓
     7 个专项 checker（sonnet）并行执行：
     design-consistency / security / concurrency / complexity
     / error-handling / auxiliary-spec / performance
                         ↓
     code-quality-reviewer（opus）综合裁决：
     - 去重
     - 严重度排序
     - 关联性分析
     - 最终结论（approved / needs_revision / rejected）
                         ↓
          Skill: code-review-report（主上下文）
          写入 requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md
```

### 5.3 双模使用

| 模式 | 触发 | 是否需要 `requirements/<id>/` |
|---|---|---|
| 独立插件模式 | `/code-review` 在任意项目 | 否（用 `git diff origin/master...HEAD` 作 ReviewScope） |
| 嵌入生命周期模式 | 阶段 7 功能点完成 | 是（范围由 `meta.yaml` 的 `services` 决定） |

### 5.4 报告格式

```markdown
# 代码审查报告 · REQ-2026-001 · 2026-04-20 15:30

## 结论
**needs_revision** · 2 critical / 5 major / 12 minor

## Critical
### [security] service-a/UserController.java:42
动态 SQL 拼接 userId 参数，存在注入风险
建议：使用 PreparedStatement 参数化

## Major
...

## Minor
...

## 审查元信息
- 审查范围：service-a, service-b（增量 diff 共 320 行）
- 并行 checker：7 个，总耗时 42s
- 综合模型：opus
```

---

## 6. 记忆系统与跨会话恢复

### 6.1 三层记忆结构

```
工作记忆（Working Memory）· 会话对话上下文 · 不可持久化
         ↓ 中断溢出
溢出区（Spillover）· requirements/<id>/ 下的四个文件
         ↓ 验收沉淀
长期记忆（Long-term Memory）· context/ + skills/reference/ + requirements/*/artifacts/
```

### 6.2 四个溢出文件 + 工具日志（v2 分层）

| 文件 | 写入频率 | 写入方式 | 谁写 | 谁读 | 入 git |
|---|---|---|---|---|---|
| `meta.yaml` | 低（阶段切换） | 覆盖 | `managing-requirement-lifecycle` | 全体 | ✅ |
| `process.txt` | 中（每个语义事件） | **追加** | `requirement-progress-logger` Skill + `stop-session-save` Hook | `requirement-session-restorer` | ✅ |
| `process.tool.log` | 高（每次 Edit/Write/Bash） | **追加** | `auto-progress-log` Hook | （可选）恢复时 tail 看活动密度 | ❌（.gitignore） |
| `notes.md` | 中 | 追加 | `/note` + Agent 自主 | `/knowledge:*` 提炼时 | ✅ |
| `plan.md` | 中 | 覆盖 | 主 Agent 在对齐阶段 | 主 Agent 回看 + session-restorer | ✅ |

**布局切换**：由 `meta.yaml.log_layout` 控制：

- `split`（新需求默认，v2）：工具日志 → `process.tool.log`；语义事件 → `process.txt`
- `legacy` 或缺字段（老需求兼容，v1）：工具 + 语义混写 `process.txt`，无 `process.tool.log`

### 6.3 `process.txt` / `process.tool.log` 格式

`process.txt`（语义事件）：

```
2026-04-20 18:30:00 [bootstrap] 创建目录 REQ-2026-001
2026-04-20 18:45:22 [definition] requirement.md 完成草稿
2026-04-20 19:02:08 [review:needs_revision] requirement-quality-reviewer 3 条 major
2026-04-20 19:16:00 [phase-transition] definition → tech-research
2026-04-20 19:40:12 [SESSION_END] 会话结束
```

`process.tool.log`（v2 工具日志，Hook 写入，不入 git）：

```
2026-04-20 18:45:10 [definition] tool=Edit
2026-04-20 18:45:22 [definition] tool=Write
2026-04-20 19:16:05 [tech-research] tool=Bash
```

**时间戳规范**（v2 新约束）：Skill 写入时必须取"写入当下"的 Asia/Shanghai now（`TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M:%S"`），不得预先计算。消除 Hook 与 Skill 并发写入时的行序与时序错位（v1 下曾出现 `phase-transition` 时间戳早于前几行 `tool=Edit`）。统一格式与时区约定见 `context/team/engineering-spec/time-format.md`；历史 UTC ISO 8601 数据保留兼容读取。

### 6.4 跨会话恢复流程

```
/requirement:continue
  → managing-requirement-lifecycle 识别意图
  → requirement-session-restorer Skill
     ├── 读 meta.yaml                         → 阶段 + log_layout
     ├── 读 process.txt 末 50 行               → 语义事件（v2 密度约 100%）
     ├── （可选）tail process.tool.log 末 20 行 → v2 下看近期工具活动密度
     ├── 读 notes.md                          → 踩坑
     └── 读 plan.md                           → 当前计划
  → 主 Agent 输出"恢复摘要"（< 200 字）
  → 等用户确认后继续
```

### 6.5 长期记忆检索优先级（`universal-context-collector` 遵守）

```
1. context/project/<当前项目>/*                 最相关
2. context/project/<当前项目>/INDEX.md          先索引后深入
3. context/team/engineering-spec/               体系自身规范
4. context/team/*                               团队通用知识
5. 历史 requirements/*/artifacts/               类似需求参考
6. 外部 WebSearch / WebFetch                    最后手段；设计阶段禁用
```

### 6.6 `.gitignore` 策略

```gitignore
# 个人覆盖
.claude/settings.local.json

# 运行态临时文件
.review-scope.json
.DS_Store

# requirements/ 必须入 git（团队资产，不是临时文件）
# context/ 也必须入 git（团队公共记忆）
```

---

## 7. Hook / StatusLine / 开箱体验

### 7.1 Hook 清单（3 个）

| Hook | 触发 | 目的 |
|---|---|---|
| `protect-branch.sh` | `PreToolUse`（Bash/Edit/Write） | master/main 上写操作时阻止 |
| `auto-progress-log.sh` | `PostToolUse`（Edit/Write/Bash） | 自动追加到 `process.txt` |
| `stop-session-save.sh` | `Stop` | 会话结束时保存状态、打 `SESSION_END` 标记 |

### 7.2 Hook 硬约束

- 全部 Bash，**幂等**、**< 100ms**、**失败不阻塞**（除 protect-branch）
- 状态读写只碰 `requirements/<id>/` 下的文件，不碰 `.claude/` 和 `context/`
- 通过 `git branch --show-current` 反查 `meta.yaml` 定位当前需求

### 7.3 StatusLine 格式

```
[REQ-2026-001·详细设计·5/8] feat/req-2026-001 ⬆ 2 ahead  |  🤖 opus
```

由 `.claude/statusline.sh` 实现，读 git 分支反查 `meta.yaml`。

### 7.4 `.claude/settings.json` 关键配置

```json
{
  "permissions": {
    "allow": ["Bash(git status)", "Bash(git diff:*)", "Bash(git log:*)", "Read", "Grep", "Glob"],
    "ask": ["Bash(git push:*)", "Bash(git commit:*)", "Edit", "Write"],
    "deny": ["Bash(rm -rf:*)", "Bash(git reset --hard:*)", "Bash(git push --force:*)"]
  },
  "hooks": { /* 三个 hook 注册 */ },
  "statusLine": { "type": "command", "command": ".claude/statusline.sh" }
}
```

### 7.5 `.mcp.json` 策略

- **默认不启用**：仓库只提供 `.mcp.json.example` 作为候选模板，避免 `git clone` 后被动触发 `npx` 拉包和 Chromium 下载。`.mcp.json` 已 gitignore
- **候选内容**：`context7`（库文档）、`chrome-devtools`（浏览器自动化）——用户按需 `cp .mcp.json.example .mcp.json` 并裁剪
- **占位**：`jira` / `wiki` / `notifier`（对应原文 TAPD / iWiki / 企微），以 JSON 注释形式保留在模板里，需替换真实 endpoint 后启用

### 7.6 开箱体验对照表

| 原文 | 骨架版 | 状态 |
|---|---|---|
| TAPD / iWiki / 企微 MCP | 公开 MCP 开箱；企业 MCP 占位 | ⚠️ 占位 |
| 状态行配好 | ✅ | ✅ |
| 保护分支 Hook | ✅ | ✅ |
| 消息通知 | 降级：`/agentic:feedback` 写 `context/team/feedback-log.yaml` | ⚠️ 降级 |
| `/agentic:help` | ✅ | ✅ |
| 双 CLI 兼容 | 只 Claude Code | ✅ 按约定精简 |

---

## 8. 团队落地路径

### 8.1 四阶段策略（对标文章第七章）

| 阶段 | 核心动作 | 衡量标准 |
|---|---|---|
| 种子期 | 1 人先跑通真实业务 + 发布 8 阶段学习知识库 | 团队至少 1 人独立走完前 3 阶段 |
| 扩散期 | `git clone` 替代培训，新人 30 分钟上手 | 2-3 人日常使用，经验回流 `context/` |
| 加速期 | 跑通者嵌入其他项目组帮打第一仗 | 每项目 `context/project/<X>/` 有第一批业务知识 |
| 常态期 | 制度化（PR 共享 / context 维护 / 新人 Onboarding） | PR 流程稳定，新人半天上手 |

### 8.2 8 阶段学习路径

放在 `context/team/onboarding/learning-path/`，骨架建成时**一次性全部写完**。

| 阶段 | 文件 | 学到什么 | 可验证动作 |
|---|---|---|---|
| 1 | `01-environment.md` | 装 Claude Code / 配 API Key | `claude /agentic:help` 有输出 |
| 2 | `02-first-conversation.md` | 场景引导 + 上下文提供 | 让 AI 读懂 README 并总结 |
| 3 | `03-command-skill-agent.md` | 三级工具选型 | 跑 `/requirement:list`，理解联动 |
| 4 | `04-first-requirement.md` | 跑完一个完整 8 阶段小需求 | 完成 1 个 < 1 人天的练习需求 |
| 5 | `05-code-review.md` | 用 `/code-review` 做增量审查 | 拦截过至少 1 个真实问题 |
| 6 | `06-knowledge-sinking.md` | 用 `/note` 和 `/knowledge:*` 沉淀 | 提交 1 份经验文档 PR |
| 7 | `07-custom-command.md` | 写 1 个自定义 Command | 提交 1 个 `.claude/commands/<你的>.md` |
| 8 | `08-custom-skill.md` | 写 1 个最小 Skill | 提交 1 个 `.claude/skills/<你的>/SKILL.md` |

前 6 阶段必修，后 2 阶段选修。

### 8.3 《Agentic 工程师入门指南》

位置：`context/team/onboarding/agentic-engineer-guide.md`
在 `CLAUDE.md` 里 `@import`（Agent 也能引用它指导新人）

**一个认知转变**：
> 核心工作从"写代码"变成"引导上下文 + 验证结果"。

**一条最小行动路径**（5 步）：
1. 说出场景
2. 提供业务上下文
3. 让 AI 按规范推进
4. 验证与纠偏
5. 确认沉淀

**第一周目标**：用这个流程完成 1 个小需求。

### 8.4 常态期制度化边界

| 该做 | 不该做 |
|---|---|
| `context/` 改动走轻量 PR review | 搞 4 级审批流程 |
| 新人半天内通过"老成员陪伴"上手 | 开 2 小时培训课 |
| 每个人都能提 PR 改 Skill/Agent | 限制只有少数人能改 |
| 定期清理过时 `context/` 文档 | 让文档积灰 |
| 只沉淀"跨会话/跨人/重复"的知识 | 为偶发问题写永久规则 |

---

## 9. 未实现清单（缺口明示）

所有未实现项会以显式清单形式写入 `CLAUDE.md`，避免 Agent "自作主张"生成虚假能力说明。

### 9.1 Skill 缺口（到 27 的差距：17 个）

以下 Skill **有可能在未来需要**，但本次骨架不建；真遇到问题再加：
- 业务配置生成类（如 `config-gen-engine` 的业务版）
- `managing-code-review`（伞形）——当 `/code-review` 逻辑超 100 行时
- `mcp-setup-guide`——新人反复问 MCP 配置时
- `ai-collaboration-primer`——新人不熟悉和 AI 对话时
- 其余依真实问题驱动

### 9.2 Agent 缺口（到 22 的差距：2 个）

文章 5.1 图表之外的阶段级 Agent（如果需要更细化的阶段支持），暂不建。

### 9.3 Command 缺口（到 28 的差距：12 个）

基本都是原文对应内部业务的命令，无迁移必要。

### 9.4 MCP 缺口

- Jira / 飞书 / DingTalk 类替换：留占位
- 内部 TAPD / iWiki / 企微：无法外部重建

---

## 10. 决策记录

本设计在 brainstorming 过程中通过一系列 A/B/C 决策得出。关键决策及依据：

| # | 决策点 | 决定 | 依据 |
|---|---|---|---|
| 分发形态 | A/B/C | B：团队模板仓库 | 文章 8.1 节 fork 路径 |
| 重建规模 | 1/2/A/B | A：全量骨架 + 业务占位 | 用户选择 |
| 工具范围 | 1/2 | 2：文章明确 + 强推断 | 规避文章 9.2 的"规范膨胀"坑 |
| 技术栈 | A/B/C/D | D：多栈，team 通用规范 | 用户选择 |
| a | `requirements/` 位置 | 根目录 | 贴文章 3.2，"位置即语义" |
| b | AGENTS.md 软链 | 不加 | 用户选择 |
| c | 体系规范目录名 | `context/team/engineering-spec/` | 文章未明确分 meta；并入 team 减少认知负担 |
| d | `docs/` 是否进上下文 | 全部并入 `context/` | 文章 3.3"文档即记忆"；docs/ 独立目录无依据 |
| e | `/agentic:feedback` 去向 | 本地 `feedback-log.yaml` | 无企微接入 |
| f | `/code-review` 默认范围 | 当前分支 vs master 增量 | 社区约定 |
| g | `/note` 子命令 | 不拆 | 极简 |
| h | 命名空间分隔符 | 冒号 `:` | Claude Code 约定 |
| i | `managing-requirement-lifecycle` 拆分 | 不拆 | 文章 5.1"伞形"模式 |
| j | `task-context-builder` 类型 | Skill | 文章 5.4 |
| k | `/agentic:help` 要 Skill 吗 | 不要 | 命令 < 100 行足够 |
| m | `task-context-builder` 类型 | Skill | 贴文章 5.4 |
| n | checker 命名语言 | 英文 | 和 Claude Code 生态一致 |
| o | 加 `performance-checker` | 加 | 常见痛点 |
| p | 阶段 Agent 缺口处理 | `CLAUDE.md` 列未实现清单 | 避免 Agent 幻觉 |
| q | 8 阶段命名 | 按文章图表 | 图表提供了准确信息 |
| u | 技术预研门禁 | 不强制 reviewer | 骨架保守 |
| v | input-normalizer 职责 | 模糊表达 → 结构化 | 文章 5.1 描述 |
| w | feature-lifecycle vs managing-lifecycle | 边界清晰：后者管阶段切换，前者管阶段 6 内功能点 | 职责内聚 |
| x | checker 模型 | sonnet | 用户选择（平衡成本和准确） |
| y | code-quality-reviewer 模型 | opus | 文章"strong"原文 |
| z | 阶段 7 触发粒度 | 每个 feature_id 完成一次 | 文章 5.1 明确 |
| aa | 审查报告命名 | `review-YYYYMMDD-HHMMSS.md` | 可排序 |
| bb | 审查报告是否写 notes.md | 否 | 避免冗余 |
| cc | `requirements/` 入 git | 入 | 团队资产 |
| dd | 进度记录粒度 | Edit/Write/Bash | 平衡信息与噪音 |
| ee | 恢复摘要长度 | < 200 字 | 渐进披露 |
| ff | plan.md vs tasks/ | 阶段级 vs 功能点级，互不重叠 | 职责分离 |
| gg | Git 权限策略 | 读 allow / 写 ask / 危险 deny | 渐进信任 |
| hh | StatusLine 显示 token | 否 | 简洁 |
| ii | `post-feature-review.sh` | **删除** | 设计错误（Hook 里起会话反模式 + 和 feature-lifecycle-manager 职责重叠） |
| jj | 默认 MCP 数量 | 2（context7 + chrome-devtools） | 用户本地已配 |
| kk | 学习路径完成度 | 一次性写完 | 用户选择 |
| ll | 入门指南 import | import | 用户选择 |
| mm | feedback-log 格式 | YAML 结构化 | 用户选择 |

---

## 11. 后续步骤

1. 用户审阅本设计文档（本文件）
2. 如无修改 → 用 `writing-plans` skill 拆 phase-by-phase 实施计划
3. 按实施计划逐 Phase 建立文件（每个 Phase 可独立 commit）
4. 每个 Phase 结束都是一个可用状态

---

## 附录 A：术语表

- **Command**：薄层意图入口，< 100 行，仅预检 + 委托
- **Skill**：主对话中的专业知识包，SKILL.md < 2k token，含 reference/templates/scripts
- **Subagent / Agent**：独立上下文的专业同事，返回 < 2k token，禁止嵌套调用
- **ReviewScope**：代码审查的范围描述对象，写在根目录 `.review-scope.json`（运行时临时文件，入 `.gitignore`）
- **feature_id**：功能点唯一标识，在 `features.json` 定义，贯穿代码 commit / 测试报告 / 追溯链
- **溢出区**：会话中断时状态的"存档"位置（`process.txt` / `notes.md` / `plan.md` / `meta.yaml`）
- **渐进式披露（Agentic Search）**：轻量入口 + 按需检索，对抗上下文膨胀

## 附录 B：参考

- 原文：《认知重建之后，步入 Agentic Engineering 的工程革命》（腾讯技术工程 rickyshou，2026-03-30）
- Anthropic: Effective Context Engineering for AI Agents
- Anthropic: Building Effective AI Agents
- Harrison Chase (LangChain): What is an AI Agent?
- OpenAI: Harness engineering: leveraging
