# REQ-2026-003 · 代码审查人类必经卡点（路由确认 + 结论 sign-off）

## 目标

给当前的 `/code-review` 流水线加两道**人类必经卡点**，阻断"AI 闭环审查 + AI 自我盖章"，让代码合并前的最终责任主体回到人类。

## 范围

- 包含：
  - 卡点 A（审查前）：`code-review-prepare` 输出 checker 路由建议 + 跳过理由，**等待人类显式确认**后才进入并行 checker
  - 卡点 B（审查后）：`code-quality-reviewer`（Judge）的 `conclusion` 取值收敛为三档机器评估（`looks_clean / needs_attention / blocked`），**禁止输出 `approved`**
  - 引入 `human_signoff` 字段进入 verdict schema，由人类通过 `/code-review:signoff` CLI 写入（非 tty 拒签）
  - `feature-lifecycle-manager` 转 done 门禁、`/requirement:submit` 提交门禁均改为查 `human_signoff.decision ∈ {"approved", "approved-trivial"}`（与 D-006 trivial 通道协同）
  - 报告模板加路由说明段 + 待 sign-off 提示
  - 场景规范留档（`context/team/engineering-spec/specs/2026-04-29-code-review-human-checkpoints.md`）
- 不包含：
  - 8 个 checker（complexity / security / concurrency / ...）的内部检查规则——本需求是流程层卡点，与 checker 内部逻辑正交
  - 一份共享的 checker 输出契约骨架（前一轮审查发现的 P0 问题，归到下一个独立需求）
  - GitHub PR Review 等价 sign-off（**完全 out of scope**，既不实施也不预留契约；未来团队化需要时独立 REQ 处理，详见 D-004）

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
- **R2：路由建议漏跑**：AI 信号正则不全可能跳过该跑的 checker → 应对：跳过原因必须落盘 `.review-scope.json.skipped_checkers`，事后可审计；初版正则宁滥勿缺
- **R3：tty 校验易绕过**：开发者给 AI shell 装假 tty → 应对：在 ai-collaboration.md 里写硬规则
- **R4：与现有 GATE-REVIEW-VERDICT 冲突**：旧门禁假定 `conclusion=approved` 即放行 → 应对：升级 schema 同步升级该门禁的判定逻辑（查 `human_signoff` 而非仅 `conclusion`）

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

### D-003 防 AI 代签：仅 tty 校验（PR Review 等价 out of scope）
- **Context**：human_signoff 字段如果可被任意调用方写入，AI 可在主对话里自行调用 `save-review.sh signoff` 完成"代签"。
- **Decision**：
  1. 本地 CLI 路径：`save-review.sh signoff` 校验 stdin 是 tty（`[ -t 0 ]`）；非 tty 直接拒签
  2. PR Review 等价 sign-off：**out of scope**——当前为单人项目无 reviewer 价值；前置依赖分支保护规则 `require review from someone other than author` 未配置；如未来团队化需要，开独立 REQ 处理
- **Consequences**：
  - 优点：AI 在 non-interactive 环境（包括子 Agent / Hook / CI）无法走通签字；范围聚焦，testing 阶段无需 GitHub API 兼容性测试
  - 缺点：tty 不是绝对防伪（开发者给 AI 装假 tty 仍可绕过），需配合 ai-collaboration.md 硬规则
- **时间**：2026-04-29 17:07:36（PR 路径裁剪：2026-04-29，scope-reduction）

### D-004 范围裁剪：移除 PR Review 等价 sign-off
- **Context**：在 definition 阶段对齐"待澄清项 1（PR Review 旁路验证范围）"时，确认当前为单人项目，PR Review 等价 sign-off 在分支保护未配置前是形式主义；旁路验证则是无人消费的死代码。
- **Decision**：把"GitHub PR Review 等价 sign-off"从范围中**完整移除**（既不实施也不预留契约）；本需求只支持单一签字路径——本地 tty CLI sign-off。
- **Consequences**：
  - 优点：待澄清项 1 直接消失（剩 2 条）；testing 阶段免做 GitHub API 兼容性测试；schema 设计更简洁（无需 source 字段区分本地/PR）
  - 缺点：未来团队化时 schema 需要扩展（接受此代价：等真有 reviewer 再做，避免提前抽象）
- **时间**：2026-04-29

### D-005 `/code-review --all` 兜底参数纳入本需求
- **Context**：双卡点的副作用是"小改也要确认两次"。如果纯文档变更也强制走完整路由建议流程，开发者会绕开整个机制。需要一个低成本逃生口。
- **Decision**：在本需求实现 `code-review-prepare --all` 标志，触发即跳过路由建议、直接选全部 8 个 checker；scope-json 中 `routing_confirmed_by.decision = "all"` 显式留痕。
- **Consequences**：
  - 优点：CLI 改动极小（一个 flag + 分支）；用户对"急用"场景有兜底；留痕仍可审计
  - 缺点：略增 prepare 阶段单测面（增 `--all` 路径测试）
- **时间**：2026-04-29

### D-006 trivial 快速通道仅放行"纯文档"
- **Context**：R1（人类 sign-off 重 ceremony）需要快速通道。可选范围：纯文档 / 纯重命名 / 纯 import 整理 / 纯测试新增 / 自定义白名单。范围越宽用户体验越好，但误放风险越大。
- **Decision**：本需求只放行**纯文档变更**——diff 中所有文件路径必须命中白名单 `*.md` / `docs/**` / `*.txt`；非全命中则拒绝，退出码 = 3，stderr 含 `trivial: non-doc files detected`。其余场景（重命名 / import 整理 / 测试新增）留待真实抱怨出现再扩。
- **Consequences**：
  - 优点：误放风险最低；判定逻辑简单（路径白名单）；通过的 verdict 标 `approved-trivial` 与 `approved` 可独立审计统计
  - 缺点：
    1. 纯重命名 / 纯单测新增等场景仍走完整流程（接受：宁可多按一次确认，不放过有风险的变更）
    2. **下游门禁协议成本**：feature-lifecycle-manager / requirement:submit / GATE-REVIEW-VERDICT 三处判定需从 `decision == "approved"` 改为 `decision ∈ {"approved", "approved-trivial"}`；schema 枚举也需扩展。本需求范围/包含 段已显式列入这两项产出物，下游设计阶段需同步落实
- **时间**：2026-04-29
