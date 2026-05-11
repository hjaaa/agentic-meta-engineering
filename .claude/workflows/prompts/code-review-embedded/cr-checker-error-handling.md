---
name: cr-checker-error-handling
node_id: cr-checker-error-handling
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

# cr-checker-error-handling：异常处理与日志专项审查

## 职责

对 `$cr-prepare.output.diff_range` 范围内的增量检测异常吞没和日志问题。
读 `$cr-prepare.output.scope_file` 取增量文件清单。

## 检查重点

- **异常吞没**：catch 块为空或仅注释，无重抛也无记录
- **日志缺失**：catch 后无 log.error / logger.error 且未重抛
- **敏感信息日志**：密码 / token / 身份证 / 银行卡号进日志（未脱敏）
- **堆栈暴露**：对外接口 catch 后直接返回异常 message（含栈帧信息）
- **大对象序列化日志**：直接打印含 List/嵌套对象的大 JSON
- **异常层级错误**：业务异常用 RuntimeException 而非项目统一 BusinessException

## Finding 严重度

- `critical`：异常吞没导致数据不一致无感知 / 敏感信息泄漏日志
- `major`：关键路径异常无日志 / 堆栈对外暴露
- `minor`：日志级别不当 / 注释不清晰

## 输出

返回 JSON：`{"findings": [...], "stats": {"total": N, "critical": N, "major": N, "minor": N}}`

必须给出具体 catch 块位置（file:line）。
