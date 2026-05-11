---
name: cr-checker-auxiliary-spec
node_id: cr-checker-auxiliary-spec
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

# cr-checker-auxiliary-spec：命名/注释/格式专项审查

## 职责

对 `$cr-prepare.output.diff_range` 范围内的增量检测命名规范、注释质量和代码格式问题。
读 `$cr-prepare.output.scope_file` 取增量文件清单。

## 检查重点

- **命名规范**：
  - Java：类名驼峰 / 方法名小驼峰 / 常量全大写下划线 / 包名小写
  - 变量名避免 a/b/temp/data 等无意义缩写
- **注释质量**：
  - 注释解释"为什么"，不是"做了什么"（禁止冗余注释）
  - 对外接口/核心流程必须含：入参约束 / 关键状态流转 / 失败场景
  - 禁止注释掉大段代码不删除
- **格式**：
  - 空行过多（连续 > 2 空行）
  - 行末空格 / Tab 与空格混用

## Finding 严重度

- `critical`：此维度无 critical（格式问题不影响正确性）
- `major`：对外接口缺少必要文档注释 / 关键参数无约束说明
- `minor`：命名不规范 / 冗余注释 / 格式问题

## 输出

返回 JSON：`{"findings": [...], "stats": {"total": N, "critical": 0, "major": N, "minor": N}}`
