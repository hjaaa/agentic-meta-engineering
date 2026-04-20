---
description: 查看所有需求的状态索引
---

## 用途

多需求并行时快速看整体进度；新人上手时了解团队当前在做什么。

## 预检

无（无需求时也能运行——输出"当前无活跃需求"）

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **list** 流程：

- 扫 `requirements/*/meta.yaml`
- 按 `created_at` 倒序
- 输出 Markdown 表格：ID / 标题 / 阶段（中文名）/ 分支 / 创建时间

| # | 列 |
|---|---|
| 1 | REQ-2026-003 \| 注册优化 \| 详细设计 \| feat/req-2026-003 \| 2026-04-18 |
