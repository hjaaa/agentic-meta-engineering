# Stage 3 · 三级工具的区别与选型

**完成时间**：30 分钟
**前置**：Stage 2 完成
**可验证动作**：读完本文能回答"什么时候用 Command / Skill / Agent"

## 三级区别

| 类型 | 上下文影响 | 场景 |
|---|---|---|
| Command | 极小（< 100 行进入主对话） | 固定操作的意图快捷入口 |
| Skill | 可控（SKILL.md < 2k token 进入主对话） | 需要领域知识的标准化工作流 |
| Agent | 隔离（独立上下文，返回 < 2k token） | 产生大量输出或独立探索的任务 |

## 决策树

```
任务会产生大量输出或需要多轮独立探索？
├── 是 → Agent
└── 否 → 需要领域知识或多步流程？
         ├── 是 → Skill
         └── 否 → 高频且固定？
                  ├── 是 → Command
                  └── 否 → 不工具化，写在规范里
```

## 伞形模式

同一领域的多个 Command（如 7 个 `/requirement:*`）委托**同一个**伞形 Skill（`managing-requirement-lifecycle`）。这是为了：

- 领域知识集中在一处
- 改一条规则只改一个 Skill
- Command 只做薄层（< 100 行）

## 阅读作业

- `context/team/engineering-spec/tool-design-spec/command-spec.md`
- `context/team/engineering-spec/tool-design-spec/skill-spec.md`
- `context/team/engineering-spec/tool-design-spec/subagent-spec.md`

## 完成标志

- [ ] 能用决策树给任一虚构场景选型
- [ ] 理解"伞形模式"的必要性
