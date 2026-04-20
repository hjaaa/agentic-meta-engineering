---
id: REQ-2026-001
refs-requirement: artifacts/requirement.md
refs-outline: artifacts/outline-design.md
created_at: 2026-04-20T15:45:00Z
---

# REQ-2026-001 详细设计

## 插入位置（精确）

`CLAUDE.md` 中"未实现清单"段之后、"反馈"段之前插入一个新的 `##` 级别段。

## 新增段结构（严格）

<!-- @feature:F-001 -->
```
## Common Pitfalls

新人使用骨架时最容易踩的 5 个坑。每条按「症状 / 原因 / 修复」三段式。

### 1. 在 main 分支直接 Edit 被 Hook 拦截
- **症状**：执行 Edit / Write 工具报错 "禁止在受保护分支..."
- **原因**：`.claude/hooks/protect-branch.sh` 对 Edit/Write 在 main/master 分支做阻塞
- **修复**：切到 feature 分支再操作，或运行 `/requirement:new` 自动建分支

### 2. `/note` 后 notes.md 没更新
- **症状**：跑完 `/note` 后 ls 不到对应文件的新行
- **原因**：当前分支没匹配到 `requirements/*/meta.yaml` 的 branch 字段
- **修复**：先 `/requirement:new` 或 `/requirement:continue` 绑定到某个需求

### 3. Command 超过 100 行或 SKILL.md 超过 2k token
- **症状**：新写的 Command / Skill 行为不稳定
- **原因**：违反 `context/team/engineering-spec/tool-design-spec/` 的硬约束
- **修复**：Command 拆到委托 Skill；Skill 内容拆到 `reference/`

### 4. 需求文档写了"看起来合理"但无来源的事实
- **症状**：`requirement-quality-reviewer` 返回 `needs_revision`
- **原因**：违反刨根问底三态（有引用 / 待确认 / 待补充），出现了第四态"无来源但合理"
- **修复**：按 `.claude/skills/requirement-doc-writer/reference/sourcing-rules.md` 补标注

### 5. /code-review 审查范围 > 2000 行被拒绝
- **症状**：`/code-review` 预检阶段终止并提示"范围过大"
- **原因**：`code-review-prepare` 硬约束不审超 2000 行 diff
- **修复**：按 feature_id 拆分提交，或 `/requirement:rollback` 回前阶段重新拆
```

## features.json

单个 feature：在 CLAUDE.md 注入 Common Pitfalls 段。

## 接口

无新接口。

## 时序

无。

## 评审要点

- 每条坑都有可观测症状（用户能自己发现）
- 每条修复都是具体动作（不是"多加注意"之类的虚话）
- 5 条覆盖了：Hook / Skill / Command / 刨根问底 / 代码审查 五个关键子系统
