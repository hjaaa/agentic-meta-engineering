# /workflow:status — 子动作实现规则

来源：detailed-design.md §1.2.4

## 前置状态矩阵

允许：所有已存在的 run（run 目录存在即可）

即：`running` / `paused` / `approval_pending` / `cancel_requested` / `cancelled` / `failed` / `completed`

## 实现步骤（workflow_status.py）

1. 解析 run_id（可选）
2. 调 `_resolve_run_dir(run_id)` → `run_dir`
3. 读 jsonl 重建 `run_state`
4. **只读校验**：run 目录存在即可，不做额外 state 限制
5. 递归检测 sub_workflow 子 run（读 run_dir/nodes/*/run_id 文件）
6. 格式化输出：

```
run_id:        REQ-2026-009
template:      standard-8phase
state:         paused
current_node:  detail-design
completed:     [initialization, definition, tech-research]
pending_approval: (none)
warnings:      (none)

子 run:
  └─ RUN-20260509-001 (code-review-embedded) [completed]
```

7. 纯只读，不写 jsonl，不改 meta

## 失败模式

- run 不存在 → 列出候选 run（扫 requirements/* + runs/*）
- jsonl 损坏 → warn + 展示已知状态（容错）
