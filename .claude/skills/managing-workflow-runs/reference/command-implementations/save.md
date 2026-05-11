# /workflow:save — 子动作实现规则

来源：detailed-design.md §1.2.3

## 前置状态矩阵

允许：`running` / `paused` / `approval_pending` / `failed` / `completed`

禁止：`cancel_requested` / `cancelled` → exit 1

## 实现步骤（workflow_save.py）

1. 解析参数：`note`（可选，多 token 拼空格，截断至 200 字符）
2. 解析 run_id（分支推断 / 参数）
3. 调 `_resolve_run_dir(run_id)` → `run_dir`
4. 读 jsonl 重建 `run_state`
5. **状态矩阵校验**
6. 调 `append_event(jsonl_path, {"type": "save", "run_id": run_id, "data": {"note": note}})`

   > 注：`save` 已加入 VALID_EVENT_TYPES 白名单（rev2 扩展）；不映射 WORKFLOW_EVENT_TO_STATE，
   > save 操作不改变 RunState.state（§1.3 矩阵 5 态均允许，正是此语义保证）。

7. 输出：`已保存 <ts>，当前节点：<current_node>，note：<note 摘要>`

## 失败模式

- 无 run → exit 1 + 提示先 run/continue
- note 超长 → 自动截断（不报错）
