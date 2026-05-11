---
description: 查看所有需求的状态索引
---

> [DEPRECATION] /requirement:list 已纳入 3 月兼容期（截至 2026-08-08）。
> 请改用：/workflow:list [--filter=<expr>]
> 本次仍执行旧实现以保证兼容；Plan 6 自举验证通过 + 兼容期到期后将物理删除。
> 详见：context/team/engineering-spec/migration/2026-XX-runs-rename.md
>
> **ARGUMENTS 透传规则**：flag 直传，如 `/workflow:list --filter=phase=development`

## 用途

多需求并行时快速看整体进度；新人上手时了解团队当前在做什么。

## 预检

无（无需求时也能运行——输出"当前无活跃需求"）

## 参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--all` | 显示所有需求，包括 phase=completed 的 | false（默认隐藏 completed） |
| `--phase <p>` | 仅显示指定阶段的需求 | 无（默认显示全部非 completed）|

**互斥规则**：`--all` 与 `--phase` 不能同时使用，同时传入时退出码为 1。

## 委托

调用函数 `list_requirements()`：

- 扫 `requirements/*/meta.yaml`
- 默认隐藏 `phase=completed` 的需求；`--all` 时显示全部；`--phase <p>` 时仅留指定阶段
- 按 `created_at` 倒序
- 输出 Markdown 表格：ID / 标题 / 阶段（中文名）/ 分支 / 创建时间

| # | 列 |
|---|---|
| 1 | REQ-2026-003 \| 注册优化 \| 详细设计 \| feat/req-2026-003 \| 2026-04-18 |
