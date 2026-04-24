# 溢出区三文件重定义 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把溢出区的三个文件（process.txt / notes.md / plan.md）职责收敛到各自的 slogan，删除 process.tool.log 与两个 Hook，并让全部相关 Skill / 模板 / 配置 / 主 spec 文档一次性同步。

**Architecture:** 先改"被引用的规范载体"（Skill/模板），再删"运行时行为"（Hook + settings），最后对齐"主 spec 文档"保证一致性。每个文件一个独立 commit，出问题可单点回滚。

**Tech Stack:** 本仓库是 Claude Code 骨架，不是传统代码项目，没有 pytest/junit。任务验证使用 `grep` / `test` / `cat` 等 shell 断言，每个 task 的 "验证" 步骤必须真的执行并检查输出。

**前置条件：**
- 当前分支：`feature/spillover-redefine`（已从 `develop` 切出）
- 设计文档已 approve：`context/team/engineering-spec/specs/2026-04-24-spillover-redefine-design.md`（commit `415ef6a`）
- 仓库根：`/Users/richardhuang/learnspace/agentic-meta-engineering`

**显式不做（Out of Scope）：**
- **不批量改动老 `requirements/*/` 目录下任何文件**。老 `process.txt` 里的 `tool=` / `SESSION_END` / `[decision]` / `[issue]` 行保留原样；老 `meta.yaml` 的 `log_layout` 字段保留；老 `plan.md` 不补"决策记录"段（由下次首次追加 ADR 时顺带补齐）
- 不写迁移脚本
- 不改 `protect-branch.sh`（该 Hook 保留）
- 不跑端到端冒烟（冒烟要在新建的测试需求里做，属于 PR 合并后的验证，不在本计划内）

---

## File Structure

本计划修改的文件清单（按执行顺序）：

**Create:**
- `.claude/skills/managing-requirement-lifecycle/reference/blocker-conventions.md` — blocker / blocker-resolved 的行为约定参考文档（新建，供 Skill 引用）

**Modify:**
- `.claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl` — 移除 `log_layout` 行
- `.claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl` — 追加「决策记录」段
- `.claude/skills/requirement-progress-logger/SKILL.md` — 更新事件标签白名单、去 log_layout、删"工具级事件"相关说明
- `.claude/skills/requirement-session-restorer/SKILL.md` — 去 process.tool.log tail / log_layout 判断 / SESSION_END 过滤；新增 ADR 最近一条入摘要
- `.claude/skills/managing-requirement-lifecycle/SKILL.md` — 参考资源清单加 blocker-conventions.md
- `.claude/commands/note.md` — 补"blocker 不走 /note"说明
- `.claude/settings.json` — 删除 PostToolUse + Stop 两个 hook 注册
- `.gitignore` — 删除 `requirements/**/process.tool.log` 条目
- `context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md` — 同步 §6.1 / §6.2 / §6.3 / §6.4 / §6.6 / §7.1

**Delete:**
- `.claude/hooks/auto-progress-log.sh`
- `.claude/hooks/stop-session-save.sh`

---

## Task 1: 清理 .gitignore 中的 process.tool.log 条目

**Files:**
- Modify: `.gitignore:22-24`

- [ ] **Step 1: 验证当前 .gitignore 末段确实有 process.tool.log 相关三行**

Run:
```bash
sed -n '22,24p' .gitignore
```

Expected 输出：
```
# 需求运行态：工具级日志（auto-progress-log Hook 写入，高频噪音）
# 语义事件仍在 process.txt，入 git；此处仅排除工具日志
requirements/**/process.tool.log
```

- [ ] **Step 2: 用 Edit 工具删除这三行**

删除 `.gitignore` 文件末尾的如下 3 行（含前面的空行分隔符一并处理——确认删除后末行是 `*.pyc`）：

```
# 需求运行态：工具级日志（auto-progress-log Hook 写入，高频噪音）
# 语义事件仍在 process.txt，入 git；此处仅排除工具日志
requirements/**/process.tool.log
```

- [ ] **Step 3: 验证删除后 .gitignore 不再包含 process.tool.log**

Run:
```bash
grep -c 'process.tool.log' .gitignore || echo "0 matches (expected)"
```

Expected: `0 matches (expected)`

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore(gitignore): 移除 process.tool.log 条目

process.tool.log 已从溢出区设计中移除（见 specs/2026-04-24-spillover-redefine-design.md），
Hook 不再写入该文件，.gitignore 条目同步清理。"
```

---

## Task 2: 模板 meta.yaml.tmpl 删除 log_layout 字段

**Files:**
- Modify: `.claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl:15`

- [ ] **Step 1: 验证当前模板第 15 行是 log_layout**

Run:
```bash
sed -n '15p' .claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl
```

Expected 输出（含 log_layout 字样）：
```
log_layout: split              # split（默认，工具日志→process.tool.log / 语义事件→process.txt） | legacy（老格式，全写 process.txt）
```

- [ ] **Step 2: 用 Edit 工具删除该行**

删除 `.claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl` 中精确匹配的这一行：

```
log_layout: split              # split（默认，工具日志→process.tool.log / 语义事件→process.txt） | legacy（老格式，全写 process.txt）
```

删除后上一行（`pr_number: 0` 那行）下面直接接空行 + `# ============ 语义组` 注释块。

- [ ] **Step 3: 验证模板不再含 log_layout**

Run:
```bash
grep -c 'log_layout' .claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl || echo "0 matches (expected)"
```

Expected: `0 matches (expected)`

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl
git commit -m "refactor(template): 从 meta.yaml 模板移除 log_layout 字段

log_layout 是 v1/v2 工具日志分层的遗留控制字段，本次重定义已取消分层，
新建需求不再需要该字段。老 meta.yaml 的旧字段保留（Skill 不再读）。"
```

---

## Task 3: 模板 plan.md.tmpl 新增「决策记录」段

**Files:**
- Modify: `.claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl`

- [ ] **Step 1: 读取当前模板确认结尾结构**

Run:
```bash
cat .claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl
```

Expected: 末尾是「## 风险」段 + 一行示例。

- [ ] **Step 2: 用 Edit 工具在文件末尾追加「决策记录」段**

在 `.claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl` 的最后一行（`- 风险 1：描述 / 应对`）之后，追加：

```markdown

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 <决策标题>
- **Context**：做决策时的背景 / 约束
- **Decision**：选了什么，没选什么
- **Consequences**：好的后果、不好的后果
- **时间**：YYYY-MM-DD HH:MM:SS
- **Supersedes**：D-NNN（废弃前一决策时才有）
```

- [ ] **Step 3: 验证模板新增段落**

Run:
```bash
grep -c '## 决策记录' .claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl
```

Expected: `1`

Run:
```bash
grep -c 'D-001' .claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl
```

Expected: `1`

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl
git commit -m "feat(template): plan.md 模板新增「决策记录」ADR 段

新建需求的 plan.md 会自带决策记录骨架，影响架构/契约/工期/依赖的决策
追加为 ### D-NNN 小节，废弃旧决策通过 Supersedes 指向。
详见 specs/2026-04-24-spillover-redefine-design.md §3.3。"
```

---

## Task 4: 新建 blocker-conventions.md 参考文档

**Files:**
- Create: `.claude/skills/managing-requirement-lifecycle/reference/blocker-conventions.md`

- [ ] **Step 1: 用 Write 工具创建新文件**

创建 `.claude/skills/managing-requirement-lifecycle/reference/blocker-conventions.md`，内容：

````markdown
# 阻塞事件行为约定

主 Agent 识别与记录阻塞（blocker）和阻塞解除（blocker-resolved）的行为准则。本文档由 `managing-requirement-lifecycle` Skill 引用。

## 触发 `[blocker]`（满足任一即主 Agent 委托 logger 写入）

- 用户明确说"我卡住了" / "不知道怎么办" / "这里过不去"
- 主 Agent 连续 2 次（含）以上尝试同一问题未解决
- 外部依赖不可用（接口超时、文档缺失、授权问题）

## 触发 `[blocker-resolved]`

- 用户说"搞定了" / "解决了" / "可以继续了"
- 主 Agent 验证问题消失（重跑成功、接口通了）

## 格式约束

- blocker：`[blocker] <现象 30 字内> / <初步判断或下一步>`
- blocker-resolved：`[blocker-resolved] <根因或解决方式>`
- 整行 ≤ 100 字符；单行装不下时拆多条 `[blocker]` 追加（每条一个关键节点）

## 判断原则

- 不确定是否要记时**倾向写**。漏记比误记代价高
- 连续同类 blocker（同一原因反复触发）合并成一条，避免刷屏
- 阻塞详情**只走 process.txt**；过程中提炼出的可复用知识另行 append `notes.md`（非 1:1 对应）

## 示例

```
2026-04-24 10:20:10 [definition] [blocker] DB 主键冲突，怀疑唯一索引重复
2026-04-24 10:35:40 [definition] [blocker] 验证：XX 表索引正常，方向转向数据层
2026-04-24 11:45:00 [definition] [blocker-resolved] batchInsert 没去重，已补 distinct
```

## 不走 /note

用户使用 `/note` 只写 notes.md（跨需求可复用经验）。blocker 是**当前需求的时间线状态**，不属于 notes.md 的语义，也不应该走 `/note`。
````

- [ ] **Step 2: 验证文件创建成功**

Run:
```bash
test -f .claude/skills/managing-requirement-lifecycle/reference/blocker-conventions.md && echo "exists"
```

Expected: `exists`

Run:
```bash
grep -c 'blocker-resolved' .claude/skills/managing-requirement-lifecycle/reference/blocker-conventions.md
```

Expected: 至少 `3`（标题 + 触发条件 + 示例）

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/managing-requirement-lifecycle/reference/blocker-conventions.md
git commit -m "docs(skill): 新增 blocker 行为约定参考文档

定义主 Agent 如何识别与记录 blocker / blocker-resolved 事件的触发条件、
格式约束、判断原则。由 managing-requirement-lifecycle Skill 引用。"
```

---

## Task 5: 改 requirement-progress-logger SKILL 事件白名单

**Files:**
- Modify: `.claude/skills/requirement-progress-logger/SKILL.md`

- [ ] **Step 1: 确认当前 SKILL.md 的已知场景标签段与 description**

Run:
```bash
cat .claude/skills/requirement-progress-logger/SKILL.md
```

- [ ] **Step 2: 用 Edit 工具整段替换「日志布局」「已知场景标签」等段**

在 `.claude/skills/requirement-progress-logger/SKILL.md` 做如下替换：

**替换 1**：把 description 里 "工具级自动日志由 Hook 写入 process.tool.log（v2 布局）或 process.txt（legacy 布局），不在此 Skill 职责内。" 改为 "工具级自动日志功能已移除，process.txt 由本 Skill 单通道写入。"

具体把第 3 行整行替换为：
```
description: 追加语义事件到 requirements/<id>/process.txt（追加式）。阶段切换、评审结论、门禁、阻塞、save 等"有含义的一行"走此 Skill；process.txt 唯一写入通道，不再有 Hook 竞争写入。
```

**替换 2**：把整段「## 日志布局（v2 分层 vs legacy）」连同下面的表格和 "**本 Skill 只关心 process.txt**——无论哪种布局，语义事件永远写 process.txt。" 这一句，整段删除，替换为：

```markdown
## 写入目标

唯一写入 `requirements/<id>/process.txt`。Hook 已不再写入本文件，本 Skill 是 process.txt 的**唯一写入通道**。
```

**替换 3**：「## 硬约束」段里，把这一行
```
- ❌ 禁止把工具级事件（Edit/Write/Bash）写进 process.txt（Hook 职责）
```
整行删除（Hook 职责已不存在）。

**替换 4**：「## 已知场景标签」整段替换为：

```markdown
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
```

- [ ] **Step 3: 验证**

Run:
```bash
grep -c 'process.tool.log\|log_layout\|legacy\|split' .claude/skills/requirement-progress-logger/SKILL.md || echo "0 matches (expected)"
```

Expected: `0 matches (expected)`

Run:
```bash
grep -c 'blocker-resolved' .claude/skills/requirement-progress-logger/SKILL.md
```

Expected: `>= 2`

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/requirement-progress-logger/SKILL.md
git commit -m "refactor(skill): logger 事件标签白名单化，移除 v1/v2 分层

- 删 log_layout 分支逻辑与 process.tool.log 相关说明
- 事件标签白名单：phase-transition / save / review / gate / blocker / blocker-resolved
- 明示 decision / issue / SESSION_END / tool= 不在白名单
- 指向 blocker-conventions.md 作为行为约定"
```

---

## Task 6: 改 requirement-session-restorer SKILL

**Files:**
- Modify: `.claude/skills/requirement-session-restorer/SKILL.md`

- [ ] **Step 1: 读取当前文件**

Run:
```bash
cat .claude/skills/requirement-session-restorer/SKILL.md
```

- [ ] **Step 2: 用 Edit 工具整段替换「核心流程」**

把「## 核心流程」下的第 2 步（「**读取四个文件**（**按顺序**）：」下整个 bullet 块）整段替换为：

```markdown
2. **读取三个文件**（**按顺序**）：
   - `meta.yaml` → 取当前阶段
   - `process.txt` 末 50 行 → **语义事件**（phase-transition / save / review / gate / blocker / blocker-resolved）
     - 遇到非白名单 tag（如老需求遗留的 `[decision]` / `[issue]` / `[SESSION_END]` / `tool=*`）**直接忽略**，不计入信号密度统计
   - `notes.md` → 已发现的坑 / 待澄清
   - `plan.md` → 当前计划 + 决策记录
     - 扫「## 决策记录」段，取**最新一条 `### D-NNN`**的标题与 Decision 字段，写入恢复摘要的上下文
```

**替换 3**：「## 硬约束」段里，把这一行
```
- ❌ 禁止不读 process.txt 就直接推进（会漏掉关键上下文）
```
保留不变。

把这一行
```
- ❌ 禁止把 4 个文件全部粘到主对话（会污染上下文）
```
改为：
```
- ❌ 禁止把 3 个文件全部粘到主对话（会污染上下文）
```

- [ ] **Step 3: 删除旧的 log_layout / process.tool.log 相关描述**

在同一文件，确保不再出现以下任一串：`log_layout`、`process.tool.log`、`split`、`legacy`、`tail process.tool.log`。

Run:
```bash
grep -cE 'log_layout|process\.tool\.log|legacy' .claude/skills/requirement-session-restorer/SKILL.md || echo "0 matches (expected)"
```

如非 `0 matches (expected)`，用 Edit 工具继续清理。

- [ ] **Step 4: 验证新增 ADR 摘要逻辑写入**

Run:
```bash
grep -c '决策记录\|D-NNN' .claude/skills/requirement-session-restorer/SKILL.md
```

Expected: `>= 1`

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/requirement-session-restorer/SKILL.md
git commit -m "refactor(skill): session-restorer 简化读取流程并带上最近 ADR

- 删 process.tool.log 可选读取、log_layout 判断、SESSION_END 过滤
- 新增扫 plan.md 决策记录段，把最近一条 ADR 标题写入恢复摘要
- 非白名单 tag 直接忽略，兼容老需求的旧事件"
```

---

## Task 7: 改 managing-requirement-lifecycle SKILL 参考清单

**Files:**
- Modify: `.claude/skills/managing-requirement-lifecycle/SKILL.md`

- [ ] **Step 1: 读取当前 SKILL.md**

Run:
```bash
cat .claude/skills/managing-requirement-lifecycle/SKILL.md
```

- [ ] **Step 2: 在「## 参考资源」段末尾追加 blocker-conventions.md 条目**

在 `.claude/skills/managing-requirement-lifecycle/SKILL.md` 的「## 参考资源」bullet 列表的 `templates/pr-body.md.tmpl` 条目之后，追加一条：

```
- [`reference/blocker-conventions.md`](reference/blocker-conventions.md) — 主 Agent 识别与记录 blocker / blocker-resolved 事件的行为约定
```

- [ ] **Step 3: 验证**

Run:
```bash
grep -c 'blocker-conventions.md' .claude/skills/managing-requirement-lifecycle/SKILL.md
```

Expected: `>= 1`

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/managing-requirement-lifecycle/SKILL.md
git commit -m "docs(skill): 参考资源清单加 blocker-conventions.md"
```

---

## Task 8: 改 /note 命令文档补 blocker 说明

**Files:**
- Modify: `.claude/commands/note.md`

- [ ] **Step 1: 读取当前文件**

Run:
```bash
cat .claude/commands/note.md
```

- [ ] **Step 2: 用 Edit 工具在「## 用途」段末追加一段**

在 `.claude/commands/note.md` 的「## 用途」段落最后一行（当前是 "开发过程中随手记录发现、坑、想法。..."）之后，追加一段：

```markdown

**不要用 /note 记 blocker**：阻塞是当前需求的时间线状态，应由主 Agent 委托 `requirement-progress-logger` 写入 `process.txt` 的 `[blocker]` 事件，不走 notes.md。详见 `../skills/managing-requirement-lifecycle/reference/blocker-conventions.md`。
```

- [ ] **Step 3: 验证**

Run:
```bash
grep -c '不要用 /note 记 blocker\|blocker-conventions' .claude/commands/note.md
```

Expected: `>= 1`

- [ ] **Step 4: Commit**

```bash
git add .claude/commands/note.md
git commit -m "docs(command): /note 命令文档声明 blocker 不走本命令

主 Agent 识别 blocker 后应走 requirement-progress-logger → process.txt，
避免阻塞状态与可复用经验混写在 notes.md。"
```

---

## Task 9: 删除 auto-progress-log.sh Hook

**Files:**
- Delete: `.claude/hooks/auto-progress-log.sh`

- [ ] **Step 1: 确认文件存在且内容是预期的 Hook**

Run:
```bash
head -5 .claude/hooks/auto-progress-log.sh
```

Expected: `#!/usr/bin/env bash` 开头 + `PostToolUse hook: 追加工具级进度日志` 注释。

- [ ] **Step 2: 删除文件**

Run:
```bash
git rm .claude/hooks/auto-progress-log.sh
```

- [ ] **Step 3: 验证**

Run:
```bash
test ! -f .claude/hooks/auto-progress-log.sh && echo "deleted"
```

Expected: `deleted`

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(hook): 删除 auto-progress-log.sh

下游项目反馈该 Hook 每次 Edit/Write/Bash 都写一行，
process.txt 噪音淹没语义事件。溢出区重定义后 process.txt
由 requirement-progress-logger Skill 单通道写入。"
```

---

## Task 10: 删除 stop-session-save.sh Hook

**Files:**
- Delete: `.claude/hooks/stop-session-save.sh`

- [ ] **Step 1: 确认文件存在**

Run:
```bash
head -3 .claude/hooks/stop-session-save.sh
```

Expected: `#!/usr/bin/env bash` 开头 + `Stop hook: 会话结束时打 SESSION_END 标记` 注释。

- [ ] **Step 2: 删除文件**

Run:
```bash
git rm .claude/hooks/stop-session-save.sh
```

- [ ] **Step 3: 验证**

Run:
```bash
test ! -f .claude/hooks/stop-session-save.sh && echo "deleted"
```

Expected: `deleted`

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(hook): 删除 stop-session-save.sh

SESSION_END 标记对「做到哪了」零信息量；session-restorer
tail 最后一条真事件就能推断断点，不需要会话边界标记。"
```

---

## Task 11: 改 settings.json 移除两个 Hook 注册

**Files:**
- Modify: `.claude/settings.json:26-44`

- [ ] **Step 1: 读取确认当前 hooks 段有 3 个注册**

Run:
```bash
grep -c 'hooks/' .claude/settings.json
```

Expected: `3`（protect-branch + auto-progress-log + stop-session-save）

- [ ] **Step 2: 用 Edit 工具替换整个 hooks 段**

把 `.claude/settings.json` 中从第 26 行到第 44 行的 `"hooks": { ... }` 整段替换为：

```json
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write",
        "hooks": [{"type": "command", "command": ".claude/hooks/protect-branch.sh"}]
      }
    ]
  }
```

注意：删除后只剩 `PreToolUse` 一个事件组，且最后这对 `}` 前**不要留逗号**（原本 `PreToolUse` 数组后有逗号是因为后面还有 `PostToolUse`/`Stop`）。

- [ ] **Step 3: 验证 JSON 合法性**

Run:
```bash
python3 -m json.tool .claude/settings.json > /dev/null && echo "valid JSON"
```

Expected: `valid JSON`

Run:
```bash
grep -c 'hooks/' .claude/settings.json
```

Expected: `1`（只剩 protect-branch）

Run:
```bash
grep -E 'auto-progress-log|stop-session-save' .claude/settings.json || echo "not found (expected)"
```

Expected: `not found (expected)`

- [ ] **Step 4: Commit**

```bash
git add .claude/settings.json
git commit -m "chore(settings): 移除 auto-progress-log / stop-session-save 的 hook 注册

两个 Hook 文件已在前两个 commit 删除，本 commit 同步 settings.json 注册项。
保留 protect-branch 的 PreToolUse 注册不变。"
```

---

## Task 12: 同步主 spec 文档 §6 / §7.1

**Files:**
- Modify: `context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md:422-521`

- [ ] **Step 1: 读取 §6 + §7.1 现状**

Run:
```bash
sed -n '422,521p' context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md
```

- [ ] **Step 2: 用 Edit 工具替换 §6.1 三层记忆结构图下的"四个文件"措辞**

把
```
溢出区（Spillover）· requirements/<id>/ 下的四个文件
```
改成
```
溢出区（Spillover）· requirements/<id>/ 下的三个文件 + 一份元数据（meta.yaml）
```

- [ ] **Step 3: 替换 §6.2 整段**

把当前 `### 6.2 四个溢出文件 + 工具日志（v2 分层）` 标题连同下面的表格、"布局切换" 段**整段**替换为：

````markdown
### 6.2 三个溢出文件 + 元数据

| 文件 | 写入频率 | 写入方式 | 谁写 | 谁读 | 入 git |
|---|---|---|---|---|---|
| `meta.yaml` | 低（阶段切换） | 覆盖 | `managing-requirement-lifecycle` | 全体 | ✅ |
| `process.txt` | 中（每个语义事件） | **追加** | `requirement-progress-logger` Skill（唯一通道） | `requirement-session-restorer` | ✅ |
| `notes.md` | 中 | 追加 | `/note` + 主 Agent 自主 | `/knowledge:*` 提炼时 | ✅ |
| `plan.md` | 中 | 上半覆盖 / 下半 ADR 段追加 | 主 Agent 在对齐阶段 + 决策发生时 | 主 Agent 回看 + session-restorer | ✅ |

**三文件 slogan**：

- `process.txt` — 做到哪了 + 遇到了什么阻塞
- `notes.md` — 过程中发现的经验 + 待沉淀的知识
- `plan.md` — 当前计划 + 决策记录（ADR 小卡）

工具调用不再记录到任何溢出文件；变更详情请用 `git log` 回看。
````

- [ ] **Step 4: 替换 §6.3 整段**

把 `### 6.3 \`process.txt\` / \`process.tool.log\` 格式` 整段替换为：

````markdown
### 6.3 `process.txt` 格式

```
2026-04-24 10:20:10 [definition] [blocker] DB 主键冲突，怀疑唯一索引重复
2026-04-24 10:35:40 [definition] [blocker] 验证：XX 表索引正常，方向转向数据层
2026-04-24 11:45:00 [definition] [blocker-resolved] batchInsert 没去重，已补 distinct
2026-04-24 12:02:08 [definition] [review:needs_revision] requirement-quality-reviewer 3 条 major
2026-04-24 12:16:00 [definition] [phase-transition] definition → tech-research
```

**事件标签白名单**：`[phase-transition]` / `[save]` / `[review:*]` / `[gate:*]` / `[blocker]` / `[blocker-resolved]`。完整定义与调用路径见 `.claude/skills/requirement-progress-logger/SKILL.md`。

**时间戳规范**：Skill 写入时必须取"写入当下"的 Asia/Shanghai now（`TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M:%S"`），不得预先计算。统一格式与时区约定见 `context/team/engineering-spec/time-format.md`。历史 UTC ISO 8601 与旧格式（`[decision]` / `[issue]` / `[SESSION_END]` / `tool=*`）保留兼容读取（session-restorer 直接忽略）。
````

- [ ] **Step 5: 替换 §6.4 跨会话恢复流程**

把 `### 6.4 跨会话恢复流程` 整段替换为：

````markdown
### 6.4 跨会话恢复流程

```
/requirement:continue
  → managing-requirement-lifecycle 识别意图
  → requirement-session-restorer Skill
     ├── 读 meta.yaml                → 阶段
     ├── 读 process.txt 末 50 行      → 白名单事件（非白名单 tag 直接忽略）
     ├── 读 notes.md                 → 踩坑 / 待澄清
     └── 读 plan.md                  → 当前计划 + 决策记录（取最近一条 ADR 入摘要）
  → 主 Agent 输出"恢复摘要"（< 200 字）
  → 等用户确认后继续
```
````

- [ ] **Step 6: 替换 §6.6 .gitignore 策略段的注释**

把 §6.6 里的 .gitignore 代码块（第 499-509 行左右）整段替换为：

````markdown
### 6.6 `.gitignore` 策略

```gitignore
# 个人覆盖
.claude/settings.local.json

# 运行态临时文件
.review-scope.json
.DS_Store
```

`requirements/` 与 `context/` 都必须入 git（团队资产）。不再有工具日志 `.gitignore` 例外——工具调用在溢出区不留痕，回看请用 `git log`。
````

- [ ] **Step 7: 替换 §7.1 Hook 清单**

把 `### 7.1 Hook 清单（3 个）` 整段替换为：

````markdown
### 7.1 Hook 清单（1 个）

| Hook | 触发 | 目的 |
|---|---|---|
| `protect-branch.sh` | `PreToolUse`（Bash/Edit/Write） | master/main/develop 上写操作时阻止 |

> 历史上曾有 `auto-progress-log.sh`（PostToolUse）与 `stop-session-save.sh`（Stop）两个 Hook，在溢出区重定义后移除（见 `specs/2026-04-24-spillover-redefine-design.md`）。
````

- [ ] **Step 8: 验证主 spec 文档清理干净**

Run:
```bash
grep -cE 'process\.tool\.log|log_layout|四个溢出文件|SESSION_END' context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md || echo "0 matches (expected)"
```

Expected: `0 matches (expected)`。若非 0 需继续清理。

Run:
```bash
grep -c 'blocker-resolved\|决策记录\|ADR' context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md
```

Expected: `>= 2`

- [ ] **Step 9: Commit**

```bash
git add context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md
git commit -m "docs(spec): 主 spec §6 / §7.1 同步溢出区重定义

- §6.1 结构图：四个文件 → 三个文件 + 元数据
- §6.2 重写为三溢出文件表 + 三文件 slogan
- §6.3 process.txt 格式 + 事件标签白名单
- §6.4 恢复流程去 process.tool.log，加取最近 ADR 入摘要
- §6.6 .gitignore 移除工具日志例外说明
- §7.1 Hook 清单从 3 个减到 1 个"
```

---

## Task 13: 最终集成验证

**Files:** (read-only 验证)

- [ ] **Step 1: 事件标签白名单一致性检查**

Run:
```bash
grep -hoE '\[(phase-transition|save|review:[a-z_]+|gate:[a-z]+|blocker|blocker-resolved)\]' \
  context/team/engineering-spec/specs/2026-04-24-spillover-redefine-design.md \
  context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md \
  .claude/skills/requirement-progress-logger/SKILL.md \
  .claude/skills/requirement-session-restorer/SKILL.md \
  .claude/skills/managing-requirement-lifecycle/reference/blocker-conventions.md 2>/dev/null \
  | sort -u
```

Expected 输出至少包含（可有其他 review/gate 变体）：
```
[blocker-resolved]
[blocker]
[gate:pass]
[phase-transition]
[review:approved]
[save]
```

- [ ] **Step 2: Hook 真的已删**

Run:
```bash
test ! -f .claude/hooks/auto-progress-log.sh && echo "ok1"
test ! -f .claude/hooks/stop-session-save.sh && echo "ok2"
test -f .claude/hooks/protect-branch.sh && echo "ok3"
```

Expected: `ok1` / `ok2` / `ok3` 三行都出现。

- [ ] **Step 3: settings.json 合法且只剩 protect-branch 注册**

Run:
```bash
python3 -m json.tool .claude/settings.json > /dev/null && echo "json ok"
grep -c 'hooks/' .claude/settings.json
```

Expected: `json ok` + `1`。

- [ ] **Step 4: 无残留的 process.tool.log / log_layout / v1/v2 分层措辞**

Run:
```bash
grep -rlE 'process\.tool\.log|log_layout' \
  .claude/skills/ \
  .claude/commands/ \
  .claude/hooks/ \
  .gitignore \
  context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md \
  2>/dev/null || echo "no residue (expected)"
```

Expected: `no residue (expected)`。

（注：本次新 spec `specs/2026-04-24-spillover-redefine-design.md` 里会提及 `process.tool.log` 作为**被删除的历史**，是合法引用，不算残留。上面 grep 的范围不包含它。）

- [ ] **Step 5: 模板变更生效**

Run:
```bash
grep -c 'log_layout' .claude/skills/managing-requirement-lifecycle/templates/meta.yaml.tmpl || echo "0 (expected)"
grep -c '## 决策记录' .claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl
```

Expected: `0 (expected)` + `1`。

- [ ] **Step 6: git log 审阅 commit 序列**

Run:
```bash
git log --oneline feature/spillover-redefine ^develop
```

Expected: 12 条 commit（Task 1–12），全部 message 清晰、无 "wip" / "fix typo" 等噪音。若有可 `git rebase -i` 合并修整——但**仅在有明确噪音时才合**，一般情况下保持 12 条不动。

- [ ] **Step 7: 所有 Task 验证均通过后，通知用户 PR 就绪**

给用户的消息模板：

> Plan 执行完毕。共 12 个 commit 在 `feature/spillover-redefine` 分支上。关键改动：
>
> - `.claude/skills/` 下 3 个 Skill + 1 个新 reference 文档更新
> - 2 个 Hook 删除 + settings.json 注册清理
> - 2 个模板更新（meta.yaml 去字段 / plan.md 加 ADR 段）
> - 主 spec `§6` / `§7.1` 同步
> - `.gitignore` 清理 process.tool.log 条目
>
> 需要冒烟测试（用 `/requirement:new` 建临时需求跑一遍）再 push PR 吗？还是你先 review 本地 diff？

---

## 自检清单（writing-plans 流程强制）

**Spec coverage（与 spec §6 对照）**：
- [x] §6.1 Skill 改动 4 个 → Task 5/6/7/8 覆盖
- [x] §6.2 模板改动 2 个 → Task 2/3 覆盖
- [x] §6.3 Hook 删除 2 个 + settings → Task 9/10/11 覆盖
- [x] §6.4 .gitignore 清理 → Task 1 覆盖
- [x] §6.5 spec 主文档同步 6 处小节 → Task 12 覆盖
- [x] §5 blocker 行为约定参考文档 → Task 4 覆盖
- [x] §9 验证方式（规范一致性 + Hook 已删 + 冒烟） → Task 13 覆盖（冒烟显式跳过，已在 Out of Scope 声明）

**Placeholder 扫描**：无 TBD / TODO / "to be filled"。每个 Edit 步骤都给出替换文本，每个 Run 步骤都给出 Expected 输出。

**Type / 名称一致性**：
- 所有 Skill 路径都用 `.claude/skills/<name>/SKILL.md` 形式
- 所有 Hook 路径用 `.claude/hooks/<name>.sh`
- 事件标签大小写与连字符全程一致（`[blocker-resolved]` 非 `[blockerResolved]`）
- ADR 字段名 Context / Decision / Consequences / 时间 / Supersedes 三个文件完全对齐（spec / 模板 / blocker-conventions 里都用同一组）
