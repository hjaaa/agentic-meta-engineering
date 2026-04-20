# Stage 7 · 写一个自定义 Command（选修）

**完成时间**：30 分钟
**前置**：Stage 3 完成
**可验证动作**：提交 1 个 `.claude/commands/<你的>.md`

## Command 硬约束回顾

见 `context/team/engineering-spec/tool-design-spec/command-spec.md`。关键：

- < 100 行
- 只做**预检 + 委托给 Skill**，不做业务逻辑

## 练习

写一个 `/project:status` 命令：

1. 预检当前是 git 仓库
2. 委托给 Skill（可以是新建的 `managing-project-status`，也可以是已有 Skill）
3. 输出：最近 10 个 commit、modified 文件数、未跟踪文件数

## 模板

```markdown
---
description: 展示项目状态摘要
---

## 用途

用户想快速了解项目当前状态时调用。

## 预检

1. 确认在 git 仓库中：`git rev-parse` 不出错

## 委托

使用 Skill `managing-project-status` 的"摘要"流程。
```

## 完成标志

- [ ] 命令 < 100 行
- [ ] 跑 `/project:status` 能输出预期结果
- [ ] 提交 PR
