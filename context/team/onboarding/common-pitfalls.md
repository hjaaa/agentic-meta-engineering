# Common Pitfalls

> 最近更新：2026-04-23

新人使用骨架时最容易踩的 8 个坑。每条按「症状 / 原因 / 修复」三段式。

## 1. 在 main / develop 分支直接 Edit 被 Hook 拦截
- **症状**：执行 Edit / Write 工具报错 "禁止在受保护分支..."
- **原因**：`.claude/hooks/protect-branch.sh` 对 Edit/Write 在 **main / master / develop** 分支做阻塞
- **修复**：切到 feature 分支再操作，或运行 `/requirement:new` 自动建分支（默认从 develop 派生）

## 2. `/note` 后 notes.md 没更新
- **症状**：跑完 `/note` 后 ls 不到对应文件的新行
- **原因**：当前分支没匹配到 `requirements/*/meta.yaml` 的 branch 字段
- **修复**：先 `/requirement:new` 或 `/requirement:continue` 绑定到某个需求

## 3. Command 超过 100 行或 SKILL.md 超过 2k token
- **症状**：新写的 Command / Skill 行为不稳定
- **原因**：违反 `context/team/engineering-spec/tool-design-spec/` 的硬约束
- **修复**：Command 拆到委托 Skill；Skill 内容拆到 `reference/`

## 4. 需求文档写了"看起来合理"但无来源的事实
- **症状**：`requirement-quality-reviewer` 返回 `needs_revision`
- **原因**：违反刨根问底三态（有引用 / 待确认 / 待补充），出现了第四态"无来源但合理"
- **修复**：按 `.claude/skills/requirement-doc-writer/reference/sourcing-rules.md` 补标注

## 5. /code-review 审查范围 > 2000 行被拒绝
- **症状**：`/code-review` 预检阶段终止并提示"范围过大"
- **原因**：`code-review-prepare` 硬约束不审超 2000 行 diff
- **修复**：按 feature_id 拆分提交，或 `/requirement:rollback` 回前阶段重新拆

## 6. PR 目标分支错选 main
- **症状**：`/requirement:submit` 开出的 PR target 是 main，绕过了 develop 的集成验证
- **原因**：`meta.yaml.base_branch` 缺失或被手动改成 main；或仓库尚未启用 develop 分支
- **修复**：
  - 仓库未启用 develop：按 `context/team/git-workflow.md` "首次启用 develop" 小节执行
  - 已启用：`/requirement:submit --target develop` 显式指定，或修正 `meta.yaml.base_branch`

## 7. `/requirement:submit` 反复失败说 "无审查报告"
- **症状**：预检报 `artifacts/code-review-reports/` 为空
- **原因**：尚未跑过 `/code-review`，或报告落在了其他路径
- **修复**：先 `/code-review` 生成报告，确认路径为 `artifacts/code-review-reports/*.md`

## 8. 所有改动都走 `/requirement:new` 把小事拖重
- **症状**：改 3 行代码或加一条注释也建了 `requirements/<id>/`，8 阶段门禁来回卡
- **原因**：误以为 `/requirement:new` 是唯一入口，忽视了"直通分支"路径
- **修复**：对照 `/agentic:help fast-path` 的"选择三问"——不需要跨会话恢复 + 不需要设计评审 + 不需要追溯链 → 切 feature 分支直接改 + `/code-review` + PR，不建需求目录
