# Stage 1 · 环境准备

**完成时间**：15-30 分钟
**前置**：无
**可验证动作**：`claude /agentic:help` 在本仓库能正常输出

## 目标

装好 Claude Code，跑通一次"读文件→改文件→运行命令"的闭环。

## 步骤

1. 装 Claude Code CLI（参考官方文档）
2. 配置 `ANTHROPIC_API_KEY`（或通过登录流程）
3. 克隆本仓库：`git clone <repo-url> && cd agenticMetaEngineering`
4. 运行 `claude` 进入会话
5. 输入：`读一下 README.md 告诉我这个仓库是做什么的`
6. 输入：`状态行显示了什么？`

## MCP 配置（可选）

本仓库默认启用 `context7`（库文档）、`chrome-devtools`（浏览器自动化）。其他 MCP（Jira / 飞书 / 企业 Wiki）未配置，需要时按以下步骤：

1. 获取对应 MCP Server（官方或团队内部分发）
2. 编辑 `.mcp.json`（**团队共享配置，改动要 PR**）或 `.claude/settings.local.json`（个人覆盖）
3. 重启 Claude Code

## 完成标志

- [ ] `claude` 能启动且状态行显示
- [ ] 能让 AI 读文件
- [ ] 知道 `.mcp.json` 在哪
