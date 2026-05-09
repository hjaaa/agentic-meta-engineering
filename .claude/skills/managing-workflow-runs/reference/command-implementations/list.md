# /workflow:list — 子动作实现规则

来源：detailed-design.md §1.2.5

## 前置状态矩阵

无（list 不需要 run 上下文，任意场景均可）

## 实现步骤（workflow_list.py）

1. 解析参数：`--filter=<expr>`（可选）
   - filter 格式：`field=value` / `field!=value` / `field contains value`
   - 支持字段：`phase` / `state` / `template` / `requirement_id` / `parent_run_id`
2. 扫描所有 run：
   - `requirements/*/meta.yaml`（D-002 兼容期）
   - `runs/*/meta.yaml`（新轨道）
3. 逐条读 meta.yaml，提取：run_id / template / state / phase / current_node / parent_run_id
4. 应用 filter 过滤
5. 表格输出：

```
run_id             template           state    phase           current_node     parent
REQ-2026-009       standard-8phase    paused   detail-design   outline-design   -
RUN-20260509-001   code-review-emb    completed -              final-report     REQ-2026-009
```

## 失败模式

- filter 语法错 → exit 1 + 用法示例
- meta.yaml 解析错 → warn + 跳过该 run，不影响整体
