# Changelog

本文件记录 Agentic Engineering 骨架仓库的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.3.0] - 2026-05-07

围绕"代码审查闭环 + 门禁系统统一与加固 + 需求生命周期"三条主线补强骨架能力，34 个 PR 累计沉淀。

### Features

#### 代码审查（reviewer verdict 结构化 + 人类卡点）

- **reviewer verdict 结构化（PR1-PR4）** — 统一 reviewer 输出 schema：基础设施（#36）→ 试点 requirement-quality-reviewer（#38）→ 全量切换 + D7 写保护（#40）→ CI 升 strict + 历史治理（#42）
- **代码审查人类必经卡点（REQ-2026-003）** — 路由确认 + 结论 sign-off 双闭环（#48），tty 双校验 + trivial 路径白名单 + schema 校验
- **submit Codex review-loop + archive 命令（REQ-2026-007）** — `/requirement:submit` 默认走 Codex review-loop；新增 `/requirement:archive` 命令做 PR-merged 后收尾闭环（#57）

#### 门禁系统统一与加固

- **统一门禁系统（REQ-2026-002）** — F-001/F-002 统一注册中心（#44）；F-003 关闭 H1/H3/H4/H5 + F-004 渲染产物化与旧入口删除（#45）
- **门禁系统加固 - 10 项缺陷修复（REQ-2026-005）** — 一次性收敛历史遗留缺陷（#50）
- **门禁系统 A+B 重构（REQ-2026-006）** — pre-tool-use 热路径解耦 + 全局逃生 + 异步 audit（#54）
- **archive 预检 5 强校验** — `lessons_extracted=true` 由脚本保障（#63）

#### 需求生命周期

- **会话结束经验提取 Hook（REQ-2026-001）** — Stop hook 自动触发经验提取写入 `context/team/experience/`（#32）
- **派发链强制结构化升级（REQ-2026-008）** — features.json `touches` 必填 + dispatch_precheck.py 拦截 + 写时校验防 RMW 丢失（#60）

### Bug Fixes

- **阻止 reviewed_artifacts 包含 meta.yaml 自引用** — 防止 R005 自引用循环（#47）

### Documentation

- 门禁体系盘点 + reviewer verdict 结构化设计与 PR1 plan（#35）
- 门禁系统 A+B 重构 spec + 实施计划（#53）
- 固化 PR-merged 后 archive 时机与分支位置约束（#61）
- reviewer verdict PR1-PR4 plan 归档到 history（#37, #39, #41, #43）

### Experience（经验沉淀）

- REQ-2026-005 复盘 5 条 / REQ-2026-006 复盘 4 条 / REQ-2026-007 复盘 3 条 / REQ-2026-008 复盘 3 条 / REQ-2026-001 跨需求经验 4 条
- 全部沉淀到 `context/team/experience/`，供后续需求复用

### Upgrade Notes

- **下游仓库感知**：reviewer verdict CI 已升 strict 模式，PR 提交前需本地跑一遍 `check-sourcing.sh --strict`
- **archive 流程变更**：PR merge 后必须经 `/requirement:archive` 走收尾（lessons_extracted + 删本地+远程分支提示），不再有手动路径
- **派发链 touches 强制**：阶段 7 实现 feature 时 `touches` 字段必填，否则 dispatch_precheck 会拒绝派发

**完整变更**：https://github.com/hjaaa/agentic-meta-engineering/compare/v1.2.0...v1.3.0

[1.3.0]: https://github.com/hjaaa/agentic-meta-engineering/releases/tag/v1.3.0

## [1.2.0] - 2026-04-24

围绕"阶段 7 subagent 化"补强开发实施能力，并对溢出区做 Hook 级清理。

### Features

- **阶段 7 引入 subagent 实现派发（保守档）** — 开发实施从"主 Agent 亲自做"升级为"派 fresh implementer subagent 做"。串行不并发；按 `complexity` 选模型档位（haiku / sonnet / opus）；按 `depends_on_features` 校验前置；DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED 四态回执契约
- **features.json schema 扩展** — 新增 `interfaces_frozen` / `depends_on_features` / `depends_on_modules` / `touches` / `complexity` / `shared_resources` 可选字段，给派发决策提供机读入口；旧 `dependencies` 标 deprecated 作回退

### Refactor

- **溢出区三文件重定义** — 删除 `auto-progress-log.sh` / `stop-session-save.sh` 两个 Hook 及其测试，下线 `process.tool.log` 日志通道（详见 PR #26）

### Upgrade Notes

- 旧 `features.json`（只有 `id/title/description/interfaces/dependencies`）仍合法，必填门禁未变
- 新字段缺失时派发策略退化为保守默认（`medium + sonnet + 串行`）
- 下游 sync 骨架的仓库需感知 Hook 变化：如引用过 `auto-progress-log.sh` / `stop-session-save.sh`，需要相应调整

**完整变更**：https://github.com/hjaaa/agentic-meta-engineering/compare/v1.1.0...v1.2.0

[1.2.0]: https://github.com/hjaaa/agentic-meta-engineering/releases/tag/v1.2.0

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
