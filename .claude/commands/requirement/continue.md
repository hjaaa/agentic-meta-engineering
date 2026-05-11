---
description: 恢复之前中断的需求上下文
argument-hint: "[需求 ID]（可选，不填则按当前分支推断）"
---

> [DEPRECATION] /requirement:continue 已纳入 3 月兼容期（截至 2026-08-08）。
> 请改用：/workflow:continue [<id>]
> 本次仍执行旧实现以保证兼容；Plan 6 自举验证通过 + 兼容期到期后将物理删除。
> 详见：context/team/engineering-spec/migration/2026-XX-runs-rename.md
>
> **ARGUMENTS 透传规则**：`$1` 直传，如 `/workflow:continue REQ-2026-001`

## 用途

开新会话要接着之前的需求继续工作时触发。

## 预检

1. 如用户提供了需求 ID：`requirements/<ID>/meta.yaml` 存在
2. 如未提供：当前分支能在某个 `requirements/*/meta.yaml` 的 `branch` 字段找到匹配
3. 都没找到 → 列出当前所有需求供选择

## 委托

调用 Skill `managing-requirement-lifecycle` → 再委托给 `requirement-session-restorer` Skill：

- 按顺序读 `meta.yaml` / `process.txt`（末 50 行）/ `notes.md` / `plan.md`
- 输出 < 200 字的"恢复摘要"
- 等用户确认后继续工作
