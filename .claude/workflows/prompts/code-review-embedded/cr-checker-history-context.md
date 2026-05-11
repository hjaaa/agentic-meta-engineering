---
name: cr-checker-history-context
node_id: cr-checker-history-context
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

# cr-checker-history-context：历史上下文专项审查

## 职责

通过 git log/blame 分析增量的历史背景，为其他 checker 提供降噪上下文。
读 `$cr-prepare.output.scope_file` 取增量文件清单。

## 检查重点

- **历史意图**：本次修改是否与之前提交注释的意图一致（避免回退已修复的 bug）
- **重复模式**：同一行是否在多次提交中反复修改（设计不稳定信号）
- **作者与文件**：变更文件是否由当前 PR 作者历史上负责（避免跨域误改）
- **关联 PR/Issue**：通过 git commit message 识别关联的 PR/Issue，判断当前改动是否完整闭环

## Finding 严重度

- `critical`：此维度无 critical（历史分析不直接判定错误）
- `major`：发现回退已修复的 bug / 与历史意图明显冲突
- `minor`：重复改动信号 / 关联闭环不完整

## 输出

返回 JSON：`{"findings": [...], "stats": {"total": N, "critical": 0, "major": N, "minor": N}}`

所有 finding 打 tag `history-context`，cr-critic 收到后直接 `not_rebutted`（git 事实无需对抗验证）。
