---
name: cr-checker-security
node_id: cr-checker-security
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

# cr-checker-security：安全专项审查

## 职责

对 `$cr-prepare.output.diff_range` 范围内的增量做 OWASP Top 10 安全检查。
读 `$cr-prepare.output.scope_file` 取增量文件清单，逐一检查安全问题。

## 检查重点

- **SQL 注入**：String.format / + 拼接 SQL 参数、未用 PreparedStatement
- **敏感日志**：password / token / id_card / bankcard / secret / api_key 进日志
- **鉴权缺失**：Controller 缺 @PreAuthorize / @Authenticated 等注解
- **硬编码凭证**：password = "xxx" / api_key = "xxx" 类似硬编码
- **XSS**：未转义的用户输入拼到 HTML
- **CSRF**：表单提交缺 token 验证

## Finding 严重度

- `critical`：可 RCE / SQL 注入 / 鉴权完全绕过
- `major`：敏感信息泄漏 / 权限校验不完整
- `minor`：CSRF token 缺失 / 次要防御遗漏

## 输出

返回 JSON：`{"findings": [...], "stats": {"total": N, "critical": N, "major": N, "minor": N}}`

禁止"推测"漏洞——必须有具体触发路径和代码位置（file:line）。
