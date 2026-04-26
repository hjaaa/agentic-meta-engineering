# spec drift：消费方对齐产出方

**沉淀原因**：AI 反复错 + 跨会话保留

## 问题

规范文档说"X 在路径 P"，但实际产出工具/命令把 X 写到了路径 Q。门禁字面校验通不过，实际功能正确——典型 spec drift。

## 根因

spec 早期设计稿与后续实现分头演进，消费方（gate / 规范 / 模板）没及时同步。本次具体：`gate-checklist.md` / `submit-rules.md` / `pr-body.md.tmpl` / 3 处文档写 `artifacts/code-review-reports/`，但 `/code-review` 命令实际产出在 `artifacts/review-YYYYMMDD-HHMMSS.md`。

## 解法

**以产出方（命令/工具的实际行为）为事实**，改消费方对齐。**禁止**反向搬产出位置：会破坏既有引用、git 历史、其他在途需求。命令实现是"事实"，spec 是"描述"，事实和描述冲突时改描述。

## 验证方法

- `grep -rn "<旧路径>" .claude/ context/ scripts/` 无残留
- 门禁能跑通

## 引用来源

- 本仓库 commit 6f4b9ef（修 6 处 review 报告路径 spec drift）
- `requirements/REQ-2026-001/process.txt` submit 流程触发暴露
