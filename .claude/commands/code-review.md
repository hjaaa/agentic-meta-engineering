---
description: 多 Agent 并行代码审查（双模：独立 / 嵌入）
argument-hint: "[scope]（可选，默认 git diff main..HEAD）"
---

## 用途

- **独立模式**：任意项目运行 `/code-review`，审当前分支 vs main 的增量
- **嵌入模式**：阶段 7 `feature-lifecycle-manager` 在 feature 完成时自动调用，scope 限定到该 feature

## 预检

1. 在 git 仓库内（`git rev-parse` 无错）
2. 工作区 clean 或变更已 stash（不审查 uncommitted 内容）
3. 增量行数 < 2000（超了引导用户先拆小）

## 流程

本命令编排顺序流（不委托单一 Skill，自身协调三步）：

### 1. 预检：`code-review-prepare` Skill

- 识别模式（embedded / standalone）
- 取 diff / 确定 services / 写 `.review-scope.json`
- 输出预检摘要，用户确认继续

### 2. 并行审查

主 Agent 在一条消息里并行调用 7 个专项 checker Agent + 1 综合 reviewer：

- `design-consistency-checker`
- `security-checker`
- `concurrency-checker`
- `complexity-checker`
- `error-handling-checker`
- `auxiliary-spec-checker`
- `performance-checker`

所有 checker 返回后，调用 `code-quality-reviewer` 做综合裁决（输入 = 7 份 checker 结果，不读源码）。

### 3. 报告：`code-review-report` Skill

- 合并 issue（去重 + 严重度分层）
- 应用综合裁决结论（approved / needs_revision / rejected）
- 写入文件：
  - 嵌入：`requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`
  - 独立：`/tmp/code-review-YYYYMMDD-HHMMSS.md`
- 主对话只输出结论 + critical 列表 + 报告文件路径
