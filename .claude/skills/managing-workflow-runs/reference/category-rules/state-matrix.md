# 命令×RunState 状态机矩阵

来源：requirements/REQ-2026-009/artifacts/detailed-design.md §1.3

## 矩阵

✓ = 允许；✗ = 拒绝（前置条件不满足，exit 1 + stderr 错误文案）

| state \ cmd     | run | continue | save | status | list | approve | reject | rollback | cancel |
|---|---|---|---|---|---|---|---|---|---|
| (无 run)        | ✓   | ✗        | ✗    | ✗      | ✓    | ✗       | ✗      | ✗        | ✗      |
| running         | ✗   | ✓        | ✓    | ✓      | ✓    | ✗       | ✗      | ✓        | ✓      |
| paused          | ✗   | ✓        | ✓    | ✓      | ✓    | ✗       | ✗      | ✓        | ✓      |
| approval_pending| ✗   | ✗        | ✓    | ✓      | ✓    | ✓       | ✓      | ✓        | ✓      |
| cancel_requested| ✗   | ✗        | ✗    | ✓      | ✓    | ✗       | ✗      | ✗        | ✗      |
| cancelled       | ✗   | ✗        | ✗    | ✓      | ✓    | ✗       | ✗      | ✗        | ✗      |
| failed          | ✗   | ✓        | ✓    | ✓      | ✓    | ✗       | ✗      | ✓        | ✗      |
| completed       | ✗   | ✗        | ✓    | ✓      | ✓    | ✗       | ✗      | ✓        | ✗      |

## 校验规则

每个子动作（command implementation）在执行任何副作用之前，必须先做矩阵校验：

1. 获取当前 run state（via `RunState.rebuild(read_events(jsonl))`)
2. 查矩阵格子：`(state, cmd)` → ✓ 或 ✗
3. 若 ✗：

```
WorkflowStateError: cmd=<cmd> run_id=<run_id> state=<state>
当前状态 <state> 不允许执行 <cmd>
允许状态: <allowed_states_list>
```

exit 1，stderr 输出上述错误文案。

## 快速参照：各命令允许的状态

| 命令 | 允许的 run states |
|---|---|
| run | (无 run)（不需要现有 run）|
| continue | running / paused / failed |
| save | running / paused / approval_pending / failed / completed |
| status | running / paused / approval_pending / cancel_requested / cancelled / failed / completed |
| list | 任意（无需 run 上下文）|
| approve | approval_pending |
| reject | approval_pending |
| rollback | running / paused / approval_pending / failed / completed |
| cancel | running / paused / approval_pending |

## 错误码

- `E-WF-STATE-001`：state 不允许执行此命令（exit 1）
- `E-WF-STATE-002`：run_id 不存在（exit 1）
- `E-WF-TTY-001`：非 tty 环境调 approve/reject（exit 2）
