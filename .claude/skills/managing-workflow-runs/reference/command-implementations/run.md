# /workflow:run — 子动作实现规则

来源：detailed-design.md §1.2.1

## 前置状态矩阵

| 前置状态 | 允许 |
|---|---|
| (无 run) | ✓ |
| 任何已有 run state | ✗（不需要先有 run）|

> `run` 不做 run 上下文校验，属于"无 run"场景。

## 实现步骤（workflow_run.py）

1. 解析参数：`template_id`（必填）+ `args`（可选，多 token 拼空格）
2. 调 `workflow_loader.discover_workflows()` 找模板；找不到 → exit 1 + 可用模板列表
3. 调 `workflow_loader.load_workflow(template_path)` 校验；有 error → exit 1 + 报告
4. 生成 run_id（格式 `REQ-YYYY-NNN` 或 `RUN-YYYYMMDD-NNN`，视模板类型）
5. 创建 run 目录：`runs/<run_id>/` 或 `requirements/<run_id>/`（需求类模板）
6. 写 meta.yaml（模板名、args、start_ts、state=running）
7. 调 `append_event(jsonl_path, {"type": "workflow_started", "run_id": run_id, "data": {...}})`
8. 若需求类模板 → 切 `feat/req-<run_id>` 分支（git checkout -b）
9. 输出：run_id + 起始节点名 + 下一步提示

## 失败模式

- template not found → exit 1，列出可用模板
- yaml schema error → exit 1 + W 错误码明细
- 分支冲突 → exit 1 + 切分支建议
- args schema 不符 → exit 1 + 缺失字段提示
