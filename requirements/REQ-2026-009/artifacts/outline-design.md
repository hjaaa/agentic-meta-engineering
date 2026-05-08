# REQ-2026-009 · 自定义工作流改造 — 概要设计

## 文档定位

把技术预研锁定的 D-005 ~ D-010 决策 + spec v2.2 + 14 项验收标准（AC-01 ~ AC-CLEAN）凝练为**模块级架构方案**。读者：detail-design 阶段的接口签名 / 时序图细化作者；Plan 6 自举切换前的实施小组。

- 详细决策原文：[plan.md](../plan.md) §决策记录 D-005 ~ D-010
- 外部协议 / 字段细节：[spec v2.2](../../../context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md) §5 ~ §11
- 可行性论证 / 工作量：[tech-feasibility.md](./tech-feasibility.md) §3 ~ §5

---

## 1. 总体架构

### 1.1 4 层模块视图

```
┌────────────────────────────────────────────────────────────────────┐
│ L1 入口层（Commands + Launcher）                                    │
│  - 11 个 /workflow:* 命令 (.claude/commands/workflow/*.md)         │
│  - 8 个 /requirement:* 兼容别名（3 月期，:next 立删）               │
│  - workflow-launcher Skill（关键词路由）                            │
│  - .claude/hooks/pre-tool-use-guard.sh（approve/reject AI 拦截）    │
└──────────────────────────────┬─────────────────────────────────────┘
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ L2 编排层（Skills）                                                 │
│  - workflow-engine：DAG 拓扑排序 / 节点决策表 / 8 种节点执行器       │
│    + approval 状态机 / loop 节点 / sub_workflow 嵌套（深度 ≤ 2）    │
│  - managing-workflow-runs：伞形 Skill，按 category 分发             │
└──────────────────────────────┬─────────────────────────────────────┘
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ L3 运行时核心（scripts/lib/workflow_*）                             │
│  - workflow_loader（双路径解析 D-007 / yaml schema 强校验）         │
│  - run_state（jsonl 读写 / RunState 重建 / 事件枚举）               │
│  - workflow_rollback（mv 归档 + .in_progress 原子标记 D-010）       │
│  - workflow_approve / workflow_reject（人机鉴别入口 D-006）         │
│  - topological_sort / substitute_vars / run_artifact_checks（辅助） │
└──────────────────────────────┬─────────────────────────────────────┘
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ L4 Schema + Artifacts 层                                            │
│  - workflow.yaml v2 schema（8 节点类型 + sub_workflow）             │
│  - meta.yaml schema（扩 category / parent_run_id 等）               │
│  - run-state.jsonl 事件枚举（cancel_requested / parent_cancelled    │
│    / parent_rolled_back 新增）                                      │
│  - runs/<id>/.archived/<ts>/（rollback 归档区）                     │
└────────────────────────────────────────────────────────────────────┘
```

| 层 | 职责 | 关键产出物 | 主要 ADR | 风险关联 |
|---|---|---|---|---|
| L1 入口层 | 命令路由、关键词触发、AI/人鉴别 | `/workflow:*` × 11、launcher Skill、hook 扩展 | D-006 / D-008 / D-009 | R-4 / R-6 / R-5 |
| L2 编排层 | DAG 拓扑、节点决策、状态机 | `workflow-engine` Skill、`managing-workflow-runs` Skill | D-001 / D-004 | R-2 / R-7 |
| L3 运行时核心 | 双路径 loader、jsonl IO、归档 | 5 个 `scripts/lib/workflow_*` | D-005 / D-007 / D-010 | R-1 / R-3 / R-8 |
| L4 Schema + Artifacts | yaml schema / meta / jsonl 事件 / 归档目录 | `workflow.yaml` v2 / `meta.yaml` 扩展 / `.archived/` | D-002 / D-010 | R-1 / R-8 |

> 来源：spec §3 / §4 / §5 / §7 / §9.3；plan.md ADR D-001 ~ D-010。

### 1.2 改动一览表

| 路径 | 操作 | 估算行数 | 主责 ADR | Plan 落地 |
|---|---|---|---|---|
| `.claude/workflows/requirement/standard-8phase.yaml` | 新建（38 节点 + 8 阶段 prompt 引用） | ~600 | D-001 | Plan 4 |
| `.claude/workflows/review/code-review-embedded.yaml` | 新建（验证 sub_workflow 嵌套） | ~250 | D-001 | Plan 4 |
| `.claude/workflows/prompts/*.md` | 新建（节点级 prompt 抽出，~16 个文件） | 各 ~50 | — | Plan 4 |
| `.claude/skills/workflow-engine/SKILL.md` + `reference/*.md` | 新建（节点决策表 / 拓扑 / 变量替换 / approval 状态机 / loop / sub_workflow） | ~1200 | D-001 / D-004 | Plan 2 / Plan 4 |
| `.claude/skills/managing-workflow-runs/SKILL.md` + `reference/category-rules/*` + `command-implementations/*` | 新建（按 category 分发；11 个命令实现） | ~800 | D-007 | Plan 5 |
| `.claude/skills/workflow-launcher/SKILL.md` + `reference/keyword-matching.md` | 新建（3 步仲裁规则） | ~150 | D-008 | Plan 5 |
| `.claude/commands/workflow/*.md` × 11 | 新建（命令定义） | 各 ~30 | D-008 / D-009 | Plan 5 |
| `.claude/commands/requirement/*.md` × 8 | **改写为别名** + deprecation warning（保留实际实现至 Plan 7） | 各 ~20 改 | D-009 | Plan 5 / Plan 7 |
| `.claude/commands/requirement/next.md` | **保留实际实现到 Plan 6 验证后**（覆盖 spec §4.3 立即删决策） | 0 改（暂留） | D-009 | Plan 6 / Plan 7 |
| `scripts/lib/workflow_loader.py` | 新建（双路径 `_resolve_run_dir` + 14 类 yaml 错误识别） | ~400 | D-002 / D-007 | Plan 1（已合并 6d55eaf） / Plan 3 |
| `scripts/lib/run_state.py` | 新建（jsonl 读写 + 事件枚举 + RunState 重建） | ~300 | — | Plan 2 |
| `scripts/lib/workflow_rollback.py` | 新建（mv 归档 + 子 run 整目录 + `.in_progress` 标记） | ~250 | D-010 | Plan 5 |
| `scripts/lib/workflow_approve.py` / `workflow_reject.py` | 新建（isatty fail-closed 兜底） | ~80 + ~80 | D-006 | Plan 2 |
| `scripts/lib/topological_sort.py` / `substitute_vars.py` / `run_artifact_checks.py` | 新建（Kahn / `${var}` / artifact lego） | ~150 + ~120 + ~200 | — | Plan 1 / Plan 2 |
| `.claude/hooks/pre-tool-use-guard.sh` | 修改（新增 `/workflow:approve` / `/workflow:reject` / `workflow_approve.py` 拦截分支） | +15 | D-006 | Plan 2 |
| `context/team/ai-collaboration.md` | 修改（规则三扩展为 sign-off / approval / reject 都是人类专属） | +10 | D-006 | Plan 2 |
| `scripts/lib/check_reviews.py` 的 `PHASE_REQUIREMENTS` | **Plan 7 删除（-57 行）**（Plan 6 自举验证通过 + 1 个迭代后） | -57 | D-009 / R-8 | Plan 7 |
| `scripts/lib/code_review_signoff.py` | **删除**（hook 接管校验后） | -150 | D-006 | Plan 7 |
| `scripts/lib/phase_enum.py` | **删除** | -30 | D-009 | Plan 7 |
| `requirements/` → `runs/` 批量 rename 工具 | 新建（一次性脚本） | ~80 | D-002 | Plan 7 |
| 各 SOP / `agentic-engineer-guide.md` / `CLAUDE.md` 引用更新 | 修改 | ~50 ~ 100 | D-009 | Plan 7 |
| `tests/lib/fixtures/workflows/invalid-*.yaml` × 14 | 新建（loader 错误识别用例） | 各 ~20 | — | Plan 1 |
| Plan 5 单测：rollback 4 场景 / launcher 仲裁 3 场景 / loader 双路径 4 场景 | 新建 | ~400 | D-007 / D-008 / D-010 | Plan 5 |

> 来源：spec §6 / §7 / §9 / §12；plan.md ADR Plan 落地点字段。

---

## 2. 关键流程时序

### 2.1 sub_workflow cancel 父子联动（D-005）

```
用户          父 Claude          父 jsonl          子 subagent       子 jsonl       TaskStop API
 │               │                   │                  │                │              │
 │─cancel──────▶│                   │                  │                │              │
 │               │─append           │                  │                │              │
 │               │  cancel_requested ▶                  │                │              │
 │               │                   │                  │                │              │
 │               │                   │   poll on node 边界 (interval≤30s)│              │
 │               │                   │◀──read───────────│                │              │
 │               │                   │  detect cancel_requested          │              │
 │               │                   │                  │─append─────────▶              │
 │               │                   │                  │  parent_cancelled             │
 │               │                   │                  │  + graceful exit              │
 │               │                   │                  │                │              │
 │               │  wait subagent return（≤30s graceful）│               │              │
 │               │                   │                  │                │              │
 │               │  if timeout > 30s ────────────────────────────────────│─────────────▶│
 │               │                                                       │   TaskStop   │
 │               │                                                       │   forceful   │
 │               │◀──exit code───────────────────────────────────────────│              │
 │◀──cancel ack──│                                                                      │
```

**关键点**：
1. 父 Claude 用 `Agent({run_in_background: true})` 派子，不阻塞主对话（spec §11.2 v2.1 修订）
2. 子 jsonl 永远由子自身写，无跨 run 文件写权限
3. cancel 时延上限 = poll 间隔 (默认 30s) + 子节点 graceful 退出耗时
4. `cancel_requested` 是 run-state.jsonl 新增事件枚举（Plan 2 落地）

> 来源：plan.md D-005；spec §11.2（v2.1 修订 line 1020+）；tech-feasibility R-2 line 159。

### 2.2 rollback 跨父子归档（D-010）

```
用户              /workflow:rollback             workflow_rollback.py     filesystem
 │                  │                                │                      │
 │─rollback ───────▶│                                │                      │
 │  --to-node=X     │                                │                      │
 │                  │─call rollback_run(rid, X)─────▶│                      │
 │                  │                                │                      │
 │                  │                                │ ① 拓扑序计算"X 及之后"产物路径集合 │
 │                  │                                │ ② mkdir .archived/<rollback-ts>/  │
 │                  │                                │ ③ touch <archived>/.in_progress  │
 │                  │                                │                      │
 │                  │                                │ ④ for 每个产物路径：               │
 │                  │                                │   shutil.move(原路径 → archived/) │
 │                  │                                │                      │
 │                  │                                │ ⑤ if 跨 sub_workflow 节点：       │
 │                  │                                │   shutil.move(runs/<child-id>/    │
 │                  │                                │      → archived/sub_runs/<child>/)│
 │                  │                                │   父 jsonl append parent_rolled_back │
 │                  │                                │                      │
 │                  │                                │ ⑥ 截断父 jsonl 尾部（保留至 X 之前）│
 │                  │                                │   原尾部 mv 为 archived/run-state.jsonl.tail │
 │                  │                                │                      │
 │                  │                                │ ⑦ rm <archived>/.in_progress      │
 │                  │                                │                      │
 │                  │◀──ok─────────────────────────  │                      │
 │◀──rolled back────│                                │                      │
```

**关键点**：
1. `.in_progress` 原子标记保证中断安全：rollback 写产物前先 `touch <archived>/.in_progress`，全部 mv 完成 + jsonl 截断后才 `rm`；`/workflow:continue` 续跑时检测到残留 `.in_progress` → 按 mv 进度完成未完的 mv 或回退已 mv 的产物到原位（详细回退算法在 detail-design 阶段定义），不允许带 partial state 推进
2. 子 run id 释放后**不复用**：下次父 continue 启新 child id
3. 多次 rollback 归档目录独立并存（v2 后续可加 `/workflow:archive --gc`）
4. **AC-10 验收**：跨父子 rollback 时子 run 必须有 `parent_rolled_back` 事件

> 来源：plan.md D-010；spec §11.3（v2.2 修订 line 1040+）；requirement.md OQ-02 line 134。

### 2.3 approval 节点人机鉴别（D-006）

```
用户/AI           Claude shell      pre-tool-use-guard.sh    workflow_approve.py
   │                 │                       │                       │
   │── input ───────▶│                       │                       │
   │ "/workflow:     │                       │                       │
   │  approve <rid>" │                       │                       │
   │                 │── tool call ─────────▶│                       │
   │                 │                       │ case 分支匹配 approve/reject │
   │                 │                       │                       │
   │                 │                       │  if !isatty(stdin):   │
   │                 │                       │    cat >&3 "禁止 AI 调 approve" │
   │                 │                       │    exit 2  ──── 拦截 ───┐ │
   │                 │                       │                       │ │
   │                 │                       │  else (人类 tty):     │ │
   │                 │                       │    pass through ─────▶│ │
   │                 │                       │                       │ │
   │                 │                       │                       │ ▼
   │                 │                       │       isatty fail-closed 兜底 │
   │                 │                       │       (B + C 双层防御) │
   │                 │                       │                       │ │
   │                 │                       │       写 jsonl approval_pending → approved │
   │                 │                       │                       │ │
   │◀──ok────────────│◀──────────────────────│◀──────────────────────│ │
```

**关键点**：
1. **B 层（hook 拦截）**：`pre-tool-use-guard.sh` 新增 case 分支，与原 `code_review_signoff.py:61` isatty 校验同构、只是搬到 hook 层
2. **C 层（软约束）**：`ai-collaboration.md` 规则三扩展为 sign-off / approval / reject 都是人类专属
3. spec §15 反对的是"双重确认链路（cli + tty 两处）"，单一 hook 层不属于"双"
4. `workflow_approve.py` / `workflow_reject.py` 内部仍 fail-closed `isatty` 兜底（hook 漏拦时双保险）

> 来源：plan.md D-006；spec §15（line 1163）；CLAUDE.md / ai-collaboration.md 规则三；tech-feasibility R-4 line 187。

### 2.4 launcher 关键词仲裁（D-008）

```
用户输入文本
    │
    ▼
┌──────────────────────────────────────────────┐
│ Step 1: state tiebreaker                     │
│   query active runs                          │
│   if 任一 run.state == approval_pending:     │
│     match approve/reject keywords first      │
│     if hit → 跳到 Step 4                     │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Step 2: 最长匹配                              │
│   list keywords by length DESC               │
│     "继续之前的需求" → /workflow:continue    │
│     "跑下代码评审"   → /workflow:run cre     │
│     "我要发版"      → /workflow:run release  │
│     "开个新需求 X"  → /workflow:run "X"      │
│     "approve"      → /workflow:approve       │
│     "reject:"       → /workflow:reject       │
│   take longest hit                           │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Step 3: 兜底 ask                              │
│   if ≥2 等长关键词同时命中（极小概率）:       │
│     ask 用户消歧                              │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ Step 4: 翻译为 /workflow:* 命令并执行         │
│   多步连接词（"再" / "and then"）= **不在 MVP**│
└──────────────────────────────────────────────┘
```

**关键点**：
1. state tiebreaker 优先级最高（避免 "approve 这个需求并跑下评审" 误判）
2. 关键词长度排序表写入 `reference/keyword-matching.md`
3. Skill **不引入新能力**，只翻译为 `/workflow:*`（来源：spec §4.2 Archon 设计原则）；Step 1 state tiebreaker 读 `run-state.jsonl` 仅用于路由仲裁（确认 active runs 状态），不参与节点执行 / 数据修改
4. 多意图组合（"开新需求 + 跑评审"）分两句说，串行执行能力 v2 演进

> 来源：plan.md D-008；spec §4.2（line 177）；tech-feasibility R-6 line 218。

---

## 3. 模块划分

### 3.1 L1 入口层

| 文件 / Skill | 责任 | 与下层契约 |
|---|---|---|
| `.claude/commands/workflow/*.md` × 11 | 用户面命令定义；调 `managing-workflow-runs` Skill | 通过 ARGUMENTS 把参数传给 Skill |
| `.claude/commands/requirement/*.md` × 8 | 兼容别名 + deprecation warning；3 月期内**保留实际实现** | 调 `managing-requirement-lifecycle`（旧）或转 `managing-workflow-runs`（新） |
| `.claude/skills/workflow-launcher/SKILL.md` | 关键词路由；3 步仲裁；翻译为 `/workflow:*` | 不直接调 lib，统一走 slash command |
| `.claude/hooks/pre-tool-use-guard.sh` | 鉴别 AI vs 人 shell；拦截 approve/reject 调用 | 命中且非 tty → exit 2 |

**禁止跨层**：
- L1 命令不允许直接调 `scripts/lib/workflow_*.py`，必须走 L2 Skill
- L2 Skill 不允许直接读写 `runs/<id>/run-state.jsonl` / `meta.yaml` 等 L4 文件，必须经 L3 `run_state.py` / `workflow_loader.py` 接口；L4 文件由 L3 独占 IO 权限
- L3 lib 不允许互相调用业务编排逻辑（topological_sort / substitute_vars / run_artifact_checks 是无状态工具，可被多方调用；其余 lib 只暴露 API 给 L2）

### 3.2 L2 编排层

| Skill | 责任 | 调用关系 |
|---|---|---|
| `workflow-engine` | DAG 拓扑排序 / 8 节点类型决策表 / approval 状态机 / loop / sub_workflow 嵌套 / `RunState` 重建 | 调 L3 `topological_sort.py` / `run_state.py` / `substitute_vars.py` / `run_artifact_checks.py` |
| `managing-workflow-runs` | 伞形 Skill；按 `category`（requirement / review / release / knowledge / pr / assist）分发到 `reference/category-rules/<cat>.md`；11 个命令实现细节在 `command-implementations/<cmd>.md` | 调 L3 `workflow_loader.py` / `workflow_rollback.py` / `workflow_approve.py` / `workflow_reject.py` |

**节点决策表**（spec §7.2）：8 节点类型互斥字段；执行入口由 SKILL.md 的 reference 描述，**不**用 if-elif 散落。

### 3.3 L3 运行时核心

| 文件 | 责任 | 关键 API |
|---|---|---|
| `workflow_loader.py` | yaml 加载 / 14 类错误识别 / 双路径 `_resolve_run_dir(req_id) → Path`（先 stat `requirements/`，再 stat `runs/`） | `load(yaml_path) → Workflow`、`_resolve_run_dir(rid)` |
| `run_state.py` | jsonl 读写 / 事件枚举 / `RunState` 重建（最终状态推导） | `append_event(rid, event)`、`build_state(rid) → RunState` |
| `workflow_rollback.py` | mv 归档 / 子 run 整目录 mv / `.in_progress` 原子标记 / jsonl 截断 | `rollback_run(run_id, to_node, target_id=None)` |
| `workflow_approve.py` / `workflow_reject.py` | 人机鉴别入口；hook 漏拦时 isatty fail-closed 兜底 | `approve(rid, comment=None)` / `reject(rid, reason)` |
| `topological_sort.py` | Kahn 算法 + 环检测（含 sub_workflow 嵌套环） | `topo_sort(nodes) → list[Node]` |
| `substitute_vars.py` | `${VAR}` 替换；`$LOOP_OUTPUT` / `$RUN_ID` / `$ARTIFACTS_DIR` 等 | `substitute(text, ctx) → str` |
| `run_artifact_checks.py` | 5 lego 验证（output_format / when / approval / bash / critic） | `run_checks(node, artifact) → list[Failure]` |

**事件枚举新增**（来源 spec §11.2 + plan.md D-005 / D-010）：
- `cancel_requested`（父写）
- `parent_cancelled`（子写）
- `parent_rolled_back`（子写）

### 3.4 L4 Schema + Artifacts

**workflow.yaml v2 schema**（spec §6）：
- 顶层字段：`name` / `version` / `description` / `default_model` / `default_effort` / `default_thinking` / `nodes`
- 8 种节点类型互斥字段：`prompt` / `bash` / `skill` / `agent` / `loop` / `approval` / `artifact` / `sub_workflow`
- 公共字段：`id` / `depends_on` / `when` / `trigger_rule` / `retry` / `timeout_seconds` / `output_threshold`
- sub_workflow 嵌套深度 ≤ 2（loader 拒绝）

**meta.yaml schema 扩展**（spec §5.3）：
- 新增 `category`（requirement / review / release / ...）
- 新增 `parent_run_id`（sub_workflow 子 run 必填）
- 兼容旧字段（`phase` / `services` / `feature_area` 等）

**run-state.jsonl 事件**（spec §5.4 + 本需求新增）：
- 已有：`run_started` / `node_started` / `node_completed` / `node_failed` / `approval_pending` / `approval_approved` / `approval_rejected` / `paused_in_loop` / `run_completed` / `run_cancelled`
- 新增：`cancel_requested` / `parent_cancelled` / `parent_rolled_back`

**`.archived/<rollback-ts>/` 目录**（D-010）：
- 路径：`runs/<id>/.archived/<ISO8601-with-tz>/`
- 内容：`<原相对路径>` 镜像 + `sub_runs/<child-id>/` + `run-state.jsonl.tail` + `.in_progress` 临时标记

---

## 4. 跨模块协同

### 4.1 状态联动协议（父子 run）

```
父事件                          子事件                     来源 ADR
──────────────────────────────────────────────────────────────────
cancel_requested（父写）   →   parent_cancelled（子写）    D-005
（rollback 触发）          →   parent_rolled_back（子写）  D-010
paused（用户主动）         →   不联动，子独立运行           D-004
父 run_completed            →   子 run 不联动                spec §11.2
```

**协议铁律**：
- 子 jsonl 永远由子自身写，父不跨 run 写
- 父用 jsonl append（O_APPEND 原子）传信号；子用节点边界 poll 读
- cancel 时延上限：poll 间隔 + graceful 退出耗时（D-005）

### 4.2 节点间数据流

| 数据载体 | 写方 | 读方 | 替换语法 |
|---|---|---|---|
| `${RUN_ID}` | 引擎初始化时注入 | 所有节点 | `${RUN_ID}` |
| `${ARTIFACTS_DIR}` | 引擎按 category 解析（requirement → `artifacts/`，其他 → `output/`） | 所有节点 | `${ARTIFACTS_DIR}` |
| `${LOOP_OUTPUT}` | loop 节点每轮迭代 | loop body 内节点 | `$LOOP_OUTPUT` |
| 节点 `outputs` 字段 | 节点完成时写 jsonl | 下游 `depends_on` 节点 | `${nodes.<id>.outputs.<key>}` |

> 来源：spec §6.5；§7.1。

### 4.3 Hook 协同

`pre-tool-use-guard.sh` case 分支（D-006）：
```
case "$tool_input" in
  *"/workflow:approve"*|*"/workflow:reject"*|*"workflow_approve.py"*|*"workflow_reject.py"*)
    if [ ! -t 0 ]; then
      cat >&3 "..AI shell 禁止调 approve/reject，请由人在 tty 终端执行.."
      exit 2
    fi
    ;;
esac
```

兜底：`workflow_approve.py` / `workflow_reject.py` 内部第一行 `if not sys.stdin.isatty(): sys.exit(2)`。

---

## 5. 自举与兼容期专题

### 5.1 双路径 loader（D-007）

**实现方式**：`workflow_loader.py` 内置默认识别——`_resolve_run_dir(req_id)` 先 stat `requirements/<rid>/`，不存在则 stat `runs/<rid>/`，都不存在抛 `WorkflowError`。**不**新增 yaml schema 字段，**不**新增 `loader-config.yaml`。

**清理成本**：3 月兼容期结束后只删 loader 中"探测 `requirements/`"的 1 行代码。

**单测覆盖（4 场景）**：
1. 仅 `requirements/` 下存在 → 命中
2. 仅 `runs/` 下存在 → 命中
3. 两处都存在 → 优先 `runs/`（新版优先）
4. 两处都不存在 → 抛 `WorkflowError`

> 来源：plan.md D-007；spec §5.2；tech-feasibility line 113。

### 5.2 旧命令实际实现保留期表（D-009）

| 命令 | 兼容期处理 | 实现归属 | Plan 7 清理 |
|---|---|---|---|
| `/requirement:new` | 别名 + 实际实现保留 | 旧 `managing-requirement-lifecycle` | ✅ 删 |
| `/requirement:continue` | 别名 + 实际实现保留 | 同上 | ✅ 删 |
| `/requirement:status` | 别名 + 实际实现保留 | 同上 | ✅ 删 |
| `/requirement:list` | 别名 + 实际实现保留 | 同上 | ✅ 删 |
| `/requirement:save` | 别名 + 实际实现保留 | 同上 | ✅ 删 |
| `/requirement:rollback` | 别名 + 实际实现保留 | 同上 | ✅ 删 |
| `/requirement:submit` | 别名 + 实际实现保留 | 同上 | ✅ 删 |
| `/requirement:archive` | 别名 + 实际实现保留 | 同上 | ✅ 删 |
| `/requirement:next` | **保留实际实现到 Plan 6 验证后**（覆盖 spec §4.3 立即删） | 旧 `managing-requirement-lifecycle` | ✅ 删（Plan 6 通过后） |

**所有别名输出 deprecation warning**："此命令将于 2026-08-08 移除，请改用 `/workflow:<对应命令>`"。

> 来源：plan.md D-009 覆盖 spec §4.3 / §15；requirement.md OQ-C line 149。

### 5.3 自举验证硬阈值（Plan 6 SOP 框架）

**目标**：本 REQ-2026-009 自身从 tech-research 推到 completed 全程必须用新引擎跑通。

**SOP**（详细落地放 Plan 6 任务文档）：
1. 第 4 周起切换到 `/workflow:run standard-8phase --rid=REQ-2026-009`（已在 outline-design 阶段使用旧命令推进的不算违反，硬阈值**从切换时刻起算**）
2. 切换后**全程禁用** `/requirement:*`，任何阶段 fallback 到旧命令视为验证失败
3. 验证通过条件：tech-research → outline-design → detail-design → task-planning → development → testing → completed 全程无降级
4. 验证失败 → 阻塞 Plan 7（旧命令 / `PHASE_REQUIREMENTS` / `code_review_signoff.py` 不能删）

> 来源：plan.md D-009；spec §4.3 修订；tech-feasibility 5.2 Plan 6。

### 5.4 PHASE_REQUIREMENTS 删除顺序约束（R-3 OPS 风险）

**约束**：D-009 旧命令实现存在期间 `scripts/lib/check_reviews.py:57` 的 `PHASE_REQUIREMENTS` **必然不能删**，否则 R001 ~ R005 五个规则失效，phase-transition 门禁会允许未经评审的需求切阶段。

**Plan 7 清理顺序**（硬性）：
```
Plan 6 验证通过
    │
    ▼
等 1 个迭代周期（观察期）
    │
    ▼
新引擎接管 artifact 校验（migration 测试覆盖 R001-R005 等价语义）
    │
    ▼
删旧命令实现 + PHASE_REQUIREMENTS + phase_enum.py + code_review_signoff.py + 旧 SOP 引用
```

**migration 测试**（detail-design 阶段细化）：覆盖 R001-R005 + R006（旧门禁规则）的等价语义到新引擎 `run_artifact_checks.py`。

> 来源：plan.md D-009；tech-feasibility R-3 line 172。

---

## 6. 验收对齐（AC-01 ~ AC-CLEAN 映射）

| AC | 描述 | 主责模块 | 验证手段 | 时序 |
|---|---|---|---|---|
| AC-01 | 改阶段顺序只改 1 yaml | L4 schema + L2 engine | 改 standard-8phase 节点顺序，不改 .py / .md | testing |
| AC-02 | MVP 双模板 loader 加载无错 | L3 `workflow_loader` | `python3 workflow_loader.py --strict` exit 0 | development |
| AC-03 | 11 个 `/workflow:*` 全可调 | L1 commands + L2 `managing-workflow-runs` | 11 命令逐一 smoke | development |
| AC-04 | `/workflow:continue` 任意中断点续跑 | L2 `workflow-engine` `RunState` 重建 | 3 种状态续跑 | development |
| AC-05 | 5 lego 可组合 | L3 `run_artifact_checks` + L2 engine | code-review-embedded.yaml 跑通 | development |
| AC-06 | 节点级 model/effort/thinking 覆盖 | L4 schema + L2 engine | yaml 测试 | development |
| AC-07 | 8 节点互斥 + 嵌套 ≤ 2 | L3 `workflow_loader` | invalid-mutex / invalid-deep-nest 拒绝 | development |
| AC-08 | 14 类 yaml 错误识别 | L3 `workflow_loader` | invalid-*.yaml 全拒并含行号 | development |
| AC-09 | 9 个 `/requirement:*` 命令 3 月兼容期保留实际实现 + deprecation warning（含 `:next`；D-009 修订覆盖 spec §4.3 立即删） | L1 兼容别名 + L2 旧 Skill | 9 命令 smoke + warning 内容验证；Plan 6 自举验证通过后 Plan 7 真删 | development / Plan 6 / Plan 7 |
| AC-10 | 跨父子 rollback 子写 `parent_rolled_back` | §2.2 时序 + L3 `workflow_rollback` | 4 场景单测 | development |
| AC-11 | 父 cancel → 子写 `parent_cancelled` | §2.1 时序 + L3 `run_state` | smoke：子在 paused_at_subworkflow 时父 cancel | development |
| AC-E2E | 老 `requirements/*` 用新引擎续跑 | §5.1 双路径 loader | 选 1 个 paused 老需求 continue | testing |
| AC-SELF | 自举：第 4 周起新引擎承载本需求 | §5.3 Plan 6 SOP | tech-research → completed 无降级 | Plan 6 |
| AC-CLEAN | grep 无残留 + hook 拦截 | §5.4 顺序约束 + Plan 7 | 全仓 grep + pre-commit hook 测试 | testing |

> 来源：requirement.md §验收标准。

---

## 7. 进入 detail-design 的待办

| # | 项 | 主责 ADR | 输出形态 |
|---|---|---|---|
| 1 | 11 个 `/workflow:*` 命令的接口签名（参数 / ARGUMENTS / 返回） | D-008 | `command-implementations/*.md` |
| 2 | 节点级 prompt 文件清单（`.claude/workflows/prompts/*.md`，~16 个） | D-001 | features.json + 文件清单 |
| 3 | `features.json` 拆分（38 节点 + 11 命令 + 别名 + 清理任务如何映射 feature_id） | — | features.json |
| 4 | `keyword-matching.md` 关键词长度排序表（含 6 类基础关键词 + tiebreaker 优先级） | D-008 | reference/keyword-matching.md |
| 5 | hook 内 `pre-tool-use-guard.sh` case 分支详细脚本（含 fd 3 写入 / exit 码） | D-006 | hook 脚本 patch + 单测 |
| 6 | rollback 4 场景单测设计（单层 R1 / 跨父子 F1 / 多次 T1 / rollback 到 root） | D-010 | tests/lib/test_workflow_rollback.py |
| 7 | sub_workflow 父子状态联动 e2e 测试设计（cancel + rollback 两条关键路径） | D-005 / D-010 | smoke test 计划 |
| 8 | migration 测试设计（R001-R006 等价语义到新引擎，Plan 7 前置） | D-009 / R-3 | tests/migration/*.py |
| 9 | `requirements/` → `runs/` 批量 rename 工具的 path 引用扫描策略（grep / sed 范围 / 全仓引用排查 / 历史 commit 注释如何处理 / pre-commit hook 拦截规则） | D-002 | tools/migrate_requirements_to_runs.py 设计文档 + 引用清单 |

---

## 待澄清清单

D-005 ~ D-010 已闭合 OQ-02 / OQ-A / OQ-B / OQ-C / OQ-D（详见 plan.md ADR）。

本设计阶段无新增 OQ。

进入 detail-design 阶段时如下细节可能浮现新问题（提示性，非阻塞）：
- `workflow.yaml` v2 中 `output_threshold` 的字节数 vs 行数语义（spec §6.11）
- `loop` 节点 `$LOOP_OUTPUT` 多变量场景（多 outputs 字段 vs 单输出）
- `sub_workflow` 节点 `inputs` 透传约束（白名单 / 黑名单 / 全透）

---

## 不在本设计范围

- **Post-MVP 第一批**（spec §14）：`lite-3phase` / `hotfix` / `release-cut` / `codex-review-loop` / `pr-feedback-handle` / `extract-experience` / `generate-sop` / `general-assist` 模板
- **Post-MVP 其他**：多 provider 共存 / git worktree 强制隔离 / 独立 daemon / HTTP API server / Web Dashboard / Postgres 持久化 / `maxBudgetUsd` 节点级硬熔断 / 多步连接词串行执行
- **不引入**：兼容期到期后旧别名的自动清理 CI 门禁（D-003 锁定为人工清理）
- **不引入**：双重确认链路（cli + tty 两处校验，spec §15 反对）；当前 D-006 是单一 hook 层
- **延后**：`requirements/` → `runs/` 批量 rename 到 Plan 7 一次性执行
