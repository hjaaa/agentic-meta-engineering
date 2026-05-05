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
- [`plugin-multi-trigger-shared-naming-convention.md`](plugin-multi-trigger-shared-naming-convention.md) — plugin 加新触发路径时命名假设要对齐下游产物实际写盘约定；用共享 helper 强制双路径同源
- [`auto-generated-artifact-needs-pre-commit-not-just-ci.md`](auto-generated-artifact-needs-pre-commit-not-just-ci.md) — 「源文件 → 自动生成派生文件 + CI 校验」组合必须挂 pre-commit / pre-submit，CI 兜底太晚浪费 round-trip
- [`r005-hash-drift-deadlock-after-reviewer-signoff.md`](r005-hash-drift-deadlock-after-reviewer-signoff.md) — reviewer sign-off 后改 hash 敏感 spec 文档触发 R005 死循环，需 3 轮重审；优先 ADR/notes 记录而非改文件
- [`perf-baseline-sample-size-jitter-trap.md`](perf-baseline-sample-size-jitter-trap.md) — 性能 baseline 「N 次中位数」模板要先量被测时长量级；ms 级被测项 N≥10 + perf_counter，否则 50ms 抖动会放大成误判
- [`runner-fail-without-stdout-message.md`](runner-fail-without-stdout-message.md) — multi-plugin runner FAIL 必须把 plugin message 渲染到 stderr，不能只写 audit log；CI 看不到原因极拖慢调试
- [`cross-language-pipeline-path-anchor.md`](cross-language-pipeline-path-anchor.md) — bash + Python 混合管道默认锚定语义不同，producer/consumer 在 cwd vs `__file__` 间分叉时审计静默丢；显式声明锚定 + env override + cwd≠root 回归用例
- [`code-deletion-breaks-archival-references.md`](code-deletion-breaks-archival-references.md) — 删除被档案需求引用的代码会触发 CI 全量 sourcing 回归；checker 对 `phase=completed` 区按"档案冻结"语义豁免
- [`local-pass-vs-ci-pass-rounds.md`](local-pass-vs-ci-pass-rounds.md) — 本地全过 vs CI 5 轮修复（git config / defaultBranch / ruff / auto-render 同步）；submit 前必跑本地 CI 模拟清单 + 测试 fixture 自给自足
- [`external-ai-reviewer-finds-internal-blindspots.md`](external-ai-reviewer-finds-internal-blindspots.md) — 8 内部 checker + critic + judge 全 pass 后 Codex 仍抓 P1（跨语言路径 / hook cwd 假设）；外部 AI reviewer 是互补层不是冗余
- [`archive-completed-triggers-framework-rule-fullset.md`](archive-completed-triggers-framework-rule-fullset.md) — `phase=completed` 触发 framework R-rule / conditional_required 全集；testing 阶段沉默的 schema 缺口都在 archive 实跑才集中暴露（F-17 outcome/completed_at + 缺失 definition review 即此规律实例）
- [`ai-bot-pass-signal-not-in-documented-channel.md`](ai-bot-pass-signal-not-in-documented-channel.md) — codex info 文本说 pass 时「react with 👍」，实测发 issue comment；轮询必须多端点 OR 语义（reviews ∪ issue_comments），否则 pass case 永远 timeout
- [`github-api-head-syntax-fork-across-surfaces.md`](github-api-head-syntax-fork-across-surfaces.md) — `gh pr list --head` 不支持 `OWNER:BRANCH`，但 `gh api .../pulls?head=` 原生支持；`gh` 各子命令是独立薄包装，跨 surface 必须分别看 manual

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
