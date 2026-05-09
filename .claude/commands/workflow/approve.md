---
description: 批准当前 approval_pending 节点（人类专属动作）
---

## 用途

在 `approval_pending` 状态下批准当前 approval 节点，推进 workflow 继续执行。

**人类专属动作**：需要 tty 终端（hook + isatty 双层校验，D-006）。AI 在主对话或子 Agent 中禁止调用此命令。

## 参数

无

## 允许状态

`approval_pending`（其他状态拒绝：exit 1）

## 鉴别机制（D-006）

1. **Hook 拦截层**（F-013 落地）：pre-tool-use hook 识别 AI 调用 → exit 2 BLOCKED
2. **isatty 兜底**：`workflow_approve.py` 检查 `sys.stdin.isatty()`，非 tty → exit 2，不允许绕过

## 委托

调用 Skill `managing-workflow-runs` 的 **approve** 子动作：

- 双层 tty 校验（hook + isatty）
- 调 `workflow_approve.py`：写 `approval_approved` jsonl 事件
- 状态机 approval_pending → running
- 输出 "Approved <node-id> at <ts>"，进入下一节点提示
