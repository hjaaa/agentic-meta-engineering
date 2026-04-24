# Changelog

本文件记录 Agentic Engineering 骨架仓库的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1.0] - 2026-04-24

围绕"可追溯的时间语义 + 下游仓库同步路径"补强骨架能力。

### Features

- **时间格式统一** — 所有写入（process.txt / notes.md / meta.yaml 等）统一 `YYYY-MM-DD HH:MM:SS` + `Asia/Shanghai` 时区，跨脚本/跨 Hook 一致
- **工具日志分层** — 工具级自动日志从 `process.txt` 拆出到 `process.tool.log`（v2 布局，不入 git），`process.txt` 回归"语义事件追加"职责；时间戳规范同步下沉
- **plan.md 软校验门禁** — 阶段切换前对 `plan.md` 结构/必填项做软校验，缺失项提示但不阻断，避免重流程把小改动拖重

### Bug Fixes

- **INDEX 引用修正** — 把 `time-format.md` 加入 `engineering-spec/INDEX.md`，消除 `check-index --strict` 告警

### Docs

- **下游同步指南** — 新增 `syncing-from-skeleton.md`，指导使用骨架的下游仓库如何升级；补全受管目录清单
- **upstream 语义澄清** — onboarding 明确"骨架仓库自身不需配置 upstream"的边界
- **git-workflow 强化** — 显性化"从 develop 切分支"的标准动作，补误切 main/master 的救急方案

**完整变更**：https://github.com/hjaaa/agentic-meta-engineering/compare/v1.0.0...v1.1.0

[1.1.0]: https://github.com/hjaaa/agentic-meta-engineering/releases/tag/v1.1.0

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
