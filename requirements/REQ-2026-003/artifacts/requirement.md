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
- `verdict` schema 中没有任何字段承载"人类签字"语义（来源：scripts/save-review.sh:1）

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
  3. 写最终 `.review-scope.json`（含 `routing_confirmed_by` 字段记录确认人）
  4. 并行跑选中的 checker → critic → judge
  5. judge 输出三档评估之一（`looks_clean / needs_attention / blocked`），写入 verdict（`human_signoff: null`）
  6. 主对话提示："请执行 `/code-review:signoff <decision>`"
  7. 开发者读完报告，执行 `/code-review:signoff approve`（CLI 校验 tty）
  8. `human_signoff` 字段被写入 verdict
  9. feature-lifecycle-manager 校验 `human_signoff.decision == "approved"` → 允许转 done
- **期望结果**：feature 转 done 必须经过两次人类介入（路由确认 + 结论 sign-off），任一缺位则阻断

### 场景 2：独立模式手动审查

- **角色**：开发者（人类）
- **前置**：开发者在某个分支上手敲 `/code-review`（无关联需求）
- **主流程**：与场景 1 一致，但 `human_signoff` 不阻断需求生命周期（独立模式无 feature-lifecycle-manager 接入）；CLI 仍要求 sign-off 才生成"已签结报告"
- **期望结果**：即使在独立模式下，AI 也无法直接产出"approved"结论；最终结论必须由开发者本人签字

### 场景 3：AI 试图代签（必须被阻断）

- **角色**：AI（主 Agent / 子 Agent）
- **前置**：AI 在 non-interactive 环境（Hook / CI / 子 Agent shell）尝试调用 `save-review.sh signoff`
- **期望结果**：CLI 检测到 stdin 非 tty → 退出码非 0 + 提示"非交互环境拒绝签字"；AI 无法走通

## 非功能需求

- **性能**：路由建议生成 ≤ 5 秒；CLI signoff 写盘 ≤ 1 秒（无外部依赖）
- **兼容性**：
  - verdict schema 需向后兼容——旧 verdict（无 `human_signoff` 字段）视为"未签字"，feature-lifecycle-manager 升级后强制要求重新 sign-off（来源：requirements/REQ-2026-003/plan.md:58）
  - 与现有 GATE-REVIEW-VERDICT 门禁协同（来源：scripts/gates/registry.yaml:136）：升级该门禁的判定逻辑，从"看 conclusion"改为"看 human_signoff.decision"
- **安全/合规**：
  - sign-off 字段不可被 AI 在非交互环境写入（tty 校验 + 防 ppid 链伪造）
  - GitHub PR Review APPROVED 视为等价 sign-off [待补充]
    - 内容：在 `requirement:submit` 阶段从 `gh pr view --json reviews` 读 PR Review 列表，把 APPROVED review 视为本地 sign-off 的等价物
    - 依据：本仓库已有 `gh` 工具与 PR 流程（来源：context/team/git-workflow.md:1）；与开源社区惯例一致
    - 风险：开发者本地用 `--all` 全跑 + 立刻自签 + 推 PR + 自审 APPROVE → 仍是单人闭环；需配合分支保护（require review from other than author）
    - 验证时机：本需求 testing 阶段不实施，留下一迭代独立 REQ 处理（来源：requirements/REQ-2026-003/plan.md:36）

## 范围

- **包含**：
  - `code-review-prepare` 流程改为两阶段（建议 → 等确认 → 写盘）
  - `scope-schema.md` 新增 `selected_checkers / skipped_checkers / routing_confirmed_by` 字段
  - `code-quality-reviewer` 的 `conclusion` 取值收敛为 `looks_clean / needs_attention / blocked`，禁止 approved
  - `verdict` schema 新增 `human_signoff: { by, at, decision }` 字段
  - `scripts/lib/save_review.py` 新增 `signoff` 子命令（tty 校验、字段写入、append process.txt）
  - 新建 `.claude/commands/code-review/signoff.md`
  - `code-review-report` 模板加路由说明段 + 待签字提示段
  - `feature-lifecycle-manager` 转 done 门禁查 `human_signoff.decision == "approved"`
  - `requirement:submit` 提交门禁同上
  - `context/team/engineering-spec/specs/2026-04-29-code-review-human-checkpoints.md` 留档
- **不包含**：
  - 8 个 checker（complexity / security / concurrency / ...）的内部检查规则改造（plan.md:范围/不包含 第 1 条）
  - 共享 checker 输出契约骨架（前一轮审查发现的 P0 问题，下一个独立需求）
  - GitHub PR Review 等价 sign-off 的 CLI 实施（本需求只描述意图）

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 卡点数量 | 单卡点（仅审查后）/ 双卡点（审查前 + 审查后）| 双卡点 | 来源：requirements/REQ-2026-003/plan.md:50 |
| AI 是否可输出 approved | 可 / 不可 | 不可 | 来源：requirements/REQ-2026-003/plan.md:58 |
| 防 AI 代签 | 不防 / tty 校验 / PR Review / 双轨 | tty 校验 + PR Review（双轨，PR 路径下迭代）| 来源：requirements/REQ-2026-003/plan.md:66 |
| 路由建议跳过 → 是否记录 | 不记录 / 记录到 scope-json / 记录到报告 | 同时记录到 scope-json + 报告 | 防止"AI 静默跳过 checker"被发现不了 |
| 旧 verdict 迁移 | 自动转换 / 强制重签 | 强制重签 | 升级即视为门禁规则变更，旧签字不可继承 |

## 待澄清清单

1. **GitHub PR Review 等价 sign-off 的具体边界**（对应非功能需求 / 安全合规段的"GitHub PR Review APPROVED 视为等价 sign-off"假设）：本需求 spec 中描述意图，但 CLI 是否在 testing 阶段就先做"读 PR Review 但不写 human_signoff"的旁路验证？倾向：testing 阶段只做契约预留（接口 + schema 字段），不做实施
2. **`/code-review --all` 兜底参数是否在本需求实现** [待用户确认]：是 → 用户跳过路由建议直接全跑；否 → 留下迭代。倾向：本需求实现，CLI 简单
3. **trivial 快速通道的判定规则** [待用户确认]：当前 plan.md:R1 提到，但具体哪些场景算 trivial（纯 .md / 纯重命名 / 纯 import 整理 / 单元测试新增…）需要逐项列举。倾向：本需求只支持"纯文档变更"一类，其余下迭代扩展
4. **是否在本需求统一升级 GATE-REVIEW-VERDICT 门禁** [待用户确认]：升级即同步改 scripts/gates 内规则；否则旧门禁仍按 conclusion 判定，与本次 schema 变更不一致。倾向：本需求一并升级，避免双轨
