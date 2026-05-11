---
description: 取消当前正在运行的 workflow run
---

## 用途

向 workflow run 发送取消请求：父 jsonl 写入 `cancel_requested` 事件，子 subagent poll 检测后 graceful 退出；30s 超时后父调 TaskStop forceful 兜底（D-005）。

## 参数

无

## 允许状态

`running` / `paused` / `approval_pending`

（`cancel_requested` / `cancelled` / `failed` / `completed` 拒绝：exit 1）

## 委托

调用 Skill `managing-workflow-runs` 的 **cancel** 子动作：

- state 校验（矩阵）
- 调 `workflow_cancel.py`：父 jsonl 写 `cancel_requested` 事件
- 等待 graceful 退出（≤ 30s）；超时调 TaskStop forceful 兜底
- TaskStop 失败则 warn + jsonl 写 `cancel_taskstop_failed`
- 输出 "Cancel requested at <ts>; awaiting graceful exit (≤ 30s)"
