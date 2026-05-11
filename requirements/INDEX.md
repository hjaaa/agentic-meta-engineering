# 需求索引

本目录承载全部需求的全生命周期产出物。入 git，是团队资产。

新需求用 `/requirement:new <标题>` 创建；恢复用 `/requirement:continue`；查看进度用 `/requirement:status`；提 PR 用 `/requirement:submit`。

查看所有需求当前阶段：`/requirement:list`。

## 单需求目录结构

```
requirements/REQ-YYYY-NNN/
├── meta.yaml        # 元信息：phase / branch / services / gates_passed / reviews / 语义字段
├── plan.md          # 活档案：上半（可覆盖）+ 下半 ## 决策记录 ADR（append-only）
├── process.txt      # 时间线状态事件流（推进/停滞有意义的事；append-only）
├── notes.md         # 跨需求可复用知识池（/knowledge:extract-experience 的原料；append-only）
├── artifacts/       # 阶段产出（详见下文 8 阶段映射）
│   ├── requirement.md          # 阶段 2 需求文档
│   ├── tech-feasibility.md     # 阶段 3 技术预研
│   ├── outline-design.md       # 阶段 4 概要设计
│   ├── detailed-design.md      # 阶段 5 详细设计
│   ├── features.json           # 阶段 5/6 功能点清单
│   ├── tasks/<F-NNN>.md        # 阶段 6 单 feature 任务卡
│   ├── tasks/<F-NNN>.receipt.json  # 阶段 7 派发链回执（GATE-POST-DEV-RECEIPT 依赖）
│   ├── review-YYYYMMDD-HHMMSS.md   # 阶段 7 代码审查报告
│   ├── codex-reviews/          # 可选：submit 走 codex review-loop 的产出
│   ├── test-report.md          # 阶段 8 测试报告
│   ├── traceability-report.md  # 可选：阶段 8 追溯链报告
│   └── retrospective.md        # 可选：自定义回溯文档
└── reviews/         # 评审 verdict JSON（GATE-REVIEW-VERDICT 依赖）
    ├── definition-NNN.json         # 阶段 2 评审
    ├── outline-design-NNN.json     # 阶段 4 评审
    ├── detail-design-NNN.json      # 阶段 5 评审
    └── code-F-NNN-NNN.json         # 阶段 7 单 feature 代码审查
```

## 三文件职责区分（按 [spillover-redefine spec §3](../context/team/engineering-spec/specs/2026-04-24-spillover-redefine-design.md)）

| 文件 | 写什么 | 不写什么 | 写入通道 |
|---|---|---|---|
| **process.txt** | 时间线事件流（推进/停滞有意义） | 经验沉淀 / 决策（去 notes.md / plan.md） | 仅 `requirement-progress-logger` Skill |
| **notes.md** | 跨需求可复用经验（坑 / 假设 / 工具细节 / 待澄清） | 当前需求一次性细节 / 时间线事件 | `/note <内容>` 命令 + 主 Agent 自主 append |
| **plan.md** 上半 | 目标 / 范围 / 里程碑 / 风险 | 决策（走下半 ADR） | 主 Agent 阶段对齐时**覆盖** |
| **plan.md** 下半 | `## 决策记录` ADR 小卡集（D-NNN） | 风险跟踪、临时备忘 | 主 Agent 决策时**append** |

**判断口诀**：

- 「时间线发生过的事」→ process.txt
- 「将来 `/knowledge:extract-experience` 会提到 `context/team/experience/` 吗」→ 会 → notes.md
- 「影响架构/契约/工期/依赖的选择」→ plan.md `## 决策记录`

**process.txt 事件标签白名单**：`[phase-transition]` / `[save]` / `[review:approved|needs_revision|rejected]` / `[gate:pass|fail]` / `[blocker]` / `[blocker-resolved]` / `[archived]` / `[codex-review-triggered]` / `[codex-review-received]` / `[signoff]`

**plan.md ADR 写入规则**：

- 新决策 append 一个 `### D-NNN` 小节（D-NNN 自增不复用）
- 废弃旧决策不回删，新开一条带 `Supersedes: D-NNN`
- 哪些决策必须写：影响架构 / 契约 / 工期 / 依赖
- 哪些不写：目录命名 / 纯文档风格 / 临时测试策略

## 8 阶段 ↔ artifact 映射

| # | 阶段 | 必备产物 | 评审 verdict |
|---|---|---|---|
| 1 | bootstrap | meta.yaml / plan.md 骨架 | — |
| 2 | definition | artifacts/requirement.md | reviews/definition-NNN.json |
| 3 | tech-research | artifacts/tech-feasibility.md | — |
| 4 | outline-design | artifacts/outline-design.md | reviews/outline-design-NNN.json |
| 5 | detail-design | artifacts/detailed-design.md + features.json | reviews/detail-design-NNN.json |
| 6 | task-planning | artifacts/tasks/F-NNN.md | — |
| 7 | development | 代码 + tasks/F-NNN.receipt.json + artifacts/review-*.md | reviews/code-F-NNN-NNN.json |
| 8 | testing | artifacts/test-report.md（可选 traceability-report.md） | — |
| 9 | completed | meta.yaml.outcome=shipped + archived_at | — |
