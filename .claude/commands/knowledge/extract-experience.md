---
description: 从实践数据中提取可迁移的经验
argument-hint: "[notes 文件路径]（可选，默认当前需求的 notes.md）"
---

## 用途

需求验收后或阶段性总结时，从碎片化笔记中提炼结构化经验，沉淀到 `context/`。

## 预检

1. 如用户提供路径：文件存在且非空
2. 如未提供：当前分支对应需求的 `notes.md` 存在且非空

## 委托

调用 Skill `managing-knowledge`，子意图 **extract-experience**：

- 加载 `.claude/skills/managing-knowledge/reference/extract-experience.md` 的规则
- 按"三必要条件"（跨需求/AI 反复错/跨会话需保留）筛选候选
- 渐进式输出候选清单（< 5 条+简要描述）
- 用户确认要沉淀哪几条 + 归属位置（`context/project/<X>/` 或 `context/team/experience/`）
- 落盘 + 更新对应 INDEX.md
