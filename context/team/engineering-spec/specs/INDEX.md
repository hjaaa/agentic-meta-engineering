# specs/ 索引

本目录存放体系级设计留档（Architecture Decision Records 变体）。
每份文档记录一个设计决策的背景、方案与实施情况，作为后续维护的记忆锚点。

## 文档列表

| 文件 | 日期 | 主题 | 状态 |
|---|---|---|---|
| [2026-04-20-agentic-engineering-skeleton-design.md](2026-04-20-agentic-engineering-skeleton-design.md) | 2026-04-20 | Agentic Engineering 骨架设计 | draft |
| [2026-04-22-index-meta-validation-design.md](2026-04-22-index-meta-validation-design.md) | 2026-04-22 | INDEX / meta.yaml 校验设计 | — |
| [2026-04-23-retire-agentic-feedback.md](2026-04-23-retire-agentic-feedback.md) | 2026-04-23 | agentic-feedback 退役记录 | — |
| [2026-04-24-spillover-redefine-design.md](2026-04-24-spillover-redefine-design.md) | 2026-04-24 | spillover 需求重定义设计 | — |
| [2026-04-27-reviewer-verdict-structuring-design.md](2026-04-27-reviewer-verdict-structuring-design.md) | 2026-04-27 | Reviewer Verdict 结构化设计 | 设计中 |
| [2026-04-30-code-review-human-checkpoints.md](2026-04-30-code-review-human-checkpoints.md) | 2026-04-30 | 代码审查人类必经卡点（双卡点机制） | 已落地 |
| [2026-05-04-submit-codex-loop-and-archive-design.md](2026-05-04-submit-codex-loop-and-archive-design.md) | 2026-05-04 | submit 增强 Codex review-loop + 新增 archive 命令 | 设计中 |

## 检索提示

- 按日期前缀找版本演进
- 按主题关键词搜索：`grep -r "关键词" context/team/engineering-spec/specs/`
- 最新决策优先级最高；旧决策若已被新文档替代，新文档头部会有 `supersedes` 引用
