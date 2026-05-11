# /workflow:rollback — 子动作实现规则

来源：detailed-design.md §1.2.8 + plan.md D-010

## 前置状态矩阵

允许：`running` / `paused` / `approval_pending` / `failed` / `completed`

禁止：`cancel_requested` / `cancelled` → exit 1

## 实现步骤（workflow_rollback_cmd.py）

1. 解析参数：`to_node`（必填）
2. 解析 run_id + 调 `_resolve_run_dir`
3. 读 jsonl 重建 `run_state`
4. **状态矩阵校验**
5. to-node 存在性 + 拓扑上游校验（需要读 workflow yaml）
6. 调 `rollback_run(run_id, to_node, run_dir)`（F-010 落地前为占位）：

```python
try:
    from workflow_rollback import rollback_run
except ImportError:
    print(
        "ERROR: rollback_run 未落地（待 F-010 实现 workflow_rollback.py）",
        file=sys.stderr,
    )
    print(f"状态校验已通过：run_id={run_id} state={run_state.state} to_node={to_node}", file=sys.stderr)
    sys.exit(1)
```

7. 输出：`Rolled back <run_id> from <current_node> to <to_node> at <ts>`；归档目录路径

## 失败模式

- to-node 不存在 → exit 1
- to-node 不是拓扑上游 → exit 1
- rollback_run 未落地（F-010）→ exit 1 + 占位错误提示
- 并发 rollback（.in_progress 锁）→ exit 1

## F-005 范围约束

完整 rollback 实现（mv 产物 + jsonl 截断）在 F-010。本 feature 只做：
- 命令 .md 入口 ✓
- state 矩阵校验 ✓
- 调用占位（ImportError 兜底）✓
- TC-F5-1 测试用 mock 验证校验 + 调用路径 ✓
