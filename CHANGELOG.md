# Changelog

本文件记录 Agentic Engineering 骨架仓库的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-04-23

首个正式版本。把 Agentic Engineering 的核心工作流完整落地成可直接 `git clone` 使用的骨架。

### Features

- **8 阶段需求生命周期** — `/requirement:new` / `next` / `continue` / `status` / `save` / `submit` / `rollback` / `list`，覆盖从初始化到测试验收全流程
- **多 Agent 并行代码审查** — `/code-review` 并行跑 8 个专项 checker（design-consistency / complexity / concurrency / error-handling / performance / security / history-context / traceability-consistency），`review-critic` 对抗验证，`code-quality-reviewer` 综合裁决（Judge 模式）
- **上下文工程骨架** — `context/team/` 团队通用 + `context/project/<X>/` 项目专属 + `requirements/<id>/artifacts/` 单需求全周期产出；INDEX.md 渐进式披露
- **知识管理** — `/knowledge:*`（extract-experience / generate-sop / generate-checklist / optimize-doc / organize-index）
- **Fast-path 双路径** — 小改动走直通分支，复杂需求走 8 阶段
- **Hook 自动机制** — `protect-branch` / `auto-progress-log` / `stop-session-save`
- **校验脚本与门禁** — `check-meta` / `check-index` / `check-sourcing`（刨根问底三态规则）/ `post-dev-verify`（开发后总门禁）；pre-commit hook + CI 兜底
- **meta-schema 扩展** — meta.yaml 新增语义组 / 结果组字段

### Docs

- 按当前能力重构 README
- CLAUDE.md 精简，补 Hook 说明与仓库布局
- onboarding 学习路径 + common-pitfalls
- engineering-spec 纳入 INDEX/meta 校验设计记录与 roadmap

### Chore

- 下线 StatusLine 脚本、`/agentic:feedback` 命令（系统瘦身）
- `.mcp.json` → `.mcp.json.example`（默认不启用，降低 clone 负担）
- 治理存量 12 条 INDEX warning，CI 切至 `--strict`

### Upgrade

- 新建根目录 `VERSION` 文件，锚定版本号

**完整变更**：https://github.com/hjaaa/agentic-meta-engineering/commits/v1.0.0

[1.0.0]: https://github.com/hjaaa/agentic-meta-engineering/releases/tag/v1.0.0
