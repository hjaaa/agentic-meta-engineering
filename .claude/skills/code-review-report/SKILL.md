---
name: code-review-report
description: 聚合 8 个专项 checker + review-critic 对抗验证 + code-quality-reviewer 综合裁决的输出，生成统一 Markdown 审查报告，按严重度分类归档，附裁决明细段。
---

## 什么时候用

由主 Agent 在收到 checker 并行结果 + critic verdicts + 综合裁决三方输入后自动调用。

## 核心流程

1. **收集输入**：
   - 8 份 checker 输出（design-consistency / security / concurrency / complexity / error-handling / auxiliary-spec / performance / history-context）
   - 1 份 critic 输出（review-critic 的 verdicts + summary）
   - 1 份综合裁决（code-quality-reviewer 的 adjudication + merged_issues + conclusion）
   - `.review-scope.json`（范围元信息）

2. **应用裁决处置**：按 `code-quality-reviewer.adjudication[*].final_disposition` 处理每条 finding：
   - `drop` → 不进报告正文，只出现在"裁决明细"段
   - `keep` → 进入对应严重度段（critical / major / minor）
   - `downgrade` → 降一级后进入对应段
   - `follow-up` → 进入 Follow-up Notes 段，不分级

3. **生成裁决明细段**：每条候选 finding 展示 `F-id / checker / 原始 severity → critic verdict → 最终处置 + 理由`，保证审查过程透明

4. **应用综合裁决结论**：approved / needs_revision / rejected

5. **生成报告**：用 `templates/review-report.md.tmpl`

6. **写入文件**：
   - 嵌入模式：`requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`
   - 独立模式：`/tmp/code-review-YYYYMMDD-HHMMSS.md`

7. **主对话输出**：只粘结论行 + critical 问题列表，其余链接到报告文件

## 硬约束

- ❌ 禁止把完整报告粘到主对话（只粘结论+critical）
- ❌ 禁止遗漏 checker（8 份都要合并，缺失的标记 `⚠️ 未运行`）
- ❌ 禁止丢弃裁决明细段（无 finding 时仍要保留该段，写明"8 checker 全空 issues，已经 critic + quality-reviewer 出 conclusion=looks_clean"）
- ✅ 报告必须带时间戳（文件名中）
- ✅ 每个 issue 必须有 `file:line` 引用
- ✅ 裁决明细段须覆盖所有候选 finding（含被 drop 的，用于复盘误报）

## 报告模板增量段（F-003 引入）

报告模板（templates/review-report.md.tmpl）在既有 verdict 摘要段之后追加两段：

### 路由说明

显示卡点 A 的确认信息（从 `.review-scope.json` 取值）：

- **决策**：`{routing_confirmed_by.decision}`（accept / all / custom）
- **确认人**：`{routing_confirmed_by.confirmed_by}`（git config user.email）
- **确认时间**：`{routing_confirmed_by.confirmed_at}`
- **跑了哪些 checker**：`{checker_route}` 列表
- **跳过的 checker（含原因）**：从 `skipped_checkers[]` 渲染列表

### 人工确认提示

显示当前 verdict 的机器评估结论 + 引导用户在主对话进行软确认（不再写入 verdict 字段，软确认只作用于当前流程动作）：

- 头：`本次评审输出 conclusion = {conclusion}（looks_clean / needs_attention / blocked），这只是 AI 的机器评估，不代表合并通过。`
- 引导：根据 conclusion 给出对应的软确认动作提示：
  - `looks_clean` 且 `required_fixes` 为空 → 提示用户回复确认（如"OK 转 done"）后 feature-lifecycle-manager 才会把对应 feature 转 done
  - `needs_attention` → 默认建议先修复；如用户判断风险可接受，需在主对话**显式接受风险**（如"接受当前 needs_attention 风险，转 done"）后才允许转 done
  - `blocked` → fail-closed，必须先把 critical 问题修掉再重审，无法软确认绕过
- 警示：未获用户软确认时 feature-lifecycle-manager 不会把对应 feature 转 done；GATE-REVIEW-VERDICT 在 phase-transition / submit 时 hard-block `blocked`（error 级），`needs_attention` 仅触发 warning（strict 模式才升 fail）；软门禁由主对话的人工确认承担

## 参考资源

- [`templates/review-report.md.tmpl`](templates/review-report.md.tmpl) — 报告模板
