---
description: 从实践中生成标准操作流程（SOP）
argument-hint: <目标场景名>
---

## 用途

某个操作反复出现、流程可标准化时生成 SOP 沉淀下来。

## 预检

1. 参数 `<目标场景名>` 非空
2. `context/team/experience/` 或 `requirements/*/notes.md` 下能 grep 到涉及该场景的条目（≥ 2 条才值得做 SOP）

## 委托

调用 Skill `managing-knowledge`，子意图 **generate-sop**：

- 加载 `reference/generate-sop.md` 规则
- 收集相关实践 → 识别通用步骤 + 决策点
- 起草 SOP 结构（触发条件 / 前置检查 / 主流程 / 决策点 / 完成标准）
- 先输出结构+关键步骤给用户确认
- 确认后落盘到 `context/team/engineering-spec/sop/<slug>.md` 或 `context/team/experience/`
- 更新对应 INDEX.md
