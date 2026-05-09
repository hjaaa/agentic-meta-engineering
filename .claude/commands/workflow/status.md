---
description: 查看 workflow run 的当前状态（父子树视图）
argument-hint: "[<run-id>]"
---

## 用途

只读查看一个 workflow run 的当前状态，包含父子树、节点拓扑、当前位置、已完成节点数。

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `[<run-id>]` | 否 | run-id；缺省时按当前 git 分支推断 |

## 允许状态

所有已存在的 run（run 目录存在即可，只读操作）

矩阵允许：`running` / `paused` / `approval_pending` / `cancel_requested` / `cancelled` / `failed` / `completed`

## 委托

调用 Skill `managing-workflow-runs` 的 **status** 子动作：

- D-007 双路径解析 run-id
- 读 jsonl 重建 RunState
- 递归展开 sub_workflow 子 run 嵌套（spec §6.4）
- 只读，不写 jsonl，不改 meta
- 输出：`run-id` / 状态 / 模板 / 当前节点 / 已完成节点列表 / 子 run 缩进展示
