# 项目级 Claude Code 指令

本仓库是 Agentic Engineering 工程骨架。克隆即具备骨架能力，按 `context/team/onboarding/agentic-engineer-guide.md` 上手。

## 常用入口

| 想做什么 | 用什么 |
|---|---|
| 开一个新需求 | `/requirement:new <标题>` |
| 恢复之前的需求 | `/requirement:continue` |
| 看当前阶段/进度 | `/requirement:status` |
| 做代码审查 | `/code-review` |
| 提 PR | `/requirement:submit` |

全量命令见 `.claude/commands/`；详细 SOP 见 `context/team/onboarding/agentic-engineer-guide.md`。

## 四条硬原则

1. **文档即记忆**：人和 AI 读同一份 Markdown
2. **位置即语义**：路径承载分类信息，不依赖元数据
3. **渐进式披露**：入口轻量，按需检索。禁止盲目 glob 全部 `context/`
4. **工具封装知识，不封装流程**

详见 @context/team/engineering-spec/design-guidance/context-engineering.md

## 通信与代码规范

- 沟通与说明：简体中文
- 代码注释：简体中文

## 和 AI 协作的基本法

@context/team/ai-collaboration.md

## 团队规范

- Git：@context/team/git-workflow.md
- 工具链：@context/team/tool-chain.md

## 体系自身

- 设计指导：`context/team/engineering-spec/design-guidance/`（四层架构 / 上下文工程 / 复利工程）
- 工具规范：`context/team/engineering-spec/tool-design-spec/`（Command / Skill / Subagent）
- 迭代 SOP：`context/team/engineering-spec/iteration-sop.md`
