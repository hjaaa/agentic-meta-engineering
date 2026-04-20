---
name: requirement-progress-logger
description: 追加进度日志到 requirements/<id>/process.txt。追加式（append-only），用于关键节点显式记录。Hook 已处理工具级自动记录，此 Skill 用于阶段切换、评审结论等语义级事件。
---

## 什么时候用

- `/requirement:save` 命令调用
- 阶段切换完成后（由 `managing-requirement-lifecycle` 调用）
- 评审结论产生后（由 `requirement-quality-reviewer` 等 Agent 间接触发）
- 用户主动说"记录一下 [事件]"

## 核心流程

1. **定位 `requirements/<id>/process.txt`**：
   - 从 meta.yaml 的 branch 匹配当前分支
   - 或从上下文中的需求 ID

2. **格式化日志行**：
   ```
   ISO8601 [phase] 事件描述
   ```
   例：
   ```
   2026-04-20T11:02:08Z [review:pending] requirement-quality-reviewer 结论 needs_revision（3 条 major）
   2026-04-20T11:16:00Z [phase-transition] definition → tech-research
   ```

3. **追加到文件末尾**（**绝不覆盖**）

## 硬约束

- ❌ 禁止覆盖写入（只能 `>>` append）
- ❌ 禁止缺 ISO8601 时间戳
- ✅ `phase` 字段必须与 `meta.yaml.phase` 一致（阶段切换时单次例外：写 `phase-transition`）
- ✅ 每行一条事件，事件描述 < 100 字符

## 已知场景标签

- `[phase-transition]` — 阶段切换
- `[review:<result>]` — 评审结论（result = approved/needs_revision/rejected）
- `[gate:<pass|fail>]` — 门禁检查结果
- `[SESSION_END]` — 会话结束（Hook 自动写）
- `[tool=<名>]` — 工具级自动日志（Hook 自动写）
