# 骨架路线图

> 最近更新：2026-04-21

项目当前能力快照 + 尚未实现的缺口。给贡献者看，不是 AI 运行时上下文。

## 当前能力清单

Phase 1-4 已完成（截至 2026-04-21，REQ-2026-001 端到端验收通过）。

- Commands：16 个（`.claude/commands/`，含 `requirement:* / knowledge:* / agentic:* / code-review / note`）
- Skills：10 个（`.claude/skills/`）
- Agents：21 个（`.claude/agents/`）
- Hooks：3 个（`protect-branch` / `auto-progress-log` / `stop-session-save`）
- MCP：见 `.mcp.json.example`（候选：context7、chrome-devtools；默认不启用，按需 `cp` 为 `.mcp.json`）

> 数字以目录实际内容为准。本清单是快照，腐化时以目录为唯一事实源。

## 未实现清单（骨架留白）

以下是文章原版有、本骨架**暂不实现**的能力。

### Command 缺口（11 个）

全为文章原版中对应内部业务的命令，本骨架未迁移。`/requirement:submit` 已于 2026-04-21 落地，不在缺口之列。

### Skill 缺口（17 个）

- 业务配置生成类（如 `config-gen-engine`）
- `managing-code-review`（伞形） — 当 `/code-review` 逻辑超 100 行时加
- `mcp-setup-guide`
- `ai-collaboration-primer`
- 其余按"真问题驱动才加"原则

### Agent 缺口（2 个）

文章 5.1 图表之外的阶段级 Agent。本骨架的 21 个已覆盖所有明确图表中的 Agent（含 Phase 4 新增 `history-context-checker`）。

### MCP 缺口

- Jira / 飞书 / DingTalk 替换：未开箱
- 内部 TAPD / iWiki / 企微：无法外部重建
