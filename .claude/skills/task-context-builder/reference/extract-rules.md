# 提取规则

## 从 features.json 提取

JSON 结构约定：
```json
{
  "features": [
    {
      "id": "F-001",
      "title": "用户注册",
      "description": "支持邮箱+密码注册，自动发送验证邮件",
      "interfaces": [
        {"name": "POST /api/users", "schema_ref": "detailed-design.md#user-create-api"}
      ],
      "dependencies": ["email-service"],
      "notes": "邮件模板和 email-service 对齐"
    }
  ]
}
```

提取：`features.json` 中 `id == feature_id` 的那条完整对象（JSON stringify 即可）。

## 从 detailed-design.md 提取

匹配规则（优先级降序）：

1. HTML 锚点匹配：`schema_ref` 中的 `#xxx` 部分 → grep `<a id="xxx">` 或 `{#xxx}`
2. 标题匹配：查找包含 feature_id 的章节标题（如 `## F-001: 用户注册`）
3. 注释匹配：`<!-- @feature:F-001 -->` 块

提取整个段落（直到下一个同级标题）。

## 从代码库提取

**仅在开发阶段需要时**提取：

- grep 接口路径（如 `/api/users`）的现有实现
- grep 数据结构名（如 `UserCreateRequest`）
- `features.json` 的 `dependencies` 字段列出的模块

**不要**：

- 全量 `ls` 代码目录
- 读整个大文件

## 输出格式

```markdown
# F-001 · 用户注册 — 开发上下文

## 需求描述

支持邮箱+密码注册，自动发送验证邮件。

## 接口

### POST /api/users

- 请求：`UserCreateRequest { email, password }`
- 响应：`UserCreateResponse { id, verificationSent }`
- 设计详情：see `artifacts/detailed-design.md:L120-L145`

## 依赖模块

- `email-service` — 邮件发送（已有接口 `SendEmail(template, to, data)`）

## 相关现有代码

- 用户实体：`src/entity/User.java:15`
- 邮箱验证旧流程（参考）：`src/service/EmailVerifier.java:88`

## 注意事项

邮件模板和 email-service 对齐（来自 features.json.notes）
```
