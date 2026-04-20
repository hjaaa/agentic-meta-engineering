---
description: Agentic 工程上手引导——MCP 配置、常用流程、FAQ
argument-hint: "[topic]（可选，如 mcp / requirement / review / 空=默认）"
---

## 用途

新人上手，或老用户忘了某个流程时，快速查阅。

## 预检

无。

## 行为

不委托 Skill。根据参数输出引导内容（< 800 字）：

### 无参数（默认）

输出：

- **核心链接**（按顺序读）：
  - 入门：`context/team/onboarding/agentic-engineer-guide.md`
  - 8 阶段学习路径：`context/team/onboarding/learning-path/`
  - 设计文档：`context/team/engineering-spec/specs/`
- **3 个最常用命令**：
  - `/requirement:new <标题>` — 开始新需求
  - `/code-review` — 多 Agent 并行审查
  - `/note <内容>` — 随手记录
- **有问题就 `/agentic:feedback <type> <target> <body>`**

### topic=mcp

读 `.mcp.json`，列出已启用 MCP；参考 `learning-path/01-environment.md` 里的配置指引，引导用户如何补充。

### topic=requirement

列 7 个 `/requirement:*` 命令及简短用途说明。

### topic=review

介绍 `/code-review` 双模（独立 / 嵌入）+ 7 个 checker 维度名。

## 硬约束

- 输出 < 800 字
- 不执行任何改文件动作（纯只读 + 输出）
