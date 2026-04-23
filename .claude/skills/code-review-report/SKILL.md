---
name: code-review-report
description: 聚合 8 个专项 checker + review-critic 对抗验证 + code-quality-reviewer 综合裁决的输出，生成统一 Markdown 审查报告，按严重度分类归档，附裁决明细段。
---

## 什么时候用

由主 Agent 在收到 checker 并行结果 + critic verdicts + 综合裁决三方输入后自动调用。

## 核心流程

1. **收集输入**：
   - 8 份 checker 输出（design-consistency / security / concurrency / complexity / error-handling / auxiliary-spec / performance / history-context）
   - 1 份 critic 输出（review-critic 的 verdicts + summary）；**零 finding 快速路径时该项为空**
   - 1 份综合裁决（code-quality-reviewer 的 adjudication + merged_issues + conclusion）；**零 finding 快速路径时该项为空**
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
- ❌ 禁止丢弃裁决明细段（即便零 finding 快速路径也要保留该段，写明"无 finding，未触发 critic / quality-reviewer"）
- ✅ 报告必须带时间戳（文件名中）
- ✅ 每个 issue 必须有 `file:line` 引用
- ✅ 裁决明细段须覆盖所有候选 finding（含被 drop 的，用于复盘误报）

## 参考资源

- [`templates/review-report.md.tmpl`](templates/review-report.md.tmpl) — 报告模板
