---
name: requirement-progress-logger
description: 追加语义事件到 requirements/<id>/process.txt（追加式）。阶段切换、评审结论、门禁、阻塞、save 等"有含义的一行"走此 Skill；process.txt 唯一写入通道，不再有 Hook 竞争写入。
---

## 什么时候用

- `/requirement:save` 命令调用
- 阶段切换完成后（由 `/workflow:next [F-012 待落地]` 经 standard-8phase yaml workflow phase-transition 节点调用）
- 评审结论产生后（由 `requirement-quality-reviewer` 等 Agent 间接触发）
- 用户主动说"记录一下 [事件]"

## 写入目标

唯一写入 `requirements/<id>/process.txt`。Hook 已不再写入本文件，本 Skill 是 process.txt 的**唯一写入通道**。

## 核心流程

1. **定位需求 ID**：
   - 从 meta.yaml 的 branch 匹配当前分支
   - 或从上下文中已有的需求 ID

2. **通过 CLI 写入**（**唯一允许的写入方式**，禁止直接 `printf >> process.txt`）：
   ```bash
   python3 scripts/lib/log_process.py \
     --req <REQ-ID> \
     --tag <tag> \
     "<事件描述>"
   ```
   CLI 内部负责：
   - 取写入瞬间的 Asia/Shanghai now 作为时间戳（`datetime.now(_CST)`，与 archive_runner / submit_codex 同源 `_CST = timezone(timedelta(hours=8))`，详见 `context/team/engineering-spec/time-format.md`）
   - 校验 tag 是否在白名单（见下表）
   - 校验消息体非空 + strip CR/LF 防多行注入
   - 以 `"a"` 模式 append 写入 `requirements/<REQ-ID>/process.txt`，**绝不覆盖**

3. **示例**：
   ```bash
   python3 scripts/lib/log_process.py --req REQ-2026-001 \
     --tag review:needs_revision "requirement-quality-reviewer 3 条 major"
   # → 2026-04-20 19:02:08 [review:needs_revision] requirement-quality-reviewer 3 条 major

   python3 scripts/lib/log_process.py --req REQ-2026-001 \
     --tag phase-transition "definition → tech-research"
   # → 2026-04-20 19:16:00 [phase-transition] definition → tech-research
   ```

## 硬约束

- ❌ 禁止直接 `printf >> process.txt` / `echo >> process.txt` / Edit 工具改 process.txt——所有写入必须经 `scripts/lib/log_process.py` CLI
  - 例外：脚本侧已有自己的 `_append_process_event` 实现（archive_runner / submit_codex / code_review_routing），保持现状不变；它们共享同一 `_CST` 时区常量
- ❌ 禁止覆盖写入（CLI 内部用 `"a"` 模式，调用方不必关心）
- ❌ 禁止预先计算时间戳再写入（CLI 强制 append 瞬间取 now，消除时序倒流）
- ❌ 禁止使用白名单外的 tag（CLI 用正则校验，不符合直接 exit 1）
- ✅ `tag` 含语义即与 `meta.yaml.phase` 对齐由调用方负责（CLI 不校验语义一致性，只校验枚举值）
- ✅ 每行一条事件；事件描述建议 < 200 字符（CLI 不强制，但 tail 可读性优先）

## 事件标签白名单

| Tag | 含义 | 触发方 |
|---|---|---|
| `[phase-transition]` | 阶段切换 | `/workflow:next [F-012 待落地]` → workflow phase-transition 节点 → 本 Skill |
| `[save]` | 用户 `/requirement:save` 显式存档 | 命令 → 本 Skill |
| `[review:approved\|needs_revision\|rejected]` | 评审结论 | 评审 Agent → 本 Skill |
| `[gate:pass\|fail]` | 门禁结果 | `/workflow:next [F-012 待落地]` / `/requirement:submit` → 本 Skill |
| `[blocker]` | 阻塞发生：现象 + 初步判断/下一步 | 主 Agent → 本 Skill |
| `[blocker-resolved]` | 阻塞解除：根因 + 解决方式 | 主 Agent → 本 Skill |
| `[archived]` | 需求归档完成 (PR #N merged at <ts>) | `archive_runner` → 本 Skill |
| `[codex-review-triggered]` | `round=N pr=#num` | `submit_codex` → 本 Skill |
| `[codex-review-received]` | `verdict=passed\|not_passed\|timeout round=N` | `submit_codex` → 本 Skill |

**不在白名单**：`[decision]`（改走 `plan.md` ADR）、`[issue]`（合并到 `[blocker]`）、`[SESSION_END]`（Hook 已删，不再写）、`[tool=*]`（Hook 已删，不再写）。

**blocker 行为约定**：见 `../managing-requirement-lifecycle/reference/blocker-conventions.md`。
