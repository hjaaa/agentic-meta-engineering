---
name: task-planning
node_id: task-decompose
version: 1.0.0
---

# 任务规划阶段（task-planning）

阶段 6：task-planning

本阶段包含以下节点：
- `task-decompose`（skill: feature-lifecycle-manager, mode: split）：
  读取 `features.json`，为每个 feature 生成对应的 task markdown 文件（含 frontmatter）
- `task-frontmatter-check`（artifact）：校验 `tasks/` 下所有 task 文件的 frontmatter 合规性
- `task-list-summary`（bash）：统计 task 数量，生成摘要报告
- `task-signoff`（approval）：人工确认任务拆分方案
- `phase-to-development`（bash）：写 phase 字段，切换到开发阶段

本阶段所有 AI 工作节点均为 skill 引用，prompt 由 `feature-lifecycle-manager` Skill 管理。
此文件为阶段占位 prompt，标识本阶段的语义边界。
