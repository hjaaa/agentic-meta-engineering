---
id: REQ-2026-003
title: 代码审查人类必经卡点（路由确认 + 结论 sign-off）
created_at: 2026-04-29T17:07:36+08:00
refs-requirement: true
---

# REQ-2026-003 · 代码审查人类必经卡点（路由确认 + 结论 sign-off）

## 背景

当前 `/code-review` 流水线的全部环节由 AI 完成，等于 **AI 给自己写的代码盖章通过**。具体表现：

- `code-review-prepare` 由 AI 单方决定要跑哪些 checker、跳过哪些（来源：.claude/skills/code-review-prepare/SKILL.md:11）
- 8 个 checker 并行执行后，`code-quality-reviewer` 直接给 `approved / needs_revision / rejected` 三档结论（来源：.claude/agents/code-quality-reviewer.md:200）
- `feature-lifecycle-manager` 把 feature 状态从 in-progress 推到 done 时，仅看 AI 给的 `conclusion`，不查任何人类签字字段（来源：.claude/commands/code-review.md:50）
- `verdict` schema 中没有任何字段承载"人类签字"语义（来源：scripts/lib/save_review.py:178）

这与 `context/team/ai-collaboration.md` 主张的"AI 是辅助、人类负责最终交付"原则相悖（来源：context/team/ai-collaboration.md:17）。

## 目标

- **主目标**：给 `/code-review` 流水线引入两道人类必经卡点，把"该跑哪些 checker"与"是否通过"两个决策权显式收回给人类
- **次要目标**：
  - 让审查流程的人类介入点可被门禁（脚本 + CI）强制执行，不依赖纸面规范
  - 保留 AI 的全部辅助能力（建议路由、机器评估），但剥离其"自我盖章"能力
  - 与现有 8 阶段需求生命周期 + GATE-REVIEW-VERDICT 门禁兼容

## 用户场景

### 场景 1：feature 完成后的嵌入式代码审查

- **角色**：开发者（人类）+ feature-lifecycle-manager（AI）+ /code-review 各 Agent
- **前置**：当前需求处于 `development` 阶段，某个 feature 编码完成、流转到 in-progress→done 时自动触发 `/code-review`
- **主流程**：
  1. `code-review-prepare` 扫描 diff，输出"推荐跑 N 个 checker / 跳过 M 个 + 跳过原因"
  2. **主对话停顿，等开发者回应**：可选 `继续 / 全跑 / 自定义列表`
  3. 写最终 `.review-scope.json`（含 `routing_confirmed_by: { by: <git_user_email>, at: <ISO8601>, decision: continue|all|custom }` 字段记录确认人 / 时间 / 决定）
  4. 并行跑选中的 checker → critic → judge
  5. judge 输出三档评估之一（`looks_clean / needs_attention / blocked`），写入 verdict（`human_signoff: null`）
  6. 主对话提示："请执行 `/code-review:signoff <decision>`"
  7. 开发者读完报告，执行 `/code-review:signoff approve`（CLI 校验 tty）
  8. `human_signoff` 字段被写入 verdict
  9. feature-lifecycle-manager 校验 `human_signoff.decision ∈ {"approved", "approved-trivial"}` → 允许转 done
- **期望结果**：feature 转 done 必须经过两次人类介入（路由确认 + 结论 sign-off），任一缺位则阻断

### 场景 1b：纯文档变更走 trivial 快速通道

- **角色**：开发者（人类）
- **前置**：feature 编码完成，diff 中所有文件路径全部命中白名单（`*.md` / `docs/**` / `*.txt`）
- **主流程**：
  1. 走完场景 1 第 1-5 步（路由确认 + checker 并行 + judge 出三档评估）
  2. 开发者执行 `/code-review:signoff --trivial`（无需对话式 prompt）
  3. CLI 校验 diff 路径白名单：全命中则写 verdict（`human_signoff.decision = "approved-trivial"`，by/at 同 tty 路径），退出码 = 0；非全命中则拒绝（退出码 = 3，stderr 含 `trivial: non-doc files detected`）
  4. feature-lifecycle-manager 校验 `human_signoff.decision ∈ {"approved", "approved-trivial"}` → 允许转 done（与场景 1 第 9 步同口径，trivial 通道下 `approved-trivial` 视同放行）
- **期望结果**：纯文档变更下 sign-off 步骤无需 tty 交互即可通过，但仍留 verdict 审计痕迹（by 字段记录触发人）

### 场景 2：独立模式手动审查

- **角色**：开发者（人类）
- **前置**：开发者在某个分支上手敲 `/code-review`（无关联需求）
- **主流程**：与场景 1 一致，但 `human_signoff` 不阻断需求生命周期（独立模式无 feature-lifecycle-manager 接入）；CLI 仍要求 sign-off 才生成"已签结报告"
- **期望结果**：即使在独立模式下，AI 也无法直接产出"approved"结论；最终结论必须由开发者本人签字

### 场景 3：AI 试图代签（必须被阻断）

- **角色**：AI（主 Agent / 子 Agent）
- **前置**：AI 在 non-interactive 环境（Hook / CI / 子 Agent shell）尝试调用 `save-review.sh signoff`
- **期望结果**：CLI 检测到 stdin 非 tty → **退出码 = 2**（与 schema 校验失败的退出码 1 区分）+ stderr 包含关键串 `signoff: refusing in non-interactive shell (stdin not a tty)`；CI 测试用 `assert exit==2 && stderr =~ /non-interactive shell/` 即可断言；AI 无法走通

## 非功能需求

- **性能**：路由建议生成 ≤ 5 秒（基准：diff < 500 行 / 文件数 < 50）；CLI signoff 写盘 ≤ 1 秒（无外部依赖；基准：单 verdict 文件 < 100 KB）
- **兼容性**：
  - verdict schema 需向后兼容——旧 verdict（无 `human_signoff` 字段）视为"未签字"，feature-lifecycle-manager 升级后强制要求重新 sign-off（来源：requirements/REQ-2026-003/plan.md:62）
  - 与现有 GATE-REVIEW-VERDICT 门禁协同（来源：scripts/gates/registry.yaml:136）：升级该门禁的判定逻辑，从"看 conclusion"改为"看 human_signoff.decision"
- **安全/合规**：
  - sign-off 字段不可被 AI 在非交互环境写入（tty 校验 + 防 ppid 链伪造）
  - 本需求只支持**单一签字路径**：本地 tty CLI sign-off（GitHub PR Review 等价 sign-off 已 out of scope，原因见"范围/不包含"）

## 范围

- **包含**：
  - `code-review-prepare` 流程改为两阶段（建议 → 等确认 → 写盘）
  - `scope-schema.md` 新增 `selected_checkers / skipped_checkers / routing_confirmed_by` 字段
  - **`.claude/agents/code-quality-reviewer.md:200` 同步收敛 `conclusion` 取值为 `looks_clean / needs_attention / blocked`，明文禁止 `approved`**（避免 schema 与 Agent 输出空间漂移）
  - `verdict` schema 新增 `human_signoff: { by, at, decision }` 字段
  - `scripts/lib/save_review.py` 新增 `signoff` 子命令（tty 校验、字段写入、append process.txt）
  - 新建 `.claude/commands/code-review/signoff.md`
  - `code-review-report` 模板加路由说明段 + 待签字提示段
  - `feature-lifecycle-manager` 转 done 门禁查 `human_signoff.decision ∈ {"approved", "approved-trivial"}`
  - `requirement:submit` 提交门禁同上
  - **`scripts/gates/registry.yaml:136` 的 `GATE-REVIEW-VERDICT` 同步升级**：判定逻辑从"看 conclusion"改为"看 human_signoff.decision ∈ {"approved", "approved-trivial"}"（接受集合而非单值，与 D-006 trivial 通道协同；与本次 schema 变更对齐，避免双轨）
  - **`scope-schema.md` / verdict schema 中 `human_signoff.decision` 取值枚举显式定义为 `{"approved", "approved-trivial", "rejected"}`**（trivial 通道引入新取值，schema 必须显式列举，避免下游门禁判定漂移）
  - **`/code-review --all` 兜底标志**：在 `code-review-prepare` 加 `--all` 参数，跳过路由建议直接选全部 8 个 checker；输出契约：`.review-scope.json.selected_checkers` = 全部 8 个 checker 名（complexity / security / concurrency / performance / error-handling / design-consistency / history-context / auxiliary-spec），`skipped_checkers = []`，`routing_confirmed_by = { by: <git_user_email>, at: <ISO8601>, decision: "all" }`
  - **`signoff --trivial` 快速通道**：`save-review.sh signoff --trivial` 允许跳过交互式 sign-off，**仅当** diff 文件全部命中白名单（`*.md` / `docs/**` / `*.txt`）时放行
    - 失败侧：退出码 = 3 + stderr 含 `trivial: non-doc files detected`
    - 成功侧：退出码 = 0 + verdict.human_signoff = `{ by: <git_user_email>, at: <ISO8601>, decision: "approved-trivial" }`（`by` 仍取 git 用户邮箱，便于事后审计是谁触发；与人类签字 `approved` 通过 decision 取值区分）
  - `context/team/engineering-spec/specs/2026-04-29-code-review-human-checkpoints.md` 留档
- **不包含**：
  - 8 个 checker（complexity / security / concurrency / ...）的内部检查规则改造（plan.md:范围/不包含 第 1 条）
  - 共享 checker 输出契约骨架（前一轮审查发现的 P0 问题，下一个独立需求）
  - GitHub PR Review 等价 sign-off（**完全 out of scope**：当前为单人项目无 reviewer，且前置依赖分支保护规则 `require review from someone other than author` 未配置；如未来团队化需要，独立 REQ 处理）

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 卡点数量 | 单卡点（仅审查后）/ 双卡点（审查前 + 审查后）| 双卡点 | 来源：requirements/REQ-2026-003/plan.md:50 |
| AI 是否可输出 approved | 可 / 不可 | 不可 | 来源：requirements/REQ-2026-003/plan.md:58 |
| 防 AI 代签 | 不防 / tty 校验 / PR Review 等价 / 双轨 | 仅 tty 校验（PR Review 等价 out of scope，单人项目无 reviewer 价值；前置依赖分支保护未配置）| 来源：requirements/REQ-2026-003/plan.md:66 |
| 路由建议跳过 → 是否记录 | 不记录 / 记录到 scope-json / 记录到报告 | 同时记录到 scope-json + 报告 | 防止"AI 静默跳过 checker"被发现不了 |
| 旧 verdict 迁移 | 自动转换 / 强制重签 | 强制重签 | 升级即视为门禁规则变更，旧签字不可继承 |
| `--all` 兜底是否本需求实现 | 实现 / 推迟 | 实现 | CLI 改动极小；不实现则纯文档变更也卡两次人，体验极差（来源：requirements/REQ-2026-003/plan.md:83）|
| trivial 通道范围 | 不做 / 仅纯文档 / 文档+重命名+测试 / 自定义 | 仅纯文档（`*.md` / `docs/**` / `*.txt`）| 先严后松；其余场景留待真实抱怨出现再扩（来源：requirements/REQ-2026-003/plan.md:91）|
| 门禁如何识别 trivial verdict | 仅 `approved` / 接受 `{approved, approved-trivial}` 集合 | 接受集合 | trivial 通道引入新 decision 取值，门禁需显式扩枚举，避免严格匹配导致 trivial 通道失效（来源：requirements/REQ-2026-003/plan.md:91）|

## 待澄清清单

_（全部已收敛 · 2026-04-29）_

<!--
历史收敛记录：
- (a) GATE-REVIEW-VERDICT 同步升级 → 写入"范围/包含"段
- (b) GitHub PR Review 等价 sign-off 整体 out of scope → 写入"范围/不包含"段（D-004）
- (c) `/code-review --all` 兜底参数 → 本需求实现，写入"范围/包含"段（D-005）
- (d) trivial 快速通道判定规则 → 仅纯文档（`*.md` / `docs/**` / `*.txt`），写入"范围/包含"段（D-006）
-->

