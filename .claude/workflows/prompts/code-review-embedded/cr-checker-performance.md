---
name: cr-checker-performance
node_id: cr-checker-performance
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

# cr-checker-performance：性能专项审查

## 职责

对 `$cr-prepare.output.diff_range` 范围内的增量检测性能反模式。
读 `$cr-prepare.output.scope_file` 取增量文件清单。

## 检查重点

- **N+1 查询**：循环内调用 findById / db.query / 远程 API
- **SELECT \***：ORM 查询或原生 SQL 未列字段
- **深分页**：offset 大表分页（无游标 / 时间戳 / ID）
- **循环内大对象创建**：频繁 new 大对象
- **同步 IO 阻塞**：请求处理链路上的同步数据库 / 文件 IO

## Finding 严重度

- `critical`：循环里调 DB（N+1 直接后果严重）
- `major`：大表无索引 where / SELECT * on hot path
- `minor`：小范围潜在性能问题

## 输出

返回 JSON：`{"findings": [...], "stats": {"total": N, "critical": N, "major": N, "minor": N}}`

必须给出具体代码位置（file:line）和影响路径描述。
