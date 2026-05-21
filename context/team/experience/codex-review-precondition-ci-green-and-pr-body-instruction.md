# codex review-loop 两条流程层硬约束：CI 全绿前置 + PR 正文阅读指令

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

20260519-context-usage-report 期间，触发 codex review-loop 时两次失误：

1. **CI 红时尝试跳过**：PR #84 在 quality-check fail 状态下，主 Agent 一度尝试用 "--no-ci-wait" 直接进 codex，被用户纠偏"必须保证 CI 通过"
2. **裸 `@codex review` 触发**：第一次尝试只发 `@codex review` 单行评论，没要求 codex 读 PR 正文，被用户纠偏"每次 review loop 都需要让 codex 读下 pr 的正文"

两条都不是代码 bug，是**流程层共识缺失**——本应在 spec 写明、在工具层强制，靠主 Agent 临场判断 fail。

## 根因

codex review 是稀缺资源（注意力 + bot 配额）：

- **CI 红就 review** = 把 reviewer 拉进无效会话；review 结论里"修 CI"会噪声化掉真正的代码 finding
- **裸触发** = codex 默认只 review diff，遗漏 PR 正文里的"变更摘要 / 影响范围 / 验证方式 / 风险与回滚 / 追溯"——这些是产品级设计意图，缺失会让 codex 从局部 diff 视角发 review，难以判断"实现是否覆盖 acceptance""silent 行为变更"

`/requirement:submit` 没有把这两条约束做成硬规则——`--no-ci-wait` 的文档原本说"不推荐"但允许跳进 codex，trigger 评论是 ad-hoc 拼装。

## 解法

**已落到工具层**（`scripts/lib/submit_codex.py` + `.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md` §7.5）：

1. **CI precheck 硬约束**：`_precheck_ci_or_exit(pr_number, req_id)` 在 `submit_with_codex` 发评论前 1 次性查 `gh pr checks <num>`：
   - `state ∈ {FAILURE, CANCELLED, TIMED_OUT}` → exit 1（fail-closed，写 `[codex-skipped] reason=ci-failed` 到 process.txt）
   - 任一 state ≠ `{SUCCESS, NEUTRAL, SKIPPED}` 且 `bucket ∉ {pass, skipping}` → exit 0 + warning（pending，写 `reason=ci-pending`）
   - 全 success → 静默通过
2. **触发评论模板硬约束**：`CODEX_REVIEW_TRIGGER_BODY` 常量（grep 唯一点，与 `_PASS_PHRASE` 同款单点维护）：
   - 永远是基础模板：`@codex review` + 5 段必读 section（变更摘要 / 影响范围 / 验证方式 / 风险与回滚 / 追溯）+ 3 条 review 重点（acceptance 完整性 / follow-up 挂账 / silent 行为变更）
   - round_n≥2 时附 "Changes since last codex review (commits + diff stat)" 段；基础体永不被截断

`--no-ci-wait` 的语义改为**仅跳过 step 11 的本地等待**，进入 codex 前仍调 precheck 校验。

## 验证方法

- 单元测试：`tests/lifecycle/test_submit_codex.py::test_check_ci_status_*` / `test_precheck_ci_or_exit_*` / `test_submit_with_codex_blocks_on_ci_failed` / `test_codex_review_trigger_body_constant_*` 锁双约束
- 端到端：PR 触发评论可 `gh pr view <num> --json comments` 看体；CI 红时调 `submit_with_codex` 立即 fail-closed 不会发评论

## 引用来源

- `requirements/20260519-context-usage-report/process.txt`（多条 `[codex-skipped]` 事件 + round=1/2 verdict）
- PR #84 commit `9d88a7c`（CI precheck + trigger 模板硬约束首次落地）
- `.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md` §7.5 / §11
- 关联经验：
  - `external-ai-reviewer-finds-internal-blindspots.md`（codex 价值的抽象规则）
  - `per-feature-review-misses-cross-component-contracts.md`（codex 抓出的 silent bug 类型）
