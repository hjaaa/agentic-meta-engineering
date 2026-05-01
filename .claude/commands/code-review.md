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

### 1. 预检：`code-review-prepare` Skill → 路由器

两步串行：

**Step 1-prepare**：
- 识别模式（embedded / standalone）
- 取 diff / 确定 services（不写盘）
- 输出预检摘要，用户确认继续

**Step 2-pre（卡点 A）：路由器 `routing.py` 交互**

调用 `python3 scripts/lib/code_review_routing.py --mode embedded --requirement-id <id> --base-sha <sha> --head-sha <sha> --base-branch develop --current-branch <branch>`

处理 5 个退码分支：
- `EXIT_OK (0)` — 正常完成，读 `.review-scope.json`；若 `skipped==true` 输出最小报告（trivial-skip）并 return
- `EXIT_NON_TTY (2)` — 检测到非 tty 调用（AI / 管道），报错并 abort
- `EXIT_SCHEMA_INVALID (3)` — routing.yaml 语义错，报错并 abort
- `EXIT_YAML_LOAD_ERROR (4)` — routing.yaml IO/解析失败，报错并 abort
- `EXIT_USER_ABORT (5)` — 用户主动取消或连续 3 次无效，audit 已写，abort

若 skipped 不为 true，继续 Step 2。

### 2. 并行 checker

读 `.review-scope.json` 中 `checker_route` 字段，按该列表并行调用 N 个 checker Agent（N=1..8，动态）

### 3. 对抗验证 + 综合裁决

**3a. 调用 `review-critic`**

收齐 checker 结果后，先统一分配全局编号 `F-{seq}` 并合并同根因/同位置的 finding，然后把候选 finding 列表 + `.review-scope.json` 交给 `review-critic` 做对抗验证。

critic 输出每条 finding 的 verdict（`rejected / not_proven / not_rebutted`）+ 反证。

**3b. 调用 `code-quality-reviewer`**

把 checker 结果 + critic verdicts + `.review-scope.json` 一并交给 `code-quality-reviewer`，它作为 Judge 做三方对比（checker 证据 / critic 反证 / 必要时读源码）给最终结论。

> 主 Agent 不自己产出 finding、不自己做对抗验证、不自己做最终裁决——这三件事分别由 checker / critic / quality-reviewer 负责。

### 4. 报告：`code-review-report` Skill

- 合并 issue（按 critic verdict 处置：rejected → drop；not_proven → 降级 + 标注；not_rebutted → 保留）
- 应用综合裁决结论（looks_clean / needs_attention / blocked）
- 生成"裁决明细"段（F-id / checker / severity / critic verdict / 最终处置）
- 写入文件：
  - 嵌入：`requirements/<id>/artifacts/review-YYYYMMDD-HHMMSS.md`
  - 独立：`/tmp/code-review-YYYYMMDD-HHMMSS.md`
- 主对话只输出结论 + critical 列表 + 报告文件路径
