# /workflow:approve — 子动作实现规则

来源：detailed-design.md §1.2.6 + plan.md D-006

## 前置状态矩阵

允许：`approval_pending`

禁止：其他所有 state → exit 1

## 实现步骤（workflow_approve.py）

1. **isatty 兜底校验**（fail-closed）：
   ```python
   if not sys.stdin.isatty():
       print("ERROR [E-WF-TTY-001]: approve 需要 tty 终端（人类专属动作）", file=sys.stderr)
       sys.exit(2)
   ```
2. 解析 run_id（分支推断）
3. 调 `_resolve_run_dir` + 读 jsonl 重建 `run_state`
4. **状态矩阵校验**：state ≠ approval_pending → exit 1
5. 获取 `pending_approval` 节点 id（来自 run_state.pending_approval）
6. 调 `append_event(jsonl_path, {"type": "approval_approved", "node_id": node_id, "run_id": run_id})`
7. 状态机：approval_pending → running（事件层由 RunState.rebuild 处理；本步骤只写事件）
8. 输出：`Approved <node_id> at <ts>` + 进入下一节点提示

## 失败模式

- non-tty → exit 2 + `E-WF-TTY-001`
- state ≠ approval_pending → exit 1 + `E-WF-STATE-001`
- hook 拦截（F-013）→ exit 2 + `BLOCKED`
