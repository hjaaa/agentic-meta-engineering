---
name: code-review-prepare
description: /code-review 的预检 Skill。识别审查模式（独立/嵌入）、确定范围、取 diff，生成 .review-scope.json 供并行 checker 消费。
---

## 什么时候用

用户触发 `/code-review` 或 `feature-lifecycle-manager` 在 feature 完成时自动调用。

## 核心流程

1. **识别模式**：
   - **嵌入模式**：当前分支在某个 `requirements/*/meta.yaml.branch` 中 → 从 `meta.yaml.services` 取服务列表
   - **独立模式**：否则 → 审当前分支 vs `main` 的增量

2. **取增量 diff**：
   - 嵌入：`git diff main...HEAD -- <services>`
   - 独立：`git diff main...HEAD`

3. **统计增量规模**：
   - 修改文件数
   - 增加/删除行数
   - 涉及的顶级目录

4. **写 `.review-scope.json`**（根目录，`.gitignore` 已覆盖）：
   按 `reference/scope-schema.md` 的 schema。

5. **输出预检摘要给用户**：模式、范围、增量规模，确认继续后触发并行审查。

## 硬约束

- ❌ 禁止审查超过 2000 行的 diff（建议用户先拆小）
- ❌ 禁止审查未提交的 uncommitted 变化（必须先 commit 到当前分支）
- ✅ `.review-scope.json` 必须合法 JSON（预检阶段 `python3 -m json.tool` 验证）
- ✅ 独立模式必须输出"当前在独立模式，审查范围为 X"告知用户

## 参考资源

- [`reference/scope-schema.md`](reference/scope-schema.md) — ReviewScope JSON schema
