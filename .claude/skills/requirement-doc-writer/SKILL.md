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
