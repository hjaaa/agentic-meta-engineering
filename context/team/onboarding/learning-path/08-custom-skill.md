# Stage 8 · 写一个最小 Skill（选修）

**完成时间**：1-2 小时
**前置**：Stage 7 完成
**可验证动作**：提交 1 个 `.claude/skills/<你的>/SKILL.md`

## Skill 硬约束回顾

- SKILL.md < 2k token
- 三种内容：指令 / 代码 / 资源
- 渐进式披露：入口轻量，详细知识放 reference/

## 练习

延续 Stage 7，创建 `managing-project-status` Skill：

```
.claude/skills/managing-project-status/
├── SKILL.md              # 入口
├── reference/
│   └── status-fields.md  # 每个字段的语义
└── scripts/
    └── collect.sh        # 收集 git 数据的脚本
```

## SKILL.md 模板

```markdown
---
name: managing-project-status
description: 收集并汇总项目当前状态（commit 数、变更文件、未跟踪文件等）。被 /project:status 调用。
---

## 什么时候用

用户触发 /project:status 或口头说"项目现在什么状态"时。

## 核心流程

1. 运行 `scripts/collect.sh` 获取原始数据（JSON 格式）
2. 按 reference/status-fields.md 定义的格式化方式渲染输出
3. 返回简洁 Markdown 摘要

## 硬约束

- ❌ 禁止直接调用 git 命令超过 3 次
- ❌ 禁止把原始 git log 全部塞进输出
- ✅ 只返回最近 10 条 commit + 统计数字

## 参考

- [`reference/status-fields.md`](reference/status-fields.md)
- [`scripts/collect.sh`](scripts/collect.sh)
```

## 完成标志

- [ ] SKILL.md < 2k token
- [ ] reference/ 和 scripts/ 各有至少 1 个文件
- [ ] 配合 Stage 7 的 Command 能端到端跑通
- [ ] 提交 PR
