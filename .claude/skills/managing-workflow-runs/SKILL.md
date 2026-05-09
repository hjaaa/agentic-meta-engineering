---
name: managing-workflow-runs
description: workflow run 全生命周期管理伞形 Skill，被 9 个 /workflow:* 命令共用。负责状态校验矩阵派发、jsonl 事件追加、bootstrap/continue/save/status/list/approve/reject/rollback/cancel 9 子动作。
---

## 什么时候用

用户通过 `/workflow:*` 命令，或口头说"启动 workflow / 继续 workflow / 保存进度 / 查看状态 / 列出 run / 批准 / 拒绝 / 回滚 / 取消"时。

## 核心流程

1. **识别意图**：映射到 9 个子动作之一
   - `run`    → bootstrap（创建 run 目录 + jsonl + `workflow_started` 事件）
   - `continue` → 反扫 jsonl 重建 RunState，进 main loop（F-006 落地前为 stub）
   - `save`   → 追加 `save` 事件 + note
   - `status` → 只读展示父子树（spec §6.4）
   - `list`   → 扫 requirements/* + runs/*，过滤输出
   - `approve` → tty 校验 + `approval_approved` 事件
   - `reject`  → tty 校验 + reason 校验 + `approval_rejected` 事件
   - `rollback` → state 校验 + 调 rollback_run（F-010 占位）
   - `cancel`  → `cancel_requested` 事件 + TaskStop 兜底（D-005）

2. **状态机矩阵校验**（每子动作开头必做）

   读 `reference/category-rules/state-matrix.md` 的矩阵表。当前 run state + 命令 → 若格子 = ✗，立即 `exit 1`，stderr 输出：
   ```
   WorkflowStateError: cmd=<cmd> run_id=<run_id> state=<state>
   当前状态 <state> 不允许执行 <cmd>（allowed states: <...>）
   ```

3. **事件追加**：所有写 jsonl 操作调 `run_state.append_event`（fcntl.LOCK_EX 原子写）。

4. **双路径 run-id 解析**：所有需要 run 上下文的子动作用 `run_state._resolve_run_dir`（D-007）。

## 9 子动作详细规则

详见 `reference/command-implementations/` 各文件：

| 子动作 | 规则文件 |
|---|---|
| run | `reference/command-implementations/run.md` |
| continue | `reference/command-implementations/continue.md` |
| save | `reference/command-implementations/save.md` |
| status | `reference/command-implementations/status.md` |
| list | `reference/command-implementations/list.md` |
| approve | `reference/command-implementations/approve.md` |
| reject | `reference/command-implementations/reject.md` |
| rollback | `reference/command-implementations/rollback.md` |
| cancel | `reference/command-implementations/cancel.md` |

## 通用分类规则

详见 `reference/category-rules/`：

- `state-matrix.md` — 命令×状态矩阵（✓ / ✗）
- `approval-guard.md` — approve / reject 人机鉴别（D-006）
- `run-id-resolution.md` — D-007 双路径解析规则

## 硬约束

- ❌ 禁止跳过状态矩阵校验（每子动作开头必做）
- ❌ 禁止 AI 调用 approve / reject（hook + isatty 双层拦截）
- ❌ 禁止直接改 run_state.py / workflow_loader.py / common.py（F-001 已锁定）
- ❌ rollback_run 完整实现属于 F-010，F-005 只做占位调用
- ✅ cancel 必须写 `cancel_requested` 事件（任何三种允许状态），30s 超时调 TaskStop
- ✅ approve / reject 非 tty 环境 → exit 2（fail-closed 原则）

## 参考资源

- [`reference/category-rules/state-matrix.md`](reference/category-rules/state-matrix.md) — 矩阵与错误码
- [`reference/category-rules/approval-guard.md`](reference/category-rules/approval-guard.md) — D-006 人机鉴别
- [`reference/category-rules/run-id-resolution.md`](reference/category-rules/run-id-resolution.md) — D-007 双路径
- [`reference/command-implementations/`](reference/command-implementations/) — 9 子动作实现规则
- `scripts/lib/run_state.py` — RunState / read_events / append_event / _resolve_run_dir
- `scripts/lib/workflow_command_dispatcher.py` — CLI 派发入口
