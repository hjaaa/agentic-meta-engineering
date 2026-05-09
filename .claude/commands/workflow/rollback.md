---
description: 回滚 workflow run 到指定节点
argument-hint: "<to-node>"
---

## 用途

将当前 workflow run 回滚到指定节点：归档当前节点之后的产物到 `.archived/<ts>/`，截断 jsonl，从 `to-node` 重新开始。

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `<to-node>` | 是 | 目标节点 ID（必须是当前节点的拓扑上游） |

## 允许状态

`running` / `paused` / `approval_pending` / `failed` / `completed`

（`cancelled` / `cancel_requested` 拒绝：exit 1）

## 委托

调用 Skill `managing-workflow-runs` 的 **rollback** 子动作：

- state 校验（矩阵）
- to-node 存在性 + 拓扑上游校验
- 调 `rollback_run`（F-010 落地前为占位入口）：mv 产物到 `.archived/<ts>/` + jsonl 截断
- 输出 "Rolled back <run-id> from <X> to <to-node> at <ts>"；归档目录路径

> 注：`rollback_run` 完整实现在 F-010；F-005 仅提供命令入口 + state 校验 + 调用占位。
