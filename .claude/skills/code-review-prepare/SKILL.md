---
name: code-review-prepare
description: /code-review 的预检 Skill。识别审查模式（独立/嵌入）、确定范围、取 diff，生成 .review-scope.json 供并行 checker 消费。
---

## 什么时候用

用户触发 `/code-review` 或 `feature-lifecycle-manager` 在 feature 完成时自动调用。

## 核心流程

1. **识别模式 + 取增量 diff**：
   - **嵌入模式**：当前分支在某个 `requirements/*/meta.yaml.branch` 中 → 从 `meta.yaml.services` 取服务列表；`git diff main...HEAD -- <services>`
   - **独立模式**：否则 → 审当前分支 vs `main` 的增量；`git diff main...HEAD`
   - 统计增量规模（修改文件数、增删行数、涉及顶级目录）

2. **输出元信息给路由器（不写盘）**：取 diff 文件列表、规模、服务列表，交由 `scripts/lib/code_review_routing.py` 统一处理

3. **自动路由**（`scripts/lib/code_review_routing.py`）：
   - **100% trivial 短路**：diff 中所有文件命中 `trivial_whitelist`（如 `**/*.md`、`requirements/*/notes.md` 等）→ routing.py 写 `skipped=true`，跳过整个 review（包括所有 8 个 checker），生成"trivial-skipped" audit 记录
   - **命中 must / suggest**：routing.py 直接按推荐集（must ∪ suggest）写 `decision=accept`，跑推荐 checker
   - **推荐集为空**（diff 全是灰色文件，未命中任何规则）：升 8 全集兜底，`decision=all`
   - 自 F-014 起取消人类 tty 卡点 A，AI / CI / 管道均可调用

4. **触发并行 checker**：按 `.review-scope.json.checker_route` 运行对应 checker（不是固定 8 个；`decision=all` 才是 8 全集）

5. **输出预检摘要给用户**：模式、范围、增量规模、路由结果，确认继续后进入并行审查阶段。

## 硬约束

- ❌ 禁止审查超过 2000 行的 diff（建议用户先拆小）
- ❌ 禁止审查未提交的 uncommitted 变化（必须先 commit 到当前分支）
- ✅ `.review-scope.json` 必须合法 JSON（预检阶段 `python3 -m json.tool` 验证）
- ✅ 独立模式必须输出"当前在独立模式，审查范围为 X"告知用户

## 参考资源

- [`reference/scope-schema.md`](reference/scope-schema.md) — ReviewScope JSON schema
