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
- **两条协作路径**（不确定走哪条 → `/agentic:help fast-path`）：
  - **直通分支**：单文件 bug / 工具补丁 / 文档润色 → `git checkout -b feat/xxx` + `/code-review` + PR
  - **完整需求**：跨文件 / 新功能 / 架构影响 / 需追溯 → `/requirement:new <标题>` → 8 阶段
- **3 个最常用命令**：
  - `/requirement:new <标题>` — 开始新需求（完整路径）
  - `/code-review` — 多 Agent 并行审查（两条路径都用）
  - `/note <内容>` — 随手记录到当前需求

### topic=mcp

优先读 `.mcp.json`（若用户已从 `.mcp.json.example` 复制启用）；若不存在则读 `.mcp.json.example` 列出候选 MCP 并提示"默认未启用，需要时 `cp .mcp.json.example .mcp.json`"。参考 `learning-path/01-environment.md` 里的配置指引。

### topic=requirement

列 7 个 `/requirement:*` 命令及简短用途说明。

### topic=review

介绍 `/code-review` 双模（独立 / 嵌入）+ 8 个 checker 维度名 + `review-critic` 对抗验证 + `code-quality-reviewer` 作为 Judge 的三方裁决。

### topic=fast-path

两条路径选择指南（详见 `context/team/onboarding/agentic-engineer-guide.md` 的"选哪条路径？"）：

**直通分支**（小改动、工具补丁、文档润色）：
- `git checkout -b feat/xxx` → 改 → `git commit` → `/code-review` → `gh pr create`
- 不建 `requirements/<id>/`；审查报告写 `/tmp/code-review-*.md`
- 不用 `/requirement:*` 命令

**完整需求**（跨文件 / 新功能 / 架构影响 / 需追溯）：
- `/requirement:new <标题>` → 8 阶段推进 → `/code-review` → `/requirement:submit`
- 产出 `requirements/<REQ-ID>/` 全量 artifacts

**选择三问**（三个都不需要 → 直通；任一需要 → 完整需求）：
1. 跨会话恢复？（换台机器明天还要继续同一件事）
2. 设计评审？（需要 outline / detail-design 阶段产出）
3. 追溯链？（需求 → 设计 → 代码 → 测试的四层引用）

**误判了怎么办**：
- 选了直通分支但发现越改越大 → 停手，`/requirement:new` 把现有分支接到需求流程
- 选了完整需求但发现其实是小改动 → `/requirement:rollback` 归档草稿，按直通分支继续

## 硬约束

- 输出 < 800 字
- 不执行任何改文件动作（纯只读 + 输出）
