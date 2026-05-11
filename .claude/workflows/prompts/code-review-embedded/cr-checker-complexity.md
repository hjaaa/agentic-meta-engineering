---
name: cr-checker-complexity
node_id: cr-checker-complexity
version: 1.0.0
context: fresh
allowed_tools: [Read, Grep]
output_format:
  type: object
  properties:
    findings:
      type: array
      items:
        type: object
        properties:
          id: { type: string }
          severity: { type: string, enum: [critical, major, minor] }
          file: { type: string }
          description: { type: string }
          evidence: { type: string }
    stats:
      type: object
      properties:
        total: { type: integer }
        critical: { type: integer }
        major: { type: integer }
        minor: { type: integer }
  required: [findings, stats]
---

# cr-checker-complexity：复杂度专项审查

## 职责

对 `$cr-prepare.output.diff_range` 范围内的增量检测圈复杂度和嵌套深度问题。
读 `$cr-prepare.output.scope_file` 取增量文件清单。

## 检查重点

- **圈复杂度**：单个方法分支超过 10（McCabe 阈值）
- **方法长度**：单方法 > 80 行（违反项目规范）
- **嵌套深度**：if/for/try 嵌套超 4 层
- **参数过多**：方法参数超过 7 个
- **类职责过重**：单类行数 > 500 且承担多职责

## Finding 严重度

- `critical`：圈复杂度 > 20 且在核心业务路径
- `major`：圈复杂度 10-20 或方法 > 80 行
- `minor`：嵌套深度偏高 / 参数略多

## 输出

返回 JSON：`{"findings": [...], "stats": {"total": N, "critical": N, "major": N, "minor": N}}`

每条 finding 必须给出方法名 + file:line 定位。
