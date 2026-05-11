---
description: 保存进度到 process.txt，为跨会话恢复准备
argument-hint: "[事件描述]（可选）"
---

> [DEPRECATION] /requirement:save 已纳入 3 月兼容期（截至 2026-08-08）。
> 请改用：/workflow:save [<note>]
> 本次仍执行旧实现以保证兼容；Plan 6 自举验证通过 + 兼容期到期后将物理删除。
> 详见：context/team/engineering-spec/migration/2026-XX-runs-rename.md
>
> **ARGUMENTS 透传规则**：`$@` 拼空格作 note，如 `/workflow:save 方案评审已通过`

## 用途

重要节点主动存档；或会话即将结束时用户显式调用。Hook 已处理工具级自动记录，这个命令用于**语义级显式节点**（例如"方案评审过了"、"发现一个阻塞"）。

## 预检

1. 当前分支对应需求存在

## 委托

调用 Skill `managing-requirement-lifecycle` → 再委托给 `requirement-progress-logger`：

- 如用户提供了事件描述：直接用作日志正文
- 如未提供：从最近对话上下文摘要一句话作日志正文
- 格式化 `YYYY-MM-DD HH:MM:SS [phase] <事件描述>`（Asia/Shanghai 时区，详见 `context/team/engineering-spec/time-format.md`）
- 追加到 process.txt
- 输出确认
