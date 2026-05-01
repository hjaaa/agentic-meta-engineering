# 跨项目经验索引

随团队开发经验积累，每条沉淀为一个 Markdown 文件。

## 已沉淀

- [`squash-merge-archive-needs-second-pr.md`](squash-merge-archive-needs-second-pr.md) — PR squash merge 后归档信息（phase=completed / completed_at）必须开二次 chore PR，因为 mergedAt 只能合并后取
- [`traceability-gate-error-code-tc-coverage.md`](traceability-gate-error-code-tc-coverage.md) — `development → testing` 门禁易暴露错误码 TC 缺口；开发期同步加 TC 是主防线，门禁是兜底
- [`spec-drift-consumer-aligns-with-producer.md`](spec-drift-consumer-aligns-with-producer.md) — 规范说 X 在路径 P 但工具写到 Q 时，改消费方对齐产出方，不反向搬位置
- [`ai-skips-realtime-notes-during-flow.md`](ai-skips-realtime-notes-during-flow.md) — auto mode 下 AI 推进流程时易漏 `/note`，process.txt 流水给假阳性安心感；需流程嵌入 / hook 强校验 / SessionEnd 兜底
- [`hook-self-import-deadlock.md`](hook-self-import-deadlock.md) — PreToolUse hook 自身 import 被门禁的代码会形成死锁；syntax pre-check + fail-open 是出路（已落 design-guidance/hook-fail-open.md）
- [`squash-merged-branch-cannot-be-rebased.md`](squash-merged-branch-cannot-be-rebased.md) — feature 分支被 squash-merge 后保留继续开发，再开 PR 必须用 merge / --skip-rebase；rebase 必撞冲突
- [`long-shell-commands-paste-pitfall.md`](long-shell-commands-paste-pitfall.md) — AI 给用户的终端命令避免反斜杠续行 / 超长单行；zsh 粘贴切碎易把数据文件当命令执行报 permission denied
- [`canonical-phase-enum-fail-closed.md`](canonical-phase-enum-fail-closed.md) — phase typo（如 'technical-research'）通过门禁 vacuous pass 静默放行；用 phase_enum.py 单一事实源 + 三层 fail-closed 拦
- [`edit-order-locks-hook-chain.md`](edit-order-locks-hook-chain.md) — 改 hook 链文件先加调用后加定义会让 NameError 锁死工具链；先定义后调用 / 或 try/except 临时包
- [`dry-run-sourcing-before-reviewer.md`](dry-run-sourcing-before-reviewer.md) — 设计文档落盘后先 dry-run GATE-SOURCING 再调 reviewer，避免 R005 hash drift 重审多走一轮
- [`refactor-grep-old-symbols-and-cli-flags.md`](refactor-grep-old-symbols-and-cli-flags.md) — 重构核心模块改函数名/CLI 必填参数后必须全仓 grep 旧符号；review scope 子集会漏 stale 测试
- [`circular-import-stub-binding.md`](circular-import-stub-binding.md) — `try/except ImportError` 兜底循环导入会让模块永久绑定 stub，规则静默失效；解法是消除循环（重排 import 顺序）+ 回归测试
- [`schema-rule-upgrade-needs-migration-plan.md`](schema-rule-upgrade-needs-migration-plan.md) — schema/CR 规则升级前必须明确数据迁移路径或 legacy escape，否则破坏历史已 completed 需求的 CI
- [`lint-rule-spec-vs-derived-docs.md`](lint-rule-spec-vs-derived-docs.md) — lint 规则按文档性质分层：spec 文档强校验 / 衍生文档（tasks/reviews/test-report）豁免，避免 source 责任错位

## 什么值得沉淀

仅当以下条件至少一条成立时创建经验文档：

- 跨项目重复出现的知识
- AI 反复犯同类错误的场景
- 跨会话/跨人需要保留的状态

## 反面：不要沉淀的

- 偶发问题（只踩过一次）
- 简单自然对话就能传递的信息
- 只对单个需求有价值的细节（留在该需求的 `notes.md`）

## 格式约定

每份文件：
- 文件名 `kebab-case.md`，描述具体场景（如 `mysql-lock-wait-timeout-in-long-transaction.md`）
- 正文不超过 200 字
- 必须包含：问题、根因、解法、验证方法
