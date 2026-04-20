# AgenticMetaEngineering

基于 Claude Code 的团队级 Agentic Engineering 工程骨架。`git clone` 即获得全部能力。

## 这是什么

一套让 AI Agent 承担需求全生命周期研发工作的工程体系，对齐文章《认知重建之后，步入 Agentic Engineering 的工程革命》的最终成型版。

核心能力（Phase 1 完成后逐步可用）：

- 8 阶段需求生命周期管理（含强制门禁）
- 多 Agent 并行代码审查（7 专项 checker + 1 综合裁决）
- 三层记忆系统（工作 / 溢出 / 长期）与跨会话恢复
- 团队知识沉淀与复利
- 保护分支 Hook / StatusLine / 开箱即用的 MCP

## 快速开始（新人 30 分钟）

1. 克隆仓库：`git clone <repo-url>`
2. 读 30 秒版入门：`context/team/onboarding/agentic-engineer-guide.md`
3. 依次完成前 6 阶段学习：`context/team/onboarding/learning-path/01-environment.md` → `06-knowledge-sinking.md`
4. 遇到问题运行 `/agentic:help`

## 设计文档

- 骨架设计：`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md`
- 体系自身规范：`context/team/engineering-spec/`
- 迭代方式：`context/team/engineering-spec/iteration-sop.md`

## 反馈

运行 `/agentic:feedback`，会追加到 `context/team/feedback-log.yaml`。

## 目录结构

完整结构见设计文档第 2 节。简要：

- `.claude/` — Claude Code 扩展（Command / Skill / Agent / Hook / StatusLine）
- `context/` — 知识库（team / project / engineering-spec）
- `requirements/` — 需求产出物（全部入库）
- `.mcp.json` — MCP 配置（公开 MCP 开箱，内部 MCP 占位）
