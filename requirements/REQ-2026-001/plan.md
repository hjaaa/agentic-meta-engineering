# REQ-2026-001 · 会话结束经验提取 Hook

## 目标

为 Agentic Engineering 工程骨架补齐"会话结束自动经验提取 Hook"——SessionEnd 时自动调用一个小 Agent 分析最近对话，把经验/坑点/决策追加到 `requirements/<id>/notes.md`，对抗"复盘流于形式"的 AI slop。

## 范围

- 包含：
  - SessionEnd Hook 配置（`.claude/settings.json` + 可执行脚本）
  - Hook 仅在"需求开发会话"生效（即当前分支匹配 `feat/req-*` 且对应 `requirements/<id>/` 存在）
  - 调用 `claude -p` 起小 Agent 抽取经验，写入 `requirements/<id>/notes.md`（追加，不覆盖）
  - 失败/超时静默降级，不阻塞用户退出
  - 单元/集成验证：人造 transcript fixture 跑通端到端
- 不包含：
  - 跨项目沉淀到 `context/team/experience/`（手工 promote，本次不自动化）
  - 推送到企微/IM
  - 对 Stop 事件（每轮 Agent 结束）做提取（仅 SessionEnd）
  - 对非需求会话生效

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

- 风险 1：Hook 阻塞退出 / 超时 → 应对：用后台模式 + 超时上限 + 失败静默降级
- 风险 2：`claude -p` 在无网/限流时调用失败 → 应对：catch 住非零退出、写一行 `[hook-skipped]` 到 notes.md，不向用户报错
- 风险 3：把无关会话（非需求开发）的内容污染 notes.md → 应对：触发条件严格收敛（必须当前分支为 `feat/req-*` 且 meta.yaml 存在）
- 风险 4：transcript 过长导致 Agent 上下文爆炸 → 应对：截断策略（保留最近 N 轮 + 关键节点）

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 <决策标题>
- **Context**：做决策时的背景 / 约束
- **Decision**：选了什么，没选什么
- **Consequences**：好的后果、不好的后果
- **时间**：YYYY-MM-DD HH:MM:SS
- **Supersedes**：D-NNN（废弃前一决策时才有）
