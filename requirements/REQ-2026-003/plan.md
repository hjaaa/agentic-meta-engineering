# REQ-2026-003 · 代码审查人类必经卡点（路由确认 + 结论 sign-off）

## 目标

给当前的 `/code-review` 流水线加两道**人类必经卡点**，阻断"AI 闭环审查 + AI 自我盖章"，让代码合并前的最终责任主体回到人类。

## 范围

- 包含：
  - 卡点 A（审查前）：`code-review-prepare` 输出 checker 路由建议 + 跳过理由，**等待人类显式确认**后才进入并行 checker
  - 卡点 B（审查后）：`code-quality-reviewer`（Judge）的 `conclusion` 取值收敛为三档机器评估（`looks_clean / needs_attention / blocked`），**禁止输出 `approved`**
  - 引入 `human_signoff` 字段进入 verdict schema，由人类通过 `/code-review:signoff` CLI 写入（非 tty 拒签）
  - `feature-lifecycle-manager` 转 done 门禁、`/requirement:submit` 提交门禁均改为查 `human_signoff.decision == "approved"`
  - 报告模板加路由说明段 + 待 sign-off 提示
  - 场景规范留档（`context/team/engineering-spec/specs/2026-04-29-code-review-human-checkpoints.md`）
- 不包含：
  - 8 个 checker（complexity / security / concurrency / ...）的内部检查规则——本需求是流程层卡点，与 checker 内部逻辑正交
  - 一份共享的 checker 输出契约骨架（前一轮审查发现的 P0 问题，归到下一个独立需求）
  - GitHub PR Review 等价 sign-off 的具体抓取实现（仅在本需求的非功能需求中描述意图，实施留到下一迭代）

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | 2026-04-29 |
| tech-research | 2026-04-29 |
| outline-design | 2026-04-30 |
| detail-design | 2026-04-30 |
| task-planning | 2026-04-30 |
| development | 2026-05-02 |
| testing | 2026-05-03 |

## 风险

- **R1：人类 sign-off 重 ceremony**：每次小改也卡人 → 应对：保留 `/code-review --all` 与 `signoff --trivial` 兜底；纯文档变更走快速跳过路径
- **R2：GitHub PR 双签字**：本地 sign-off + PR Review 重复 → 应对：`requirement:submit` 走 PR 路径时把 PR Review 视为等价 sign-off（实现在下一迭代，本需求只在 spec 中预留接口）
- **R3：路由建议漏跑**：AI 信号正则不全可能跳过该跑的 checker → 应对：跳过原因必须落盘 `.review-scope.json.skipped_checkers`，事后可审计；初版正则宁滥勿缺
- **R4：tty 校验易绕过**：开发者给 AI shell 装假 tty → 应对：在 ai-collaboration.md 里写硬规则；CI 流水线追加 `gh pr review` 二次校验作为兜底
- **R5：与现有 GATE-REVIEW-VERDICT 冲突**：旧门禁假定 `conclusion=approved` 即放行 → 应对：升级 schema 同步升级该门禁的判定逻辑（查 `human_signoff` 而非仅 `conclusion`）

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
-->

### D-001 双卡点而非单卡点
- **Context**：单纯加"审查后 sign-off"无法防止 AI 在选 checker 时漏选某类风险（例如悄悄不跑 security-checker 让漏洞过关）。
- **Decision**：在 `code-review-prepare` 与 `code-quality-reviewer` 两处都设人类卡点。前者卡"查不查"，后者卡"过不过"。
- **Consequences**：
  - 优点：覆盖"漏检"与"误判"两类风险
  - 缺点：每次审查至少两次人类介入；通过 trivial 快速通道与跨 feature 路由偏好缓解
- **时间**：2026-04-29 17:07:36

### D-002 AI 三档评估，禁止输出 approved
- **Context**：旧 schema 中 `conclusion` 由 AI 直接给 `approved/needs_revision/rejected`，feature 转 done 仅看此字段——AI 实际成为最终签字主体。
- **Decision**：AI 只能给 `looks_clean / needs_attention / blocked` 三档**机器评估**；`approved` 字段从 AI 输出空间中移除，改由 `human_signoff.decision` 单向写入。
- **Consequences**：
  - 优点：AI 与人类的判断分离、可独立审计
  - 缺点：旧 verdict 文件需要迁移（迁移策略：旧文件 conclusion=approved 视为 looks_clean + 无 sign-off，feature-lifecycle-manager 在升级后强制要求重新 sign-off）
- **时间**：2026-04-29 17:07:36

### D-003 防 AI 代签：tty 校验 + GitHub PR Review 等价
- **Context**：human_signoff 字段如果可被任意调用方写入，AI 可在主对话里自行调用 `save-review.sh signoff` 完成"代签"。
- **Decision**：
  1. 本地 CLI 路径：`save-review.sh signoff` 校验 stdin 是 tty（`[ -t 0 ]`）；非 tty 直接拒签
  2. PR 路径（下一迭代）：`gh pr view --json reviews` 读 PR Review，将 APPROVED 的 review 视为等价 sign-off
- **Consequences**：
  - 优点：AI 在 non-interactive 环境（包括子 Agent / Hook / CI）无法走通签字
  - 缺点：tty 不是绝对防伪（开发者给 AI 装假 tty 仍可绕过），需配合 ai-collaboration.md 硬规则与 CI 二次校验
- **时间**：2026-04-29 17:07:36
