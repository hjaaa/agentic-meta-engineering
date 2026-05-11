---
description: 启动一个新的 workflow run
argument-hint: "<template-id> [<args>]"
---

## 用途

按指定模板启动一个新的 workflow run。自动创建 run 目录（`runs/<id>/` 或 `requirements/<id>/`）、meta.yaml、jsonl，并写入初始 `workflow_started` 事件。

## 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `<template-id>` | 是 | workflow yaml 模板名（不含路径和 .yaml 后缀） |
| `[<args>]` | 否 | 模板自定义参数；多 token 拼空格传递 |

## 预检

1. `template-id` 非空
2. 当前无对应分支的活跃 run（避免重复启动同一需求）

## 委托

调用 Skill `managing-workflow-runs` 的 **run** 子动作：

- 加载并校验 template yaml（via `workflow_loader`）
- 调 `workflow_run.py` 完成 bootstrap：生成 run-id + 创建目录 + 写 `workflow_started` jsonl 事件
- 需求类模板自动切 `feat/req-<id>` 分支
- 输出 run-id + 起始节点 + 下一步提示
