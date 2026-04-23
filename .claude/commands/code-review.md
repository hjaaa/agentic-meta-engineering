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

本命令编排顺序流（不委托单一 Skill，自身协调四步）：

### 1. 预检：`code-review-prepare` Skill

- 识别模式（embedded / standalone）
- 取 diff / 确定 services / 写 `.review-scope.json`
- 输出预检摘要，用户确认继续

### 2. 并行 checker

主 Agent 在一条消息里并行调用 8 个专项 checker Agent：

- `design-consistency-checker`
- `security-checker`
- `concurrency-checker`
- `complexity-checker`
- `error-handling-checker`
- `auxiliary-spec-checker`
- `performance-checker`
- `history-context-checker`

**零 finding 快速路径**：若 8 个 checker 全部返回空 issues，直接跳到第 4 步输出 `approved` 报告，不调 critic / 不调综合 reviewer。

### 3. 对抗验证 + 综合裁决

**3a. 调用 `review-critic`**

收齐 checker 结果后，先统一分配全局编号 `F-{seq}` 并合并同根因/同位置的 finding，然后把候选 finding 列表 + `.review-scope.json` 交给 `review-critic` 做对抗验证。

critic 输出每条 finding 的 verdict（`rejected / not_proven / not_rebutted`）+ 反证。

**3b. 调用 `code-quality-reviewer`**

把 checker 结果 + critic verdicts + `.review-scope.json` 一并交给 `code-quality-reviewer`，它作为 Judge 做三方对比（checker 证据 / critic 反证 / 必要时读源码）给最终结论。

> 主 Agent 不自己产出 finding、不自己做对抗验证、不自己做最终裁决——这三件事分别由 checker / critic / quality-reviewer 负责。

### 4. 报告：`code-review-report` Skill

- 合并 issue（按 critic verdict 处置：rejected → drop；not_proven → 降级 + 标注；not_rebutted → 保留）
- 应用综合裁决结论（approved / needs_revision / rejected）
- 生成"裁决明细"段（F-id / checker / severity / critic verdict / 最终处置）
- 写入文件：
  - 嵌入：`requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`
  - 独立：`/tmp/code-review-YYYYMMDD-HHMMSS.md`
- 主对话只输出结论 + critical 列表 + 报告文件路径
