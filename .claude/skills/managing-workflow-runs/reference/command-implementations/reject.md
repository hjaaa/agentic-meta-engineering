# /workflow:reject — 子动作实现规则

来源：detailed-design.md §1.2.7 + plan.md D-006

## 前置状态矩阵

允许：`approval_pending`

禁止：其他所有 state → exit 1

## 实现步骤（workflow_reject.py）

1. **isatty 兜底校验**（同 approve.md）：
   ```python
   if not sys.stdin.isatty():
       print("ERROR [E-WF-TTY-001]: reject 需要 tty 终端（人类专属动作）", file=sys.stderr)
       sys.exit(2)
   ```
2. 解析参数：`reason`（必填，多 token 拼空格）
3. **reason 长度校验**：`len(reason) < 8` → exit 1 + 提示"reason 最短 8 字符"
4. 解析 run_id + 调 `_resolve_run_dir`
5. 读 jsonl 重建 `run_state`
6. **状态矩阵校验**：state ≠ approval_pending → exit 1
7. 获取 `pending_approval` 节点 id
8. 调 `append_event(jsonl_path, {"type": "approval_rejected", "node_id": node_id, "run_id": run_id, "data": {"reason": reason}})`
9. 状态机：approval_pending → on_reject 节点路径（yaml 声明；F-005 只写事件，路径跳转由 F-006 main loop 处理）
10. 输出：`Rejected <node_id> at <ts>: <reason>` + on_reject 节点信息

## 失败模式

- non-tty → exit 2 + `E-WF-TTY-001`
- reason 未提供 → exit 1 + 用法提示
- reason 太短（< 8 字符）→ exit 1 + 长度要求
- state ≠ approval_pending → exit 1 + `E-WF-STATE-001`
