---
description: 恢复一个暂停/中断的 workflow run
argument-hint: "[<run-id>]"
---

## 用途

恢复处于 running / paused / failed 状态的 workflow run，反扫 jsonl 重建 RunState 后进入 main loop 继续执行。

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `[<run-id>]` | 否 | run-id（如 `REQ-2026-009`）；缺省时按当前 git 分支 `feat/req-<id>` 模式推断 |

## 允许状态

`running` / `paused` / `failed`

（`completed` / `cancelled` / `cancel_requested` / `approval_pending` 拒绝：状态不满足时 exit 1）

## 委托

调用 Skill `managing-workflow-runs` 的 **continue** 子动作：

- D-007 双路径解析 run-id（via `_resolve_run_dir`）
- 读 jsonl 重建 RunState（via `read_events` + `RunState.rebuild`）
- 写 `run_resumed` jsonl 事件
- 进 main loop（占位 / F-006 落地完整实现）
- 输出当前节点 + 已完成节点数 + 下一步提示
