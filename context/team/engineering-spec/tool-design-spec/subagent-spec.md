# Subagent（Agent）设计规范

**Agent 是独立上下文中的专业同事，不是被动的脚本执行器。**

## 硬约束

| 约束 | 数值 | 理由 |
|---|---|---|
| 返回内容 | < 2k token | 保护主对话上下文不被淹没 |
| 嵌套调用 | **禁止**（Agent 之间不相互调用） | 编排由主 Agent / Skill 完成 |
| 上下文 | 独立（不继承主对话） | 避免信息污染；只看 SKILL.md 里传的输入 |

## 按任务类型分五类

| 类别 | 模型档位 | 示例 |
|---|---|---|
| 初始化类（创建资源） | 轻量（sonnet） | `requirement-bootstrapper` |
| 准备类（收集信息） | 轻量 | `universal-context-collector` |
| 评审类（评估质量） | 高能力（opus） | `requirement-quality-reviewer` / `code-quality-reviewer` |
| 执行类（生成代码） | 中等（sonnet） | 7 个代码审查 checker |
| 维护类（更新文档） | 轻量 | `documentation-batch-updater` |

不同类别推荐不同模型——让一次完整操作既全面又经济。

## 文件位置

```
.claude/agents/<agent-name>.md
```

单文件，frontmatter 里声明 model 和 tools。

## Agent 文件骨架

```markdown
---
name: <agent-name>
description: 一句话。第三方能准确理解什么时候该调用这个 Agent。
model: opus | sonnet | haiku
tools: Read, Grep, Bash, ...
---

## 你的职责

简述。

## 输入

你会收到什么信息。

## 输出契约

必须以什么格式返回。返回 < 2k token。

## 行为准则

- 禁止嵌套调用其他 Agent
- 禁止污染主对话（直接写文件前要明确原因）
- 评审类 Agent 不读源码本身，只读结构化输入（避免重复）
```

## 反面：Agent 不应该做的事

- 返回超长原始数据（切记 < 2k token）
- 调用其他 Agent（让主 Agent 编排）
- 期待"继承"主对话的状态（写清楚你需要什么输入）
- 修改 `.claude/` 或 `context/team/engineering-spec/`（这属于设计层）
