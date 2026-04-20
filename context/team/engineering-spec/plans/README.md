# 实施计划索引

按文章"每个 Phase 结束都是一个可用状态"的原则拆分。每个 Phase 对应一份独立的 plan 文档。

| Phase | 范围 | Plan 文档 | 状态 |
|---|---|---|---|
| 1 | 基础设施 + 上下文文档（root configs / hooks / statusline / 完整 context/ 树） | [phase-1-foundation](./2026-04-20-phase-1-foundation.md) | ✅ 已完成（20 Tasks · 合入 `setup/phase-1-foundation`） |
| 2a | 10 Skill（伞形 + 专项） | [phase-2a-skills](./2026-04-20-phase-2a-skills.md) | ✅ 已完成（11 Tasks · 分支 `setup/phase-2a-skills`） |
| 2b | 16 Command + 集成验证 | 待 Phase 2a 完成后撰写 | ⏸ 未开始 |
| 3 | 20 Agent | 待 Phase 2b 完成后撰写 | ⏸ 未开始 |
| 4 | 集成验收 + Phase 1 示例需求跑通 | 待 Phase 3 完成后撰写 | ⏸ 未开始 |

## 执行原则

1. 一次只执行一个 Phase，完成后再写下一个 Phase 的 plan
2. 每个 Phase 内部按 task 顺序执行，每个 task 单独 commit
3. Phase 完成后做一次整体 review，通过才进下一 Phase
