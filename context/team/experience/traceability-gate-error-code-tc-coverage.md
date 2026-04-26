# traceability 门禁易暴露错误码 TC 缺口

**沉淀原因**：跨需求重复 + AI 反复错

## 问题

`development → testing` 门禁的 `traceability-consistency-checker` 在 `semantic` 深度下发现"设计 §错误码矩阵列出的分支但 `run-e2e.sh` 中无对应 TC"，FAIL 阻断切换。

## 根因

开发期间 TC 偏向主流程，罕见错误分支（如 `transcript-truncate-failed` / `prompt-template-missing` / `notes-busy`）易漏覆盖。门禁兜底，开发期无强制点。

## 解法

**主防线**：开发实施时每加一条 `append_skip_marker "<reason>"` 就**同步**在 `run-e2e.sh` 加一个 TC 验证该标记写入。检查清单：worker 内 grep `append_skip_marker` 计数 ≤ run-e2e.sh 内 grep `hook-skipped:` 断言计数。

**兜底**：留给 traceability gate 临门一脚发现，但要付补 TC + fixup commit + 重跑门禁的代价。

## 验证方法

`traceability-consistency-checker` 的 `test_branch_coverage.uncovered_branches` 为空。

## 引用来源

- 本仓库 commit a690888（补 TC-11/TC-12 闭环 traceability fail）
- `requirements/REQ-2026-001/process.txt` 18:09:01 [gate:fail] 行
