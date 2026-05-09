---
description: 保存当前 workflow run 进度到 jsonl
argument-hint: "[note]"
---

## 用途

在 workflow 执行中途主动保存进度，追加 `save` 类型事件到 jsonl，作为续跑检查点。

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `[note]` | 否 | 保存说明；多 token 拼空格，最长 200 字符 |

## 允许状态

`running` / `paused` / `approval_pending` / `failed` / `completed`

（其他状态拒绝：exit 1）

## 委托

调用 Skill `managing-workflow-runs` 的 **save** 子动作：

- 调 `workflow_save.py`：追加 `save` 事件（含 note + ts + run_id）
- 输出 "已保存 <ts> + 当前节点 + note 摘要"
