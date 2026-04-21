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

## 骨架能力清单

Phase 1-4 已完成（截至 2026-04-21，REQ-2026-001 端到端验收通过）。

- Commands：16 个（`.claude/commands/`，含 `requirement:* / knowledge:* / agentic:* / code-review / note`）
- Skills：10 个（`.claude/skills/`）
- Agents：21 个（`.claude/agents/`）
- Hooks：3 个（`protect-branch` / `auto-progress-log` / `stop-session-save`）
- MCP：见 `.mcp.json`（默认启用 context7、chrome-devtools 等）

## Common Pitfalls

> 最近更新：2026-04-21

<!-- @feature:F-001 -->

新人使用骨架时最容易踩的 7 个坑。每条按「症状 / 原因 / 修复」三段式。

### 1. 在 main / develop 分支直接 Edit 被 Hook 拦截
- **症状**：执行 Edit / Write 工具报错 "禁止在受保护分支..."
- **原因**：`.claude/hooks/protect-branch.sh` 对 Edit/Write 在 **main / master / develop** 分支做阻塞
- **修复**：切到 feature 分支再操作，或运行 `/requirement:new` 自动建分支（默认从 develop 派生）

### 2. `/note` 后 notes.md 没更新
- **症状**：跑完 `/note` 后 ls 不到对应文件的新行
- **原因**：当前分支没匹配到 `requirements/*/meta.yaml` 的 branch 字段
- **修复**：先 `/requirement:new` 或 `/requirement:continue` 绑定到某个需求

### 3. Command 超过 100 行或 SKILL.md 超过 2k token
- **症状**：新写的 Command / Skill 行为不稳定
- **原因**：违反 `context/team/engineering-spec/tool-design-spec/` 的硬约束
- **修复**：Command 拆到委托 Skill；Skill 内容拆到 `reference/`

### 4. 需求文档写了"看起来合理"但无来源的事实
- **症状**：`requirement-quality-reviewer` 返回 `needs_revision`
- **原因**：违反刨根问底三态（有引用 / 待确认 / 待补充），出现了第四态"无来源但合理"
- **修复**：按 `.claude/skills/requirement-doc-writer/reference/sourcing-rules.md` 补标注

### 5. /code-review 审查范围 > 2000 行被拒绝
- **症状**：`/code-review` 预检阶段终止并提示"范围过大"
- **原因**：`code-review-prepare` 硬约束不审超 2000 行 diff
- **修复**：按 feature_id 拆分提交，或 `/requirement:rollback` 回前阶段重新拆

### 6. PR 目标分支错选 main
- **症状**：`/requirement:submit` 开出的 PR target 是 main，绕过了 develop 的集成验证
- **原因**：`meta.yaml.base_branch` 缺失或被手动改成 main；或仓库尚未启用 develop 分支
- **修复**：
  - 仓库未启用 develop：按 `context/team/git-workflow.md` "首次启用 develop" 小节执行
  - 已启用：`/requirement:submit --target develop` 显式指定，或修正 `meta.yaml.base_branch`

### 7. `/requirement:submit` 反复失败说 "无审查报告"
- **症状**：预检报 `artifacts/code-review-reports/` 为空
- **原因**：尚未跑过 `/code-review`，或报告落在了其他路径
- **修复**：先 `/code-review` 生成报告，确认路径为 `artifacts/code-review-reports/*.md`

## 反馈

`/agentic:feedback` 写入 `context/team/feedback-log.yaml`。
