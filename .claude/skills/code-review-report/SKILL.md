---
name: code-review-report
description: 聚合 8 个专项 checker + code-quality-reviewer 的输出，生成统一 Markdown 审查报告，按严重度分类归档。
---

## 什么时候用

由主 Agent 在收到所有 checker + 综合 reviewer 结果后自动调用。

## 核心流程

1. **收集输入**：
   - 8 份 checker 输出（design-consistency / security / concurrency / complexity / error-handling / auxiliary-spec / performance / history-context）
   - 1 份综合裁决（code-quality-reviewer）
   - `.review-scope.json`（范围元信息）

2. **合并 issue**：
   - 同一行同一问题 → 合并（保留原始 checker 来源作为 tags）
   - 按严重度分层：critical / major / minor

3. **应用综合裁决结论**：approved / needs_revision / rejected

4. **生成报告**：用 `templates/review-report.md.tmpl`

5. **写入文件**：
   - 嵌入模式：`requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`
   - 独立模式：`/tmp/code-review-YYYYMMDD-HHMMSS.md`

6. **主对话输出**：只粘结论行 + critical 问题列表，其余链接到报告文件

## 硬约束

- ❌ 禁止把完整报告粘到主对话（只粘结论+critical）
- ❌ 禁止遗漏 checker（所有 8 份都要合并，缺失的标记 `⚠️ 未运行`）
- ✅ 报告必须带时间戳（文件名中）
- ✅ 每个 issue 必须有 `file:line` 引用

## 参考资源

- [`templates/review-report.md.tmpl`](templates/review-report.md.tmpl) — 报告模板
