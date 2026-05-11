---
description: 列出所有 workflow run（支持过滤）
argument-hint: "[--filter=<expr>]"
---

## 用途

扫描 `requirements/*/` 与 `runs/*/` 下所有 run，输出表格索引，支持条件过滤。

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `[--filter=<expr>]` | 否 | 过滤表达式，如 `state=paused`、`template=standard-8phase` |

支持的过滤字段：`phase` / `state` / `template` / `requirement_id` / `parent_run_id`

操作符：`=` / `!=` / `contains`

## 允许状态

任意（list 是纯只读命令，无 run 上下文要求）

## 委托

调用 Skill `managing-workflow-runs` 的 **list** 子动作：

- 扫 `requirements/*/meta.yaml` + `runs/*/meta.yaml`（D-002 双轨期）
- 按 `--filter` 过滤
- 表格输出：run-id / 模板 / 状态 / 阶段 / 当前节点 / 父子标识
