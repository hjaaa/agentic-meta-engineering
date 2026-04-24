---
name: requirement-progress-logger
description: 追加语义事件到 requirements/<id>/process.txt（追加式）。阶段切换、评审结论、门禁、阻塞、save 等"有含义的一行"走此 Skill；process.txt 唯一写入通道，不再有 Hook 竞争写入。
---

## 什么时候用

- `/requirement:save` 命令调用
- 阶段切换完成后（由 `managing-requirement-lifecycle` 调用）
- 评审结论产生后（由 `requirement-quality-reviewer` 等 Agent 间接触发）
- 用户主动说"记录一下 [事件]"

## 写入目标

唯一写入 `requirements/<id>/process.txt`。Hook 已不再写入本文件，本 Skill 是 process.txt 的**唯一写入通道**。

## 核心流程

1. **定位 `requirements/<id>/process.txt`**：
   - 从 meta.yaml 的 branch 匹配当前分支
   - 或从上下文中的需求 ID

2. **取时间戳 = 写入当下东八区 now**（不是"事件计划发生时"）
   - 格式：`YYYY-MM-DD HH:MM:SS`，时区 Asia/Shanghai（详见 `context/team/engineering-spec/time-format.md`）
   - 保证行序与时序一致（必须 append 瞬间取 now）
   - 推荐命令：`TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M:%S"`

3. **格式化日志行**：
   ```
   YYYY-MM-DD HH:MM:SS [phase] 事件描述
   ```
   例：
   ```
   2026-04-20 19:02:08 [review:needs_revision] requirement-quality-reviewer 3 条 major
   2026-04-20 19:16:00 [phase-transition] definition → tech-research
   ```

4. **追加到文件末尾**（**绝不覆盖**）

## 硬约束

- ❌ 禁止覆盖写入（只能 `>>` append）
- ❌ 禁止缺时间戳
- ❌ 禁止使用其他时区或其他格式（格式见 `context/team/engineering-spec/time-format.md`）
- ❌ 禁止预先计算时间戳再写入（必须在 append 那一刻取 now，消除时序倒流）
- ✅ `phase` 字段必须与 `meta.yaml.phase` 一致（阶段切换时单次例外：写 `phase-transition`）
- ✅ 每行一条事件，事件描述 < 100 字符

## 事件标签白名单

| Tag | 含义 | 触发方 |
|---|---|---|
| `[phase-transition]` | 阶段切换 | `managing-requirement-lifecycle` → 本 Skill |
| `[save]` | 用户 `/requirement:save` 显式存档 | 命令 → 本 Skill |
| `[review:approved\|needs_revision\|rejected]` | 评审结论 | 评审 Agent → 本 Skill |
| `[gate:pass\|fail]` | 门禁结果 | `managing-requirement-lifecycle` → 本 Skill |
| `[blocker]` | 阻塞发生：现象 + 初步判断/下一步 | 主 Agent → 本 Skill |
| `[blocker-resolved]` | 阻塞解除：根因 + 解决方式 | 主 Agent → 本 Skill |

**不在白名单**：`[decision]`（改走 `plan.md` ADR）、`[issue]`（合并到 `[blocker]`）、`[SESSION_END]`（Hook 已删，不再写）、`[tool=*]`（Hook 已删，不再写）。

**blocker 行为约定**：见 `../managing-requirement-lifecycle/reference/blocker-conventions.md`。
