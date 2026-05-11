---
description: 拒绝当前 approval_pending 节点（人类专属动作）
argument-hint: "<reason>"
---

## 用途

在 `approval_pending` 状态下拒绝当前 approval 节点，触发 on_reject 路径。

**人类专属动作**：需要 tty 终端（hook + isatty 双层校验，D-006）。AI 禁止调用。

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `<reason>` | 是 | 拒绝理由；多 token 拼空格；**最短 8 字符** |

## 允许状态

`approval_pending`（其他状态拒绝：exit 1）

## 鉴别机制（D-006）

1. **Hook 拦截层**（F-013 落地）：pre-tool-use hook 识别 AI 调用 → exit 2 BLOCKED
2. **isatty 兜底**：`workflow_reject.py` 检查 `sys.stdin.isatty()`，非 tty → exit 2

## 委托

调用 Skill `managing-workflow-runs` 的 **reject** 子动作：

- 双层 tty 校验（hook + isatty）
- reason 长度校验（≥ 8 字符）
- 调 `workflow_reject.py`：写 `approval_rejected` jsonl 事件（含 reason 字段）
- 状态机 approval_pending → on_reject 节点（yaml 声明的回退路径）
- 输出 "Rejected <node-id> at <ts>: <reason>"，on_reject 节点信息
