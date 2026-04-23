---
name: requirement-progress-logger
description: 追加语义事件到 requirements/<id>/process.txt（追加式）。阶段切换、评审结论、门禁、决策、save 等"有含义的一行"走此 Skill；工具级自动日志由 Hook 写入 process.tool.log（v2 布局）或 process.txt（legacy 布局），不在此 Skill 职责内。
---

## 什么时候用

- `/requirement:save` 命令调用
- 阶段切换完成后（由 `managing-requirement-lifecycle` 调用）
- 评审结论产生后（由 `requirement-quality-reviewer` 等 Agent 间接触发）
- 用户主动说"记录一下 [事件]"

## 日志布局（v2 分层 vs legacy）

由 `meta.yaml` 的 `log_layout` 字段决定：

| 值 | process.txt | process.tool.log |
|---|---|---|
| `split`（新需求默认） | 语义事件（本 Skill + `stop-session-save` Hook） | 工具日志（`auto-progress-log` Hook） |
| `legacy`（老需求，缺字段视同此值） | 语义事件 + 工具日志混写 | 不使用 |

**本 Skill 只关心 process.txt**——无论哪种布局，语义事件永远写 process.txt。

## 核心流程

1. **定位 `requirements/<id>/process.txt`**：
   - 从 meta.yaml 的 branch 匹配当前分支
   - 或从上下文中的需求 ID

2. **取时间戳 = 写入当下 UTC now**（不是"事件计划发生时"）
   - 避免 Hook 和 Skill 竞争写入时行序与时序错位
   - 推荐命令：`date -u +"%Y-%m-%dT%H:%M:%SZ"`

3. **格式化日志行**：
   ```
   ISO8601 [phase] 事件描述
   ```
   例：
   ```
   2026-04-20T11:02:08Z [review:needs_revision] requirement-quality-reviewer 3 条 major
   2026-04-20T11:16:00Z [phase-transition] definition → tech-research
   ```

4. **追加到文件末尾**（**绝不覆盖**）

## 硬约束

- ❌ 禁止覆盖写入（只能 `>>` append）
- ❌ 禁止缺 ISO8601 时间戳
- ❌ 禁止预先计算时间戳再写入（必须在 append 那一刻取 now，消除时序倒流）
- ❌ 禁止把工具级事件（Edit/Write/Bash）写进 process.txt（Hook 职责）
- ✅ `phase` 字段必须与 `meta.yaml.phase` 一致（阶段切换时单次例外：写 `phase-transition`）
- ✅ 每行一条事件，事件描述 < 100 字符

## 已知场景标签

- `[phase-transition]` — 阶段切换
- `[review:<result>]` — 评审结论（result = approved/needs_revision/rejected）
- `[gate:<pass|fail>]` — 门禁检查结果
- `[decision]` — 关键决策（方案选型 / 契约 / 放弃分支）
- `[issue]` / `[blocker]` — 发现的坑 / 阻塞项（指向 notes.md 行号）
- `[save]` — 用户 `/requirement:save` 触发的显式存档
- `[SESSION_END]` — 会话结束（`stop-session-save` Hook 自动写）
- `[tool=<名>]` — 工具级自动日志（**v2 下写 process.tool.log；legacy 下写 process.txt**）
