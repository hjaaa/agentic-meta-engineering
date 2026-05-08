# 派发决策详细说明

## 派发时序（详细设计 §2.6）

```
load yaml → 解析 frontmatter → 一致性校验
  ↓
反扫 jsonl 重建 RunState（node_outputs Map + current_node）
  ↓
替换变量（$ARGUMENTS / $node.output / $ARTIFACTS_DIR / $LOOP_OUTPUT）
  ↓
shellQuote / JSON 序列化转义
  ↓
派发：
  - context: fresh / agent / loop fresh_context: true → 子 agent
  - context: shared / skill / prompt 默认 → 主 Claude
  ↓
节点 stdout 受 output_format 约束
  ↓
追加 node_completed + output 字段
```

## RunState dataclass

```python
@dataclass
class RunState:
    run_id: str
    workflow_name: Optional[str]
    arguments: Optional[str]
    state: str                  # running | paused | approval_pending | completed | failed | cancelled | cancel_requested
    current_node: Optional[str] # 最后启动但未结束的节点
    node_outputs: dict[str, dict]   # {node_id: {"output": str, "state": "completed"|"failed"|"skipped", ...}}
    pending_approval: Optional[str] # 当前 approval_pending 节点 id
    last_event_ts: Optional[str]
    warnings: list[str]         # 反扫期间的 warn（损坏行 / 残缺对）
```

## 事件枚举（spec §5.4 + D-005 v2.1）

```
workflow_started | workflow_paused | workflow_completed
workflow_failed  | workflow_cancelled
cancel_requested        # v2.1 新增（D-005）：父 jsonl 写入此事件作为子 subagent 的可见信号
node_started | node_completed | node_failed | node_skipped | node_retried
approval_pending | approval_approved | approval_rejected
loop_iteration_started | loop_iteration_completed
loop_completed | loop_max_iterations_exceeded
parent_cancelled        # 子 run 检测到父 cancel_requested 后自写
parent_rolled_back      # 子 run 检测到父 rollback 越过本 sub_workflow 节点后自写
```

每事件至少含 `{ts, type, run_id?, node_id?, data?}`，ts 为 ISO 8601 UTC。

## jsonl 兜底规则（spec §13 + plan.md 风险 6）

| 场景 | 处理 |
|---|---|
| 文件不存在 | RunState 视为初始空（没有任何事件） |
| 整行 JSON 解析失败（非最后一行） | 跳过 + 加入 `warnings`，整体可恢复 |
| 最后一行损坏 | 跳过 + warn（spec §13） |
| 缺少 `type` 字段 | 跳过 + warn |
| `node_started` 无对应 `node_completed` | 该节点视为 running（重启重跑），不算 completed |
| 多次同节点 `node_started`（重跑） | 取最后一次的状态 |

## 双路径 _resolve_run_dir（D-007）

```python
def _resolve_run_dir(run_id: str) -> Path:
    """先 stat requirements/<run_id>/，不存在则 stat runs/<run_id>/，都不存在抛 WorkflowError。"""
```

- `requirements/<run_id>/` 命中 → 兼容期路径（D-002 双轨期）
- `runs/<run_id>/` 命中 → 新路径
- 都不存在 → `WorkflowError("run_id 不存在")`
- 3 月兼容期结束后清理：删 loader 中"探测 `requirements/`"那一行（D-007 锁定）

## 字段优先级实现要点（AC-06 / 详细设计 §2.2.1）

引擎内部统一通过 `_apply_defaults(workflow)` 把 workflow 顶层默认（model / effort / thinking / provider）填入每节点；prompt frontmatter 在 yaml 节点未显式声明对应字段时再补；同字段在两处都声明且**值不同**时输出 warning（不报 error）。

实现：在 loader 主流程 `_apply_defaults` 之后，扫每节点的 `prompt_file` frontmatter，把缺失字段补进去——这一步由 F-002+ 做（loader 当前只校验 yaml 自身，不解析 prompt frontmatter）。F-001 已经把 W100/W110/W111 等 yaml 自身字段错误识别完毕。
