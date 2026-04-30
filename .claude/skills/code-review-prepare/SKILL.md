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

2. **生成 .review-scope.json + 卡点 A 路由确认**：调 `python3 scripts/lib/code_review_routing.py`：
   - **默认两阶段**：脚本扫 diff 输出候选 checker_route + 跳过原因 → tty 确认（accept / all / abort / 自定义子集逗号分隔下标）→ 写盘
   - `--all`：跳过路由建议，直接用 8 全集——**仍要求 tty**（防 AI 自动加 --all 绕过卡点 A）
   - `--trivial`：仅写 mode_hint=trivial 透传给下游，**不豁免**卡点 A，仍走默认两阶段 tty 确认
   - **stdin 非 tty → 退出码 2**（拒绝 AI 在主对话直接调；abort 时不写盘、正常退出 0）

3. **触发并行 checker**：按 `.review-scope.json.checker_route` 运行对应 checker（不是固定 8 个；`decision=all` 才是 8 全集）

4. **输出预检摘要给用户**：模式、范围、增量规模，确认继续后进入并行审查阶段。

## 硬约束

- ❌ 禁止审查超过 2000 行的 diff（建议用户先拆小）
- ❌ 禁止审查未提交的 uncommitted 变化（必须先 commit 到当前分支）
- ✅ `.review-scope.json` 必须合法 JSON（预检阶段 `python3 -m json.tool` 验证）
- ✅ 独立模式必须输出"当前在独立模式，审查范围为 X"告知用户

## 参考资源

- [`reference/scope-schema.md`](reference/scope-schema.md) — ReviewScope JSON schema
