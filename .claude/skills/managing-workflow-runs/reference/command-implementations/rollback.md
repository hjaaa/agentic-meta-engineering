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
6. 调 `rollback_run(run_id, to_node, target_id=None, repo_root=None)`（`scripts/lib/workflow_rollback.py`）：拓扑序找产物路径集合 → `shutil.move` 到 `.archived/<ts>/`；递归处理跨 sub_workflow 节点；截断 jsonl 尾部 mv 为 `<archived>/run-state.jsonl.tail`；双层锁顺序 `flock → mkdir → O_EXCL`

7. 输出：`Rolled back <run_id> from <current_node> to <to_node> at <ts>`；归档目录路径

## 失败模式

- to-node 不存在 → exit 1
- to-node 不是拓扑上游 → exit 1
- 并发 rollback（.in_progress 锁被占）→ exit 1
- WorkflowError（mv/锁失败等）→ exit 1 + stderr 错误文案

## 实现现状

完整 rollback 已落地（`workflow_rollback.py` + 4 个子模块）：
- 命令入口 `workflow_rollback_cmd.py` ✓
- state 矩阵校验 ✓
- 拓扑工具 `workflow_rollback_topology.py`（yaml 加载 / 拓扑序）✓
- 归档 `workflow_rollback_archive.py`（_collect / _move / _truncate_jsonl）✓
- sub_run 递归归档 `workflow_rollback_subrun.py` ✓
- 双层锁 `workflow_rollback_lock.py`（flock + mkdir + O_EXCL）✓
- `.archived/<ts>/.meta.json` 持久化 run_id/to_node/started_at，续跑读取 ✓
