---
id: REQ-2026-001
refs-requirement: artifacts/requirement.md
created_at: 2026-04-20T15:35:00Z
---

# REQ-2026-001 概要设计

## 架构方案

无新增模块。方案是在 `CLAUDE.md` 末尾（"反馈" 段后 / 文件末端）插入一段 `## Common Pitfalls`。

## 模块划分

- **文档层**：`CLAUDE.md` 新增段
- **知识层**（可选）：将 5 条坑的**来源**记入 `context/team/experience/common-pitfalls-sources.md`（供日后扩充时检索）

## 变更影响

- 影响文件：`CLAUDE.md`（+ ~30 行）
- 不影响：任何 Command/Skill/Agent 的行为

## 评审要点

- 位置合理性：CLAUDE.md 当前结构 = 原则 → 规范引用 → 检索优先级 → 未实现清单 → 反馈。新增段应在"反馈"前还是后？**决策：在"反馈"前**（读者看完主索引应先知道常见坑，再知道如何反馈）
- 与 `context/team/onboarding/agentic-engineer-guide.md` 的重合：该指南也写了新人上手流程。决策：Pitfalls 段聚焦"容易出错的动作"，入门指南聚焦"正确的学习路径"，两者互补不重复
