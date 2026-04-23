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

## 特殊分支场景

以下分支名前缀为例外，不要求匹配 `feat/req-*` 模式：

- `setup/*` — 骨架搭建或集成验收（如 Phase 4 的 `setup/phase-4-integration`）
- `fix/*` — 紧急修复
- `release/*` — 发版

这些分支下创建的需求，`meta.yaml.branch` 字段应记录**实际分支名**，以保持 Hook 的匹配。Skill 的门禁校验对分支前缀不做强制限制，只校验"`meta.yaml.branch == 当前分支`"。

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
