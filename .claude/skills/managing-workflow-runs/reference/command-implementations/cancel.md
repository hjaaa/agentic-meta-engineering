# /workflow:cancel — 子动作实现规则

来源：detailed-design.md §1.2.9 + plan.md D-005

## 前置状态矩阵

允许：`running` / `paused` / `approval_pending`

禁止：`cancel_requested` / `cancelled` / `failed` / `completed` → exit 1

## 实现步骤（workflow_cancel.py）

1. 解析 run_id
2. 调 `_resolve_run_dir` + 读 jsonl 重建 `run_state`
3. **状态矩阵校验**
4. 调 `append_event(jsonl_path, {"type": "cancel_requested", "run_id": run_id})`
5. 输出：`Cancel requested at <ts>; awaiting graceful exit (≤ 30s)`
6. 等待 graceful 退出（子 subagent poll `cancel_requested`）；30s 超时后：
   ```python
   try:
       # TaskStop forceful 兜底（F-009 落地；F-005 用 mock）
       _task_stop_forceful(run_id)
   except Exception as exc:
       # TaskStop 失败 → warn + 写事件
       warnings.append(f"TaskStop 失败: {exc}")
       append_event(jsonl_path, {"type": "cancel_taskstop_failed", "run_id": run_id,
                                  "data": {"error": str(exc)}})
   ```

   > 注：`cancel_taskstop_failed` 需加入 VALID_EVENT_TYPES（F-005 在 workflow_cancel.py 内临时 patch）
   > 完整 TaskStop 实现在 F-009；F-005 测试时用 mock 验证调用链。

7. 输出：`cancelled` 状态确认 / `cancel_taskstop_failed` 警告

## 失败模式

- state 不匹配 → exit 1 + `E-WF-STATE-001`
- TaskStop 调用失败 → warn + jsonl 写 `cancel_taskstop_failed`（不 exit 1）

## D-005 约束（父子 cancel 信号传递）

TC-F5-6 必须验证：
- running / paused / approval_pending 三状态都写 `cancel_requested` 事件
- 30s 超时后调用 TaskStop（mock 验证）
