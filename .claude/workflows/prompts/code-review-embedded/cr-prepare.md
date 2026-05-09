---
name: cr-prepare
node_id: cr-prepare
version: 1.0.0
context: shared
allowed_tools: [Read, Grep, Bash, Write]
output_format:
  type: object
  properties:
    diff_range:
      type: string
      minLength: 1
    scope_file:
      type: string
    mode:
      type: string
      enum: [standalone, embedded]
    feature_id:
      type: string
    warning:
      type: string
  required: [diff_range, scope_file, mode]
---

# cr-prepare：审查预检（识别模式 + diff scope）

## 目标

识别当前审查是独立（standalone）还是嵌入（embedded）模式，
确定增量范围（diff_range），输出供下游 8 个 checker 使用。

## 输入

- `$ARGUMENTS`：父 workflow 通过 sub_workflow.args 序列化传入的 JSON 字符串（嵌入模式），
  或 `/code-review` 命令行参数（独立模式）。
- 当前 git 工作目录上下文。

## 模式识别规则

1. **嵌入模式**：`$ARGUMENTS` 是有效 JSON 且包含 `diff_range` 字段
   - `diff_range` 直接取自 args
   - `feature_id` 取自 args（若有）
   - `mode = "embedded"`

2. **独立模式**：`$ARGUMENTS` 为空或非 JSON
   - 运行 `git diff --name-only HEAD~1..HEAD` 获取增量文件列表
   - `diff_range = "HEAD~1..HEAD"`（或用户在命令行指定的范围）
   - `mode = "standalone"`

## scope_file 生成

将增量文件清单写到隔离路径 `$ARTIFACTS_DIR/review-scope.json`，格式：

```json
{
  "diff_range": "<range>",
  "mode": "standalone | embedded",
  "feature_id": "<F-XXX 或空>",
  "changed_files": ["<file1>", "<file2>"]
}
```

`$ARTIFACTS_DIR` 由引擎注入，每个 workflow run 独立，父子 run 路径互不重叠，
不会因并发 review 互相覆盖（spec §2.4 父子隔离）。

## 输出约定

输出结构化 JSON，字段：
- `diff_range`：git diff 范围字符串（非空；若为空则抛错，见下方注意事项）
- `scope_file`：`$ARTIFACTS_DIR/review-scope.json` 路径（运行时已替换为具体路径）
- `mode`：`"standalone"` 或 `"embedded"`
- `feature_id`（可选）：嵌入模式时从 args 获取
- `warning`（可选，`type: string`）：非致命告警信息

## 注意事项

- 禁止在此阶段读取完整 diff 内容（节省主对话 token）
- **若 diff_range 为空（无增量），必须抛出错误并终止执行**，不得 fallback 为
  `"HEAD~1..HEAD"`——空 diff 会导致下游 8 个 checker 静默跑空集合，cr-judge
  输出空报告掩盖实际问题。
- scope_file 必须写到 `$ARTIFACTS_DIR/review-scope.json`，禁止写到工作目录根
