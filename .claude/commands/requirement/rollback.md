---
description: 回退到早期阶段，归档当前产出物
argument-hint: <目标阶段英文标识>
---

## 用途

发现前序阶段设计有问题，需要回到更早阶段重新做。

## 预检

1. 当前分支对应需求存在
2. 参数 `<目标阶段>` 是合法阶段英文标识（bootstrap / definition / tech-research / outline-design / detail-design / task-planning / development / testing）
3. 目标阶段严格**早于**当前 `meta.yaml.phase`
4. 工作目录 clean（避免回退丢失未提交改动）

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **rollback** 流程：

- 把 `artifacts/` 下所有"晚于目标阶段"的产出归档到 `artifacts/.rollback-<ISO8601>/`
- 更新 `meta.yaml.phase` = 目标阶段
- 询问用户回退原因（一句话），追加到 `notes.md`
- 委托 `requirement-progress-logger` 写 `[phase-transition] <old> → <new> (rollback)`
- 分析下游影响（哪些后续阶段的产出将作废）并输出给用户
