# /workflow:continue — 子动作实现规则

来源：detailed-design.md §1.2.2

## 前置状态矩阵

允许：`running` / `paused` / `failed`

禁止：`approval_pending` / `cancel_requested` / `cancelled` / `completed` → exit 1

## 实现步骤（workflow_continue.py）

1. 解析参数：`run_id`（可选）；缺省时从当前 git 分支推断
2. 调 `_resolve_run_dir(run_id)` → `run_dir`（D-007 双路径）
3. 调 `read_events(jsonl_path)` + `RunState.rebuild(events, run_id)` → `run_state`
4. **状态矩阵校验**：`run_state.state` ∉ {running, paused, failed} → exit 1 + 错误文案
5. 调 `append_event(jsonl_path, {"type": "run_resumed", "run_id": run_id})`

   > 注：`run_resumed` 已加入 VALID_EVENT_TYPES 白名单；不映射 WORKFLOW_EVENT_TO_STATE，保持原 state 语义不变；main loop 进入后的事件由 dispatcher / scheduler / outcome_router 协作管理。

6. 进 main loop（`workflow_continue.py:_main_loop`）：dispatch_node 按 node kind 派发；_route_outcome 处理 7 outcome（completed / failed / approval_pending / loop_continue / loop_done / sub_workflow_pending / sub_workflow_done）；进入循环前 `_poll_sub_workflows` 反扫 sub_runs 回填父节点完成事件
7. 输出：当前节点 + 已完成节点数 + 下一步提示

## 失败模式

- run 不存在 → exit 1 + 候选 run 列表
- jsonl 损坏 → warn + 从最近 checkpoint 恢复（run_state.warnings 透传）

## 实现现状

main loop 已完整落地（REQ-2026-011 F-007/F-008/F-011 系列）：
- state 校验：`workflow_state_validator.validate_state_for_cmd` ✓
- jsonl 事件追加（`run_resumed`，不改 state，保持原语义）✓
- main loop：7 outcome 路由表 + 失败矩阵 retry/skip/abort ✓
- skill/agent/prompt 节点 → 写 `node_ready` 后返回 `awaiting_claude_action`，等 Claude 调 `save_node_result.py --kind=skill_result` 写 `node_completed` 后再次 `/workflow:continue` 推进 ✓
- sub_workflow 父子完成回填（AC-08：进 loop 前反扫 sub_runs 子 jsonl 末位事件） ✓
- path_lock 入口取锁（防并发 continue） ✓
