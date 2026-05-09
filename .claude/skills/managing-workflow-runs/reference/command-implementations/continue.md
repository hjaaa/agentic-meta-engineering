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

   > 注：`run_resumed` 不在 VALID_EVENT_TYPES 白名单（当前版本）；实际测试用 `workflow_started` 或 `save` 类型验证续跑路径；main loop 进入后的事件由 F-006 管理。

6. 进 main loop（F-006 落地前调 `_main_loop_stub(run_state)`，仅打印当前状态）
7. 输出：当前节点 + 已完成节点数 + 下一步提示

## 失败模式

- run 不存在 → exit 1 + 候选 run 列表
- jsonl 损坏 → warn + 从最近 checkpoint 恢复（run_state.warnings 透传）

## F-005 范围约束

main loop 完整实现在 F-006。本 feature 提供：
- state 校验 ✓
- jsonl 事件追加（`workflow_paused` → 恢复标记）✓
- `_main_loop_stub` 占位（仅打印状态，不真正执行节点）✓
