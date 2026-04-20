# 项目级 Claude Code 指令

本仓库是 Agentic Engineering 工程骨架。克隆即具备骨架能力，按 `context/team/onboarding/agentic-engineer-guide.md` 上手。

## 四条硬原则

1. **文档即记忆**：人和 AI 读同一份 Markdown
2. **位置即语义**：路径承载分类信息，不依赖元数据
3. **渐进式披露**：入口轻量，按需检索。禁止盲目 glob 全部 `context/`
4. **工具封装知识，不封装流程**

详见 @context/team/engineering-spec/design-guidance/context-engineering.md

## 通信与代码规范

- 沟通与说明：简体中文
- 代码注释：简体中文
- 遵循用户全局 CLAUDE.md §0（小步提交 / 不确定就问）

## 和 AI 协作的基本法

@context/team/ai-collaboration.md

## 团队规范

- Git：@context/team/git-workflow.md
- 工具链：@context/team/tool-chain.md

## 体系自身

- 设计指导：`context/team/engineering-spec/design-guidance/`（四层架构 / 上下文工程 / 复利工程）
- 工具规范：`context/team/engineering-spec/tool-design-spec/`（Command / Skill / Subagent）
- 迭代 SOP：`context/team/engineering-spec/iteration-sop.md`
- 完整设计：`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md`

## 记忆检索优先级（universal-context-collector 遵循）

```
1. context/project/<当前项目>/*
2. context/project/<当前项目>/INDEX.md
3. context/team/engineering-spec/
4. context/team/*
5. 历史 requirements/*/artifacts/
6. 外部 WebSearch / WebFetch（设计阶段禁用）
```

## 未实现清单（骨架留白）

以下是文章原版有、本骨架**暂不实现**的能力，避免 Agent 假设它们存在：

### Command 缺口（12 个）

全为文章原版中对应内部业务的命令，本骨架未迁移。

### Skill 缺口（17 个）

- 业务配置生成类（如 `config-gen-engine`）
- `managing-code-review`（伞形） — 当 `/code-review` 逻辑超 100 行时加
- `mcp-setup-guide`
- `ai-collaboration-primer`
- 其余按"真问题驱动才加"原则

### Agent 缺口（2 个）

文章 5.1 图表之外的阶段级 Agent。本骨架的 20 个已覆盖所有明确图表中的 Agent。

### MCP 缺口

- Jira / 飞书 / DingTalk 替换：未开箱
- 内部 TAPD / iWiki / 企微：无法外部重建

## 开发中阶段状态

当前 Phase 1 完成：基础设施 + 上下文文档。
Phase 2（Commands + Skills）和 Phase 3（Agents）未开始。

- [ ] Phase 2 — Commands 16 个 + Skills 10 个
- [ ] Phase 3 — Agents 20 个
- [ ] Phase 4 — 集成验收（跑通一个小需求）

## 反馈

`/agentic:feedback`（Phase 2 后可用）写入 `context/team/feedback-log.yaml`。
