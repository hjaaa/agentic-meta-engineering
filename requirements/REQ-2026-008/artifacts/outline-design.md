---
id: REQ-2026-008
title: 派发链强制结构化升级 · 概要设计
created_at: 2026-05-06T09:10:00+08:00
phase: outline-design
refs-requirement: true
refs-tech-feasibility: true
---

# REQ-2026-008 · 概要设计

## 文档定位

requirement.md 已审定 5 场景 / 9 验收 / 6 决策（来源：requirements/REQ-2026-008/artifacts/requirement.md:30）；tech-feasibility.md 已给出 9 评估单元 / 8 features / 风险矩阵 / 工作量（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:9）。本文档不重新论证方案，做三件事：

1. **把 9 评估单元翻译成 4 层模块视图与时序**——为 detail-design 写接口签名做准备
2. **把 8 features 落到 4 层的具体节点 + 依赖 DAG**——为任务规划阶段拆 features.json 做准备
3. **复盘可能影响模块切分的 trade-off（T-01 ~ T-04）**——T-01 留 detail-design 收口，T-02/T-03/T-04 仅复盘不翻案

---

## 1. 总体架构

### 1.1 4 层模块视图

```
┌──────────────────────────────────────────────────────────────────────┐
│ L1 Hooks 层 (.claude/hooks/)                                         │
│   pre-tool-use-guard.sh                                               │
│     ├─[NEW Task case]──→ dispatch_precheck.py     (PreToolUse Task)   │
│     └─[Edit/Write/MultiEdit case +tail]                              │
│                  └─→ touches_guard.py             (PreToolUse 写工具) │
│   settings.json:29 PreToolUse matcher 加 |Task                       │
└──────────────────────────────────────────────────────────────────────┘
                                │ 解析 prompt / 读 schema / 写 receipt
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ L2 Skills + engineering-spec 层                                      │
│   .claude/skills/feature-lifecycle-manager/                           │
│     SKILL.md                ──[+ hook/gate 拦截标注]                  │
│     reference/subagent-dispatch.md ──[+派发模板首部 feature_id 行]    │
│     templates/feature-task.md.tmpl ──[+frontmatter touches 字段]      │
│   .claude/skills/managing-requirement-lifecycle/                      │
│     SKILL.md                ──[+ 4 个新 gate 说明]                    │
│     reference/gate-checklist.md ──[render-docs.py 重生成]             │
│   context/team/engineering-spec/                                      │
│     receipt-schema.yaml         ──[NEW]                               │
│     features-schema.yaml        ──[NEW]                               │
│     task-frontmatter-schema.yaml──[NEW]                               │
│     meta-schema.yaml            ──[+ legacy 字段说明 1 行]            │
└──────────────────────────────────────────────────────────────────────┘
                                │ check / 注册 / 调度
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ L3 Gates + scripts/lib 层                                            │
│   scripts/gates/                                                      │
│     registry.yaml ──[NEW 4 gate：POST-DEV-RECEIPT / TOUCHES-VIOLATION │
│                      / FEATURES-SCHEMA / TASK-FRONTMATTER]           │
│     plugins/post_dev_receipt.py     ──[NEW]                           │
│     plugins/touches_violation.py    ──[NEW]                           │
│     plugins/features_schema.py      ──[NEW]                           │
│     plugins/task_frontmatter.py     ──[NEW]                           │
│   scripts/lib/                                                        │
│     check_receipt.py            ──[NEW] 参照 check_meta.py            │
│     check_features.py           ──[NEW]                               │
│     check_task_frontmatter.py   ──[NEW]                               │
│     dispatch_state.py           ──[NEW] flock 锁工具单一入口          │
└──────────────────────────────────────────────────────────────────────┘
                                │ 读写
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ L4 Artifacts 结构层 (requirements/<id>/)                             │
│   artifacts/tasks/<feature_id>.md         ──[+frontmatter touches]    │
│   artifacts/tasks/<feature_id>.receipt.json ──[NEW] subagent 写       │
│   artifacts/features.json                  ──[受 schema 约束]         │
│   .dispatch-state.json                     ──[NEW] hook 锁文件        │
└──────────────────────────────────────────────────────────────────────┘
```

四层之间是**单向依赖**（Hooks → Skills+Spec → Gates+Lib → Artifacts），无反向引用；Hooks 只读 schema/写 artifact，不调 gate；Gates 只读 artifact，不调 hook。

### 1.2 改动一览表

| # | 路径 | 类型 | 来源 |
|---|---|---|---|
| 1  | `context/team/engineering-spec/receipt-schema.yaml` | 新增 | requirement.md:131 |
| 2  | `context/team/engineering-spec/features-schema.yaml` | 新增 | requirement.md:131 |
| 3  | `context/team/engineering-spec/task-frontmatter-schema.yaml` | 新增 | requirement.md:131 |
| 4  | `scripts/lib/check_receipt.py` | 新增 | requirement.md:132 |
| 5  | `scripts/lib/check_features.py` | 新增 | requirement.md:132 |
| 6  | `scripts/lib/check_task_frontmatter.py` | 新增 | requirement.md:132 |
| 7  | `scripts/lib/dispatch_state.py` | 新增 | tech-feasibility.md:683 |
| 8  | `.claude/hooks/dispatch_precheck.py` | 新增 | requirement.md:134 |
| 9  | `.claude/hooks/touches_guard.py` | 新增 | requirement.md:134 |
| 10 | `.claude/hooks/pre-tool-use-guard.sh` | 修改（+Task case +touches 调度） | requirement.md:140 |
| 11 | `.claude/settings.json` | 修改（matcher +Task） | requirement.md:138 |
| 12 | `scripts/gates/plugins/post_dev_receipt.py` | 新增 | requirement.md:136 |
| 13 | `scripts/gates/plugins/touches_violation.py` | 新增 | requirement.md:136 |
| 14 | `scripts/gates/plugins/features_schema.py` | 新增 | requirement.md:136 |
| 15 | `scripts/gates/plugins/task_frontmatter.py` | 新增 | requirement.md:136 |
| 16 | `scripts/gates/registry.yaml` | 修改（+4 gate 注册） | requirement.md:137 |
| 17 | `.claude/skills/feature-lifecycle-manager/SKILL.md` | 修改（+ hook/gate 拦截标注） | requirement.md:142 |
| 18 | `.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md` | 修改（派发模板首部 + 红线段精简） | requirement.md:142 |
| 19 | `.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl` | 修改（+frontmatter touches） | notes.md:20 |
| 20 | `.claude/skills/managing-requirement-lifecycle/SKILL.md` | 修改（+4 gate 说明） | requirement.md:143 |
| 21 | `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md` | 重生成 | tech-feasibility.md:625 |
| 22 | `context/team/engineering-spec/meta-schema.yaml` | 修改（+legacy 字段说明 1 行） | plan.md:88 |
| 23 | `.github/workflows/quality-check.yml` | 修改（pytest 覆盖扩展） | tech-feasibility.md:545 |
| 24 | `requirements/REQ-2026-008/artifacts/requirement.md` | 修改（V-07 措辞已修订 D-006） | plan.md:97 |
| 25 | `tests/hooks/test_dispatch_precheck.bats` 等 | 新增（V-01~V-08 用例） | requirement.md:146 |

合计：14 新增 + 11 修改 = **25 个文件**（不含 `tests/` 多文件展开）。

### 1.3 8 features 依赖 DAG

```
            ┌────────────────────────────────────────┐
            │ schema 层（可三路并行）                │
            │  F-001 receipt-schema + check_receipt  │
            │  F-002 features-schema + check_features│
            │  F-003 task-frontmatter + check_task   │
            └────────────┬───────────┬───────────────┘
                         │           │
            ┌────────────▼───┐    ┌──▼─────────────────┐
            │ F-004          │    │ F-006              │
            │ dispatch_      │    │ CI quality-check   │
            │ precheck +     │    │ pytest 覆盖扩展    │
            │ POST-DEV-      │    │ （独立，可最早合）  │
            │ RECEIPT +      │    └────────────────────┘
            │ dispatch_state │
            └────────┬───────┘
                     │
              ┌──────▼──────────────┐
              │ F-005 touches_guard │
              │  + TOUCHES-VIOLATION│
              │  （依赖 F-004 锁&  │
              │   .dispatch-state） │
              └──────┬──────────────┘
                     │
            ┌────────▼─────────────┐
            │ F-007 派发模板 + Skill│
            │ 文档收口（V-09）      │
            │ （依赖 F-001~F-005    │
            │  全部落地后定稿）     │
            └────────┬─────────────┘
                     │
            ┌────────▼─────────────┐
            │ F-008 沙盒 e2e        │
            │ + 自举回归            │
            │ （依赖前 7 项全 ready）│
            └──────────────────────┘
```

关键串行链：**F-001 → F-004 → F-005 → F-007 → F-008**；F-002/F-003 与 F-001 并行；F-006 完全独立可最早合（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:769）。

> **备注**：F-006 不被 F-001/F-002/F-003 阻塞——它只是把现有 `tests/lib/` `tests/integration/` `tests/lifecycle/` 纳入 CI；F-001~F-005 的新测试落地是**之后**的事，但 F-006 的 yml 改动可作为 PR 第一个 commit 让 CI 提前感知。

---

## 2. 关键时序

### 2.1 派发前置校验（dispatch_precheck）

主 Agent 调 `Task` tool 派 subagent；PreToolUse hook 拦截做三重校验。

```
主 Agent                .claude/hooks/                scripts/lib/                Artifacts
  │                     pre-tool-use-guard.sh         dispatch_state.py           features.json
  │                          │                              │                       .dispatch-state.json
  │ Task(prompt:             │                              │                       tasks/F-002.md
  │   "feature_id: F-002     │                              │                       tasks/F-001.receipt.json
  │    ...实施 F-002")       │                              │                       │
  ├─────────────────────────►│                              │                       │
  │                          │ tool_name=="Task"?           │                       │
  │                          │ ├─ Yes → 调 dispatch_precheck.py                     │
  │                          │ │   ├─ 解析首行 feature_id: F-\d{3}                   │
  │                          │ │   │   （fail-open：解析失败 exit 0）               │
  │                          │ │   ├─ flock(.dispatch-state.json) ◄────────────────►│
  │                          │ │   ├─ 读 features.json：F-002.status?               │
  │                          │ │   ├─ 校验 1：status ∈ {pending,blocked}            │
  │                          │ │   ├─ 校验 2：depends_on 全部 done                  │
  │                          │ │   ├─ 校验 3：当前在 in-progress 的 feature 数==0  │
  │                          │ │   │   （保守档串行）                              │
  │                          │ │   ├─ 通过 → 写 .dispatch-state.json                │
  │                          │ │   │           current=F-002 / started_at=ts       │
  │                          │ │   │           pid=$$                              │
  │                          │ │   └─ exit 0                                       │
  │                          │ └─ Edit/Write/MultiEdit → touches_guard（见 §2.3）   │
  │ ◄─Task 实际执行─────────┤                              │                       │
  │ subagent 完成 Write       │                              │                       │
  │   tasks/F-002.receipt.json│                              │                       │
  │                          │                              │                       │
```

校验失败时：`exit 2 + stderr` 输出明确错误（场景 1 / 6 的 V-01 / V-06，来源：requirements/REQ-2026-008/artifacts/requirement.md:114）。

### 2.2 完成回执 + post-dev gate 兜底

subagent 写 `receipt.json` → 主 Agent 切阶段 → `GATE-POST-DEV-RECEIPT` 兜底扫描。

```
subagent                 主 Agent                     scripts/gates/             Artifacts
  │                       │                            run.py                    features.json
  │ Write tasks/          │                                                       tasks/F-002.receipt.json
  │ F-002.receipt.json    │                                                       │
  │ {status:"DONE",       │                                                       │
  │  commit_sha:...,      │                                                       │
  │  files_changed:[...], │                                                       │
  │  test_summary:...,    │                                                       │
  │  touches_violations:[]│                                                       │
  │  schema_version:"1.0"}│                                                       │
  ├──────────────────────►│                                                       │
  │ "RECEIPT_WRITTEN: ..."│                                                       │
  │                       │ bash scripts/lib/check_receipt.py <path>              │
  │                       │   ├─ schema 校验 → exit 0/1                            │
  │                       │   └─ jq -r '.status' → "DONE"                         │
  │                       │ 主 Agent 据 status 走分支：                            │
  │                       │   DONE/DONE_WITH_CONCERNS → 标 features.json done    │
  │                       │   NEEDS_CONTEXT/BLOCKED   → 三选一决策（人类介入）  │
  │                       │                            │                          │
  │                       │ /requirement:next（→ testing 等阶段切换）             │
  │                       │   trigger=phase-transition                             │
  │                       ├───────────────────────────►│                          │
  │                       │                            │ 7 既有 gate 顺序跑      │
  │                       │                            │   + GATE-POST-DEV-RECEIPT│
  │                       │                            │   ├─读 features.json    │
  │                       │                            │   ├─筛 status==done     │
  │                       │                            │   └─检查每个 feature_id │
  │                       │                            │     都有 receipt.json   │
  │                       │                            │     且 status ∈         │
  │                       │                            │     {DONE,DONE_WITH_*}  │
  │                       │                            │ exit 0/1                 │
```

兜底逻辑（D-004，来源：requirements/REQ-2026-008/plan.md:73）：即使主 Agent 跳过逐 feature 的 post-dev gate，phase-transition 时仍会扫描所有 done feature，缺 receipt 直接 fail（场景 4 / V-04）。

### 2.3 touches 越界双层拦截

subagent 改 `touches` 范围外文件 → 软拦截（开发期）+ 硬拦截（phase-transition）。

```
subagent (开发期)             pre-tool-use-guard.sh    touches_guard.py        receipt.json
  │                            │                         │                       │
  │ Edit src/billing/api.ts    │                         │                       │
  │ (任务 F-001 touches 是     │                         │                       │
  │  src/auth/*)               │                         │                       │
  ├───────────────────────────►│                         │                       │
  │                            │ tool ∈ {Edit,Write,     │                       │
  │                            │   MultiEdit}? → 调 hook │                       │
  │                            ├────────────────────────►│                       │
  │                            │                         │ 读 .dispatch-state    │
  │                            │                         │   .current=F-001      │
  │                            │                         │ 读 tasks/F-001.md     │
  │                            │                         │   frontmatter.touches │
  │                            │                         │ glob 匹配 file_path:  │
  │                            │                         │   src/billing/api.ts  │
  │                            │                         │   ∉ ["src/auth/*"]   │
  │                            │                         │ → 软拦截：           │
  │                            │                         │   append 到 receipt   │
  │                            │                         │   .touches_violations[]│
  │                            │                         │   exit 0（放行）      │
  │ ◄─Edit 继续执行────────────│                         │                       │
  │                            │                                                  │
  │ ... 完成阶段，主 Agent     │                                                  │
  │  /requirement:next →       │                                                  │
  │  GATE-TOUCHES-VIOLATION    │                                                  │
  │                            │ scripts/gates/plugins/touches_violation.py     │
  │                            │   ├─ scan all receipt.json                      │
  │                            │   ├─ 任一 .touches_violations[].length > 0      │
  │                            │   └─ exit 1 + 列违规清单                         │
  │                            │ 硬挡：人类介入决定豁免 / 修复                    │
```

设计动机（D-003，来源：requirements/REQ-2026-008/plan.md:67）：subagent 实际开发常需调整邻近文件，硬拦截误伤多导致 BLOCKED 重派转发成本高；双层既不静悄悄越界又给合理调整留路（场景 3 / V-03）。

---

## 3. 模块接口骨架

> 接口签名（参数 / 返回值 / 退出码语义）的精确定义留 detail-design。本节只画"最小契约"，让任务规划阶段能拆 features.json。

### 3.1 schema 三件套（F-001 / F-002 / F-003）

参照 `context/team/engineering-spec/meta-schema.yaml`（来源：context/team/engineering-spec/meta-schema.yaml:1）形态。每份 schema 必须含：

| 字段 | 含义 | 备注 |
|---|---|---|
| `schema_version: "1.0"` | 强制，演化时递增 | tech-feasibility.md:633 R3 |
| `required: [...]` | 必填字段清单 | YAML 形式 |
| `properties.<field>.type` | 类型约束（string/array/enum 等） | |
| `properties.<field>.enum` | 枚举值列表（如 status / complexity） | |
| `description` | 字段语义说明 | 必填，便于后续维护 |

**receipt-schema.yaml** 关键字段（D-002，来源：requirements/REQ-2026-008/plan.md:61）：
- `status`：枚举 `[DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED]`
- `commit_sha`：string，必填（DONE 类）
- `files_changed: [path...]`
- `test_summary: {passed, failed, skipped, output_excerpt}`
- `touches_violations: [{path, ts, tool}]`
- `concerns / missing_context / block_reason`：状态对应字段
- `timestamp`：ISO8601 (Asia/Shanghai)

**features-schema.yaml** 关键字段：
- `features[].id`：`F-\d{3}` 正则
- `features[].status`：枚举 `[pending, in-progress, done, blocked]`
- `features[].complexity`：枚举 `[trivial, light, medium, heavy]`（具体取值留 detail-design）
- `features[].depends_on: [feature_id...]`
- `features[].touches: [glob...]`

**task-frontmatter-schema.yaml** 关键字段：
- `feature_id` / `title` / `status` / `complexity` / `depends_on` / `touches` / `created_at` / `updated_at` / `review_report`
- 注意：现有模板 frontmatter 缺 `touches` 字段（来源：requirements/REQ-2026-008/notes.md:20），detail-design F-005 / F-007 必补；schema 把 `touches` 列为 required 后模板必须同步

**check 脚本三件套** 形态（参照 `scripts/lib/check_meta.py`，来源：scripts/lib/check_meta.py:1）：
```
python3 scripts/lib/check_<X>.py <path-or-glob> [--strict]
  exit 0  → 全部通过
  exit 1  → 至少一项 schema 违规（stderr 列字段）
  exit 2  → 内部错误（schema 自身有问题）
```

### 3.2 dispatch_precheck.py 接口（F-004）

```
.claude/hooks/dispatch_precheck.py
输入：stdin JSON（PreToolUse 协议）
   {"tool_name": "Task", "tool_input": {"prompt": "...", "subagent_type": "...", ...}}
输出：
   exit 0  → 放行（含 fail-open：解析失败也 0）
   exit 2  → 阻断（stderr 输出明确原因）
副作用：成功放行时 write .dispatch-state.json
   {"current": "F-002", "started_at": "...", "pid": <pid>}
```

依赖（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:670）：
- `scripts/lib/dispatch_state.py`（锁工具，§3.4）
- `requirements/<id>/artifacts/features.json`（读 status / depends_on）
- prompt 解析正则 `^feature_id:\s*(F-\d{3})\s*$`（双保险首部字段，D-005 #3）+ 5 行内 fallback `F-\d{3}` 兜底
- **fail-open 契约**：prompt 解析失败 / state.json 读失败 / 锁 timeout → 一律 exit 0（与 guard.sh ERR trap 哲学一致，tech-feasibility.md §5.4）

### 3.3 touches_guard.py 接口（F-005）

```
.claude/hooks/touches_guard.py
输入：stdin JSON（PreToolUse 协议）
   {"tool_name": "Edit"|"Write"|"MultiEdit", "tool_input": {"file_path": "...", ...}}
输出：
   exit 0  → 放行（始终；软拦截不阻断）
副作用：当 file_path 不在 .dispatch-state.current 的 touches glob 内时，
   append 到 tasks/<current>.receipt.json.touches_violations[]
```

注意（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:680）：
- **glob 语义留 detail-design**（§5 T-01 不涉及；但需在模板注释固化是否 pathspec gitignore 风格）
- **MultiEdit 多 file_path** 需逐个匹配
- **subagent 写 receipt 之前** 的 touches 违规先暂存到内存或 tmp 文件，receipt 创建时合并；具体策略留 detail-design

### 3.4 dispatch_state.py 锁工具（F-004 内嵌）

唯一对外暴露三函数（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:210）：
```
read_state(req_dir: Path) -> dict | None
write_state(req_dir: Path, state: dict) -> None
clear_state(req_dir: Path) -> None
```

约束：
- 所有函数内部 `fcntl.flock(LOCK_EX)`，timeout 5s（D-005 #4）
- timeout 触发时抛 `TimeoutError`；调用方（hook）按 fail-open 转 exit 0
- **禁止** hook / gate / 命令绕过此模块直接 `open(.dispatch-state.json)`

### 3.5 4 个新 gate plugin（F-002 / F-003 / F-004 / F-005）

参照 `scripts/gates/plugins/meta_schema.py`（来源：scripts/gates/plugins/meta_schema.py:1）形态。每个 plugin 实现：

```python
def run(ctx: GateContext) -> GateResult:
    # ctx.requirement_id / ctx.req_dir / ctx.changed_files / ctx.trigger
    # 返回 GateResult(status="pass"|"fail", messages=[...])
```

| Gate | 触发组（来源：requirement.md:131） | 主要逻辑 |
|---|---|---|
| GATE-POST-DEV-RECEIPT | phase-transition / submit | 扫 features.json done feature 都有 receipt.json + status ∈ {DONE,DONE_WITH_CONCERNS} |
| GATE-TOUCHES-VIOLATION | phase-transition / submit | 扫所有 receipt.json `.touches_violations` 长度 > 0 即 fail |
| GATE-FEATURES-SCHEMA | pre-commit / ci（仅 features.json 变更时） | 调 `check_features.py` |
| GATE-TASK-FRONTMATTER | pre-commit / ci（仅 tasks/*.md 变更时） | 调 `check_task_frontmatter.py` |

**applies_when 自然过滤**（V-07 D-006 修订，来源：requirements/REQ-2026-008/plan.md:97）：4 个新 gate 不加 `legacy-bypass` tag；historic completed 需求由 trigger / changed_files / target_phase 自然过滤。historic ci trigger 不会命中 phase-transition / submit 限定的 2 个 gate；historic features.json / tasks/*.md 不变更则 schema 类 gate 也不命中。

### 3.6 settings.json + guard.sh 改动骨架（F-004 / F-005）

`.claude/settings.json:29` PreToolUse matcher（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:548）：
```diff
- "matcher": "Bash|Edit|Write|MultiEdit"
+ "matcher": "Bash|Edit|Write|MultiEdit|Task"
```

`.claude/hooks/pre-tool-use-guard.sh` 增加分支：
```sh
case "$TOOL_NAME" in
  Task)
    exec python3 .claude/hooks/dispatch_precheck.py
    ;;
  Edit|Write|MultiEdit)
    # ... 既有 protect-branch 校验
    python3 .claude/hooks/touches_guard.py || true   # 软拦截恒 exit 0
    ;;
esac
```

> Task 分支直接 `exec`（exit code 透传 dispatch_precheck）；Edit/Write/MultiEdit 分支 touches_guard 软拦截 `|| true` 防止 hook 内任何异常误伤。具体 case 位置 / ERR trap 互动留 detail-design（tech-feasibility §5.1）。

### 3.7 文档收口三处（F-007）

| 文件 | 改动要点 | 来源 |
|---|---|---|
| `feature-lifecycle-manager/SKILL.md` | "硬约束"段把"由 hook/gate 拦截"标注落地（取代"由 SKILL 文档约束"措辞） | requirement.md:142 |
| `feature-lifecycle-manager/reference/subagent-dispatch.md` | 派发模板首部加 `feature_id: F-xxx` 显式行（D-005 #3）；红线段精简为引导用户看 stderr | requirement.md:142 |
| `feature-lifecycle-manager/templates/feature-task.md.tmpl` | frontmatter 加 `touches: __TOUCHES__` 字段 | notes.md:20 |
| `managing-requirement-lifecycle/SKILL.md` | 加新 4 个 gate 说明（描述 + 触发组） | requirement.md:143 |
| `managing-requirement-lifecycle/reference/gate-checklist.md` | 由 `scripts/gates/migration/render-docs.py` 重生成 | tech-feasibility.md:625 |
| `engineering-spec/meta-schema.yaml` | `legacy` 字段说明补一行"不豁免本次新增的 4 个派发链 gate" | plan.md:88 |

---

## 4. trade-off 复盘

### 4.1 T-01 F-002 / F-003 是否合并为单一 `check_schema.py` 多 schema 注册

**Context**：F-002（features-schema）/ F-003（task-frontmatter-schema）形态高度相似——都是 YAML schema + check 脚本 + gate plugin。可以合并为单一 `scripts/lib/check_schema.py` 接受 `--schema features` / `--schema task-frontmatter` 多注册。

| 维度 | A. 合并（多 schema 注册） | B. 不合并（独立脚本） |
|---|---|---|
| 表达力 | 中——一处 lookup；schema 演化要改 dispatch 表 | 高——脚本名即语义 |
| 实现成本 | 中——多 50 行 dispatch + 抽象化 | 低——直接复制 check_meta.py 改名 |
| 单测成本 | 中——多 schema 共用 fixture 容易混淆 | 低——单测独立 |
| 后续扩展 | 高——再来 1 个 schema 几乎零成本 | 中——再写一份 |
| 修改隔离 | 低——改 features schema 风险面波及 task-frontmatter | 高——纯解耦 |

**推荐 B（不合并）**：
- 现仅 2 个 schema，抽象化的 ROI 不显著（YAGNI）
- check_meta.py 已是单 schema 单脚本的范本（来源：scripts/lib/check_meta.py:1），保持一致风格
- 单测/演化/修改隔离均略优；轻微重复（<200 行）可接受
- 若后续新增 schema 数 ≥ 4，再考虑抽象化（开放，不锁死）

**A 案保留为兜底**：detail-design 阶段若发现 3 个脚本初步实现重复 > 60%，再升级 A 案。

**决议时机**：detail-design 阶段首日，仅在 B 案三脚本骨架出现 > 60% 重复时复评。

### 4.2 T-02 / T-03 / T-04 一行回顾（已决议不翻案）

| # | trade-off | 决议 | 出处 |
|---|---|---|---|
| T-02 | receipt 是单文件 `receipt.json` 还是 `receipt + log.txt` 拆分 | **单文件**；schema 内嵌 test_summary.output_excerpt 已可承载关键日志 | D-002，requirements/REQ-2026-008/plan.md:61 |
| T-03 | touches 双层（软+硬） vs 单层硬拦截 | **双层**；硬拦截误伤多导致 BLOCKED 重派转发成本高 | D-003，requirements/REQ-2026-008/plan.md:67 |
| T-04 | `fcntl.flock` timeout 5s vs 自适应 | **5s 固定**；rollback + 完成清理低频，5s 足够；自适应额外复杂度无收益 | D-005 #4，requirements/REQ-2026-008/plan.md:79 |

---

## 5. 验收对齐（V-01 ~ V-09）

| V- | 验收点 | 本概要承担节点 |
|---|---|---|
| V-01 | 沙盒 e2e：派 F-002 但 F-001 未 done → exit 2 | §2.1 时序 + §3.2 dispatch_precheck 三重校验 |
| V-02 | 沙盒 e2e：缺 commit_sha 的 receipt → check_receipt exit 1 | §3.1 receipt-schema + §3.5 GATE-POST-DEV-RECEIPT |
| V-03 | 沙盒 e2e：subagent 写 touches 范围外文件 → 软拦截 + 硬挡 | §2.3 时序 + §3.3 touches_guard + §3.5 GATE-TOUCHES-VIOLATION |
| V-04 | 沙盒 e2e：feature done 但缺 receipt → GATE-POST-DEV-RECEIPT exit 1 | §2.2 时序 + §3.5 |
| V-05 | 沙盒 e2e：features.json `complexity: "giant"` / task.md `status: invalid_value` → schema gate exit 1 | §3.5（GATE-FEATURES-SCHEMA / GATE-TASK-FRONTMATTER）+ §3.1 schema |
| V-06 | 沙盒 e2e：F-001 in-progress 时派 F-003 → exit 2 保守档串行 | §3.2 校验 3（in-progress 数 == 0） |
| V-07 | 回归：历史 completed REQ ci 通道不命中新 gate | §3.5 applies_when 自然过滤段 |
| V-08 | 自举：本需求自身 development → testing 切换通过 | §3.5 + §1.2 改动一览（含本需求自身的 features.json） |
| V-09 | 文档一致性：4 处文档收口完成；gate-checklist.md 重生成 | §3.7 |

---

## 6. 进入 detail-design 的待办

> 接 tech-feasibility §5 的 8 条 + 本概要新增项（去重合并）。

| # | 待办项 | 出处 | 必须在 detail-design 决议 |
|---|---|---|---|
|  1 | settings.json + guard.sh 精确 patch（matcher 改法 + Task case 位置 + touches 调度位置） | tech-feasibility §5.1 / 本概要 §3.6 | ✅ |
|  2 | dispatch_precheck.py 的 stdin JSON 字段名实采样确认（`tool_input.prompt`） | tech-feasibility §5.1 待澄清#1 | ✅ |
|  3 | dispatch_precheck.py fail-open 行为契约文档化 | tech-feasibility §5.4 / 本概要 §3.2 | ✅ |
|  4 | `.dispatch-state.json` schema 字段（current / started_at / pid 等）+ dispatch_state.py 三函数签名 | tech-feasibility §5.5 / 本概要 §3.4 | ✅ |
|  5 | touches glob 语义固化（pathspec gitignore 风格 vs 简化 glob） | tech-feasibility §5.6 / 本概要 §3.3 | ✅ |
|  6 | 3 份 schema 的 schema_version + SUPPORTED_VERSIONS 兼容窗口策略 | tech-feasibility §5.7 / 本概要 §3.1 | ✅ |
|  7 | F-007 派发模板 frontmatter 补 `touches: __TOUCHES__` 字段（含 `task-context-builder` Skill 填充逻辑同步） | notes.md:20 / tech-feasibility 待澄清 #2 | ✅ |
|  8 | 4 个新 gate 的 `applies_when` 触发条件（精确字段值，避免 ci 通道误命中） | 本概要 §3.5 | ✅ |
|  9 | render-docs.py 重生成 gate-checklist.md 列入 PR 提交前清单 | tech-feasibility §5.8 | ✅ |
| 10 | F-002 / F-003 是否合并 check_schema.py 复评（仅 B 案重复 > 60% 时） | 本概要 §4.1 T-01 | 可选 |
| 11 | F-001 回归基线：`tests/` 全量 pytest 现状快照（已知 603 passed / 8 skipped） | tech-feasibility §5.9 待澄清 #3 / 本概要 §1.3 备注 | 已闭环 |
| 12 | meta-schema.yaml `legacy` 字段说明补一行的精确 patch | plan.md:88 / 本概要 §1.2#22 | ✅ |
| 13 | CI quality-check.yml pytest 扩展的精确 patch（`pytest tests/ --ignore=tests/benchmarks/`）+ 提交时机（与本 PR 同包） | tech-feasibility §5.3 / 本概要 §1.3 备注 | ✅ |

---

## 待澄清清单

> tech-research 阶段 3 条已于 2026-05-06 实证回填（来源：requirements/REQ-2026-008/notes.md:18）；本概要无新增未决条目，仅延续：

1. **Task tool 的 stdin JSON 字段名 `tool_input.prompt`** [待用户确认]——detail-design 首日用最小 hook 抓一次实采样即可。当前所有解析逻辑按假设字段名设计；若实采样字段名不同，需调整 §3.2 / §3.3 hook 路径（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:734）。

2. **`feature-task.md.tmpl` frontmatter 缺 `touches` 字段**——本概要已写入 §1.2#19 / §3.7 / §6 待办#7；detail-design F-005 / F-007 必补，否则 V-03 fail（来源：requirements/REQ-2026-008/notes.md:20）。

3. **CI 扩展零修复成本**：`pytest tests/ --ignore=tests/benchmarks/` 已实证 603 passed / 8 skipped；F-006 可在本 PR 直接合入（来源：requirements/REQ-2026-008/notes.md:21）。

---

## 不在本设计范围

重申 requirement.md scope-out 6 项（来源：requirements/REQ-2026-008/artifacts/requirement.md:142）+ tech-feasibility 已剔项：

- 门禁链 `/requirement:next` "读清单自答"升级（属"门禁链优先"分支，下一轮做）
- `/code-review` 自动 loop 修复（保留人工 sign-off）
- worktree 隔离（与 `requirements/<id>/` 主分支约定冲突）
- 替换 Task tool 为 wrapper 脚本（用户偏好 hook 优先）
- DAG YAML 引擎（不引入新工具链）
- 改动保守档串行约束（"禁止并发派 implementer"红线保留）
- 受控自动重派 BLOCKED（保留"禁止原模型原上下文重试"红线，来源：requirements/REQ-2026-008/artifacts/requirement.md:158）
- Archon 整体迁移（D-001，仅借鉴范式）
