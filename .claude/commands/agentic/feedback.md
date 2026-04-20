---
description: 把反馈写入 feedback-log.yaml（praise / complaint / suggestion / bug）
argument-hint: <type> <target> <body>
---

## 用途

团队成员日常有问题/建议时快速记录。

## 预检

1. `context/team/feedback-log.yaml` 存在且 YAML 合法
2. 3 个参数：
   - `type` ∈ {praise, complaint, suggestion, bug}（必填）
   - `target` 格式形如 `agent:<name>` / `skill:<name>` / `command:<name>` / `hook:<name>` / `docs` / `other`（必填）
   - `body` 简体中文正文（必填）
3. `body` 不含敏感信息（简单 regex 扫 `password|token|api[_-]?key|secret`）——命中则阻止并提示

## 行为

不委托 Skill：

1. 生成 entry id：`YYYYMMDD-NNN`（NNN 按当日已有条目数 +1）
2. 读 `git config user.email` 作为 `user`
3. 构造 YAML entry：
   ```yaml
   - id: <id>
     at: <ISO8601>
     user: <email>
     type: <type>
     target: <target>
     body: <body>
     resolved: false
     resolution: null
   ```
4. append 到 `context/team/feedback-log.yaml` 的 `entries` 列表
5. `python3 -c "import yaml; yaml.safe_load(open('context/team/feedback-log.yaml'))"` 验证
6. Commit：
   ```
   git add context/team/feedback-log.yaml
   git commit -m "feedback(<type>): <target> — <body 首 30 字符>"
   ```
7. 输出条目 ID 给用户

## 硬约束

- 敏感信息扫描必须做，命中即拒绝写入
- commit 前必须 YAML 合法
