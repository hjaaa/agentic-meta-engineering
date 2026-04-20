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
