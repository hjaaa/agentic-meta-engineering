# 团队工具链规范

由于团队是多栈环境，本文件只记录**通用工具**约定。语言/框架专属约定请在 `context/project/<项目>/` 下维护。

## 通用

- 所有仓库提供 `README.md`、`.gitignore`、`CLAUDE.md`
- `.mcp.json` 列出该项目使用的 MCP Server
- `requirements/` 目录用于需求管理（见 `requirements/INDEX.md`）

## Git

见 [`git-workflow.md`](git-workflow.md)

## Claude Code

- 入口文件：`CLAUDE.md`（项目级）
- 配置：`.claude/settings.json`（团队共享）+ `.claude/settings.local.json`（个人覆盖，不入库）
- MCP：`.mcp.json` 默认启用 `context7`、`chrome-devtools`
- 自定义能力：`.claude/commands/`（意图入口）+ `.claude/skills/`（知识包）+ `.claude/agents/`（独立同事）

## 语言栈

当前空。新项目第一个需求开发时，由 Agent 沉淀到 `context/project/<项目名>/lang-<语言>.md`。

## 文档与图表

- Markdown（Obsidian / GitHub Flavor）
- 图表：Mermaid 优先（嵌入 Markdown）；复杂图用 excalidraw/draw.io 导出 SVG
