# Command 设计规范

**Command 是意图快捷入口，不是流程执行器。**

## 硬约束

| 约束 | 数值 | 理由 |
|---|---|---|
| 单文件行数 | < 100 行 | 避免把领域逻辑塞进 Command |
| 职责 | 仅预检 + 委托给 Skill | 逻辑集中在 Skill，Command 改了不动 Skill |
| 同领域多 Command | 委托**同一个**伞形 Skill | `/requirement:new` / `:continue` / `:next` / ... 全部委托 `managing-requirement-lifecycle` |

## 为什么这样分

同领域的多个命令（如 7 个 `/requirement:*`）背后共享**同一套领域知识**。如果每个 Command 都把逻辑重复写一遍，改一条规则要同时改 7 个文件。维护成本从 O(n) 降到 O(1)。

## 文件结构

```
.claude/commands/
├── <name>.md                    根命令
└── <namespace>/
    └── <name>.md                命名空间命令 → /<namespace>:<name>
```

## Command 文件骨架

```markdown
---
description: 一句话说这个命令做什么
argument-hint: <参数提示（可选）>
---

## 用途

一段话描述触发时机和使用场景。

## 预检

1. [前置条件 1]
2. [前置条件 2]

预检不通过直接返回错误，不进入 Skill 流程。

## 委托

使用 Skill `<skill-name>` 的 `<动作>` 流程。
```

## 正面示例

见 `.claude/commands/requirement/new.md`（Phase 2 创建）。

## 反面：Command 不应该做的事

- 直接写业务逻辑（应该在 Skill 里）
- 直接调用多个 Agent 编排（应该在 Skill 里）
- 定义数据结构、模板、规则（应该在 Skill 的 reference/ 里）
