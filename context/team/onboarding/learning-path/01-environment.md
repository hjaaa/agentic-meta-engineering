# Stage 1 · 环境准备

**完成时间**：15-30 分钟
**前置**：无
**可验证动作**：`claude /agentic:help` 在本仓库能正常输出

## 目标

装好 Claude Code，跑通一次"读文件→改文件→运行命令"的闭环。

## 步骤

1. 装 Claude Code CLI（参考官方文档）
2. 配置 `ANTHROPIC_API_KEY`（或通过登录流程）
3. 克隆本仓库：`git clone <repo-url> && cd agentic-meta-engineering`
4. 运行 `claude` 进入会话
5. 输入：`读一下 README.md 告诉我这个仓库是做什么的`
6. 输入：`状态行显示了什么？`

## 环境依赖

骨架的 Hook / 门禁脚本依赖以下 Python 包：

```bash
pip install pyyaml
```

无 pyyaml 时 meta.yaml 解析会失败，门禁脚本会报错。Homebrew 或系统 Python 都可安装。

## MCP 配置（可选）

本仓库默认**不启用**任何 MCP，避免 `git clone` 后被动触发 `npx` 拉包和 Chromium 下载。仓库提供 `.mcp.json.example` 作为候选配置模板，当前包含：

- `context7` — 库文档检索（补训练数据滞后）
- `chrome-devtools` — 浏览器自动化（UI 测试，首次使用会拉 Chromium）

启用步骤：

1. `cp .mcp.json.example .mcp.json`（已 gitignore，个人裁剪不影响他人）
2. 按需保留/删除 `mcpServers` 下的条目
3. 重启 Claude Code，首次会话按提示批准 MCP

其他 MCP（Jira / 飞书 / 企业 Wiki）未配置，需要时：获取对应 Server → 加到本地 `.mcp.json` → 重启。**团队共享配置若要变更候选列表，改 `.mcp.json.example` 并 PR**。

## 完成标志

- [ ] `claude` 能启动且状态行显示
- [ ] 能让 AI 读文件
- [ ] 知道 `.mcp.json.example` 是 MCP 模板，`.mcp.json` 是本地启用态
