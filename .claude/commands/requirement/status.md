---
description: 查看当前需求的阶段、进度、待办概览
---

## 用途

快速了解当前需求状态，不深入细节。典型 < 5 秒读完的摘要。

## 预检

1. 当前分支对应需求存在

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **status** 流程：

- 读 `meta.yaml` → 当前阶段 + 已通过门禁列表
- 读 `process.txt` 末 3 行 → 最近动作
- 扫描 `artifacts/` → 已产出文件清单
- 如在阶段 7（development）：额外扫 `artifacts/tasks/*.md`，统计 feature 状态（pending / in-progress / done）
- 输出紧凑摘要（< 400 字）
