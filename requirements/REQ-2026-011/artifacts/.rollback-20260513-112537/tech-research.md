---
id: REQ-2026-011
phase: tech-research
title: workflow runtime DAG 调度与节点 dispatcher 补全 · 技术预研
created_at: 2026-05-13T10:37:36+08:00
refs-tech-feasibility: true
---

# REQ-2026-011 · 技术预研报告

## 1. 评估方法

聚焦"具体怎么改、改几行、几人天、坑在哪"，不重做 research.md 的宏观 Archon 对比。

类比参照：REQ-2026-010 实际 9.8 天（AC-01~05 五个 AC，main loop 框架 3.5 天为主体）（来源：requirements/REQ-2026-010/artifacts/tech-research.md:127）；REQ-2026-009 Plan 2 引擎主循环 15 天（含完整 approval + loop + sub_workflow）（来源：requirements/REQ-2026-009/artifacts/tech-feasibility.md:255）。

## 2. 可行性结论

**feasibility: high**

P0 三块改造（DAG scheduler / artifact dispatcher / approval 闭环）全部可行：

- `topological_layers()`（来源：scripts/lib/topological_sort.py:25）已有完整 Kahn 实现，DAG scheduler 是直接复用；
- `run_artifact_checks()`（来源：scripts/lib/run_artifact_checks.py:145）已覆盖 5 类 artifact 校验，artifact dispatcher 是直接调用；
- approval 闭环缺口已明确定位（来源：scripts/lib/workflow_approve.py:65）（来源：scripts/lib/workflow_reject.py:95），改造量确定。

无新技术依赖，无新第三方库，无 DB 改动。

**风险 Top 3**：

1. DAG scheduler 无 feature flag（一次性切换），旧 yaml（仅 `next` 字段）退化兼容覆盖不足会导致所有已有 yaml 跑失败。
2. `on_reject` 运行时语义未在 schema 层明确（来源：scripts/lib/workflow_loader.py:400），AC-03b 实现细节待 detail-design 确认。
3. `node_ready` / `awaiting_claude_action` 两个新事件/状态需同步扩展 `VALID_EVENT_TYPES`（来源：scripts/lib/run_state.py:54）、`RunState.rebuild`（来源：scripts/lib/run_state.py:133）、`DispatchOutcome`（来源：scripts/lib/workflow_dispatcher.py:37）三处，漏一处会导致 jsonl 写入 WorkflowError。

---

## 3. AC 改造点逐条定位

### 3.1 AC-01 DAG ready-node scheduler（P0）

**现状**：主循环（IB-13 拆模块后入口层精简至 281 行；来源：scripts/lib/workflow_continue.py:48）条件 `while run_state.state == "running" and run_state.current_node` 依赖 `current_node` 非空。`_next_node()`（IB-13 拆模块后已移入 workflow_scheduler.py；来源：scripts/lib/workflow_scheduler.py:23）只读 `current_node.next`，不消费 `depends_on`。首次启动（`current_node=None`）或仅用 `depends_on` 描述依赖时引擎无法推进。

**改造方案**：新增 `_ready_nodes(workflow, run_state) -> list[str]` 函数，复用 `topological_layers()`（来源：scripts/lib/topological_sort.py:25），传入 loader 已展开的 `depends_on` 拓扑（来源：scripts/lib/workflow_loader.py:475），排除 `node_outputs` 中已完成节点，返回当前 ready 集合首项。主循环入口：`current_node` 为 None 时先调 `_ready_nodes` 取首层 ready 节点。`_next_node` 保留为 `depends_on` 为空时退化路径（来源：requirements/REQ-2026-011/artifacts/requirement.md:89）。`_build_node_map()`（来源：scripts/lib/workflow_continue.py:28）不变。改动量：`_ready_nodes` 约 35~45 行；主循环改造约 15~20 行。

**测试覆盖**：e2e：构造 ≥ 5 节点仅用 `depends_on` 的最小 yaml，跑过两层；e2e：`code-review-embedded.yaml` 8 个 checker 被识别为同层 ready（均 `depends_on: [cr-prepare]`）。

**工作量估算**：1.5~2.5 天（design 0.5 / dev 1 / test 0.5~1）

**风险**：末节点判定函数 `_finalize_after_rebuild_if_last_topology_node()`（IB-13 拆模块后已移入 workflow_scheduler.py；来源：scripts/lib/workflow_scheduler.py:293）依赖 `_next_node(last_node, None)` 判断拓扑末尾，DAG 切换后此判断逻辑需同步扩展，否则 `workflow_completed` 可能不写（likelihood: medium, impact: high）。

---

### 3.2 AC-02 artifact dispatcher（P0）

**现状**：`dispatch_node()`（来源：scripts/lib/workflow_dispatcher.py:110）if/elif 派发 7 类节点（来源：scripts/lib/workflow_dispatcher.py:137），`else` 分支（来源：scripts/lib/workflow_dispatcher.py:153）抛 WorkflowError。`standard-8phase.yaml` 首节点 `bootstrap-validate`（来源：.claude/workflows/requirement/standard-8phase.yaml:51）为 `artifact` 类，当前命中 `else` 直接 node_failed。

**D-01 复用矩阵预研结论**：

| 候选 | 是否复用 | 原因 |
|---|---|---|
| `check_meta.py` | 否 | 绑定 meta-schema.yaml 业务语义，非通用 artifact 校验 |
| `check_sourcing.py` | 否 | 专用文档三态校验，无 must_exist 语义 |
| `check_index.py` | 否 | INDEX.md 完整性校验，无关 |
| `run_artifact_checks.py` | **是** | `run_artifact_checks(spec, cwd)`（来源：scripts/lib/run_artifact_checks.py:145）已实现 must_exist / must_not_exist / schema_check / must_contain_sections / must_match_regex 五类校验，接口干净，可被引擎直接调用 |

**D-01 结论**：本报告阶段关闭，无需延期 detail-design。复用 `run_artifact_checks`，直接调用即可。

**改造方案**：在 `dispatch_node()` if/elif 链中插入 `elif "artifact" in node` 分支（1 行），新增 `_dispatch_artifact_node()` 函数（约 40~50 行）：取 `node["artifact"]` spec，对路径字段做 `substitute_vars(escape_for_bash=False)`（路径字面值注入），调用 `run_artifact_checks(spec, cwd=root)`，无失败写 `node_completed`，有失败写 `node_failed`。

**测试覆盖**：e2e：`standard-8phase.yaml` 的 `bootstrap-validate` 跑通，jsonl 含 `node_completed`；unit：must_exist 缺文件场景 → `node_failed` 含 error detail。

**工作量估算**：1~2 天（design 0.3 / dev 0.5~1 / test 0.5）

**风险**：`substitute_vars` 对 artifact 路径必须用 `escape_for_bash=False`，否则生成带引号路径字符串导致 must_exist 永远失败（likelihood: medium, impact: high）。

---

### 3.3 AC-03 approval 闭环 + on_reject（P0）

#### AC-03a：approve 后写 node_completed

**现状**：`workflow_approve.py` 只写 `approval_approved`（来源：scripts/lib/workflow_approve.py:65），不写 `node_completed`。`RunState.rebuild`（来源：scripts/lib/run_state.py:198）看到 `approval_approved` 后仅清 `pending_approval` + state 置 running，approval 节点留在"未完成"，下次 `continue` 会重派。

**改造**：在 `workflow_approve.py` 写 `approval_approved` 后追加写 `node_completed`（约 10 行），同时写 `node_id`（取自 `run_state.pending_approval`）。

**工作量**：0.5 天

#### AC-03b：reject 后写 node_failed + on_reject 跳转

**现状**：`workflow_reject.py` 注释明确 "on_reject 路径由 main loop（F-006）处理"（来源：scripts/lib/workflow_reject.py:95）但未实现。

**on_reject schema 分析**：`workflow_loader.py` 必填字段为 `prompt + max_attempts`（来源：scripts/lib/workflow_loader.py:400），无 `node` 字段。实际 yaml 示例（来源：.claude/workflows/requirement/standard-8phase.yaml:156）`on_reject.prompt` 是"给 AI 的修订指引"，无显式跳转目标节点。

**on_reject 语义判断**：当前语义为"原 approval 节点重试，以 `on_reject.prompt` 为上下文给 AI 修订"，非跳转到独立节点 [待用户确认]（详见 §待澄清清单 Q-01）。

**改造方向**：`workflow_reject.py` 追加写 `node_failed`（约 10 行）；main loop `_route_outcome()`（来源：scripts/lib/workflow_continue.py:258）的 `failed` 分支读 `on_reject.prompt` 构造修订上下文，推回原节点重跑。

**工作量**：1.5~2.5 天（含语义确认不确定度）

#### AC-03c：attempt 计数 + 上限 workflow_failed

**改造**：统计 jsonl 中同节点历史 `approval_rejected` 事件数，达 `on_reject.max_attempts` 时写 `workflow_failed`（reason=`approval_attempts_exhausted`）。约 15 行。

**D-02 结论**：yaml schema 层已强制 `max_attempts` 必填（来源：scripts/lib/workflow_loader.py:400），引擎侧无需维护独立默认值。D-02 在本报告阶段关闭 [待用户确认]（详见 §待澄清清单 Q-02）。

**工作量**：0.5~1 天

**AC-03 风险**：reject 改动必须保持 isatty 校验不减弱（来源：scripts/lib/workflow_reject.py:39），D-006 hook 拦截范围不变（来源：requirements/REQ-2026-011/artifacts/requirement.md:91），新增代码必须在 isatty 校验通过之后（likelihood: low, impact: critical）。

---

### 3.4 AC-04 AI 节点完成契约（P1）

**现状**：三类 AI 节点均直接写 `node_completed` 而不等待真实执行：`_dispatch_agent_node`（来源：scripts/lib/workflow_dispatcher.py:190）、`_dispatch_skill_node`（来源：scripts/lib/workflow_dispatcher.py:221）、`_dispatch_prompt_node`（来源：scripts/lib/workflow_dispatcher.py:262）。

**save_node_result.py 模块结构**：参照 `save_review.py`（来源：scripts/lib/save_review.py:1）平级布局，新建 `scripts/lib/save_node_result.py`（约 120~150 行）：

- CLI：`python3 scripts/lib/save_node_result.py --run=<id> --node=<id> --output=<json>`
- 核心校验：run state 必须为 `awaiting_claude_action`，output 为合法 JSON，node_id 非空
- 写 `node_completed` 事件到 jsonl

**node_ready 事件 schema + 状态机**：三类 AI 节点 dispatcher 改为写 `node_ready` 事件并返回 outcome=`awaiting_claude_action`。需同步扩展：`VALID_EVENT_TYPES`（来源：scripts/lib/run_state.py:54）新增 `node_ready`；`RunState.rebuild`（来源：scripts/lib/run_state.py:133）处理 `node_ready` → state=`awaiting_claude_action`；`DispatchOutcome`（来源：scripts/lib/workflow_dispatcher.py:37）扩展 `awaiting_claude_action`。

**D-006 hook 扩展**：`save_node_result.py` 与 `save_review.py signoff` 性质不同——允许主 Claude Code 调用（执行节点产出后回写），建议不加 hook 拦截，但 CLI 内部校验 state=`awaiting_claude_action`，非此状态调用 exit 1 [待用户确认]（详见 §待澄清清单 Q-03）。

**工作量估算**：2~3 天（design 0.5 / dev 1~1.5 / test 0.5~1）

**风险**：若 AI 自调 `save_node_result.py` 时 run state 不为 `awaiting_claude_action`（如节点未真实执行），state 校验可拦截（likelihood: low after 校验, impact: high without 校验）。

---

### 3.5 AC-05 active-run / path-lock（P1）

**三件套实现路径**：新建 `scripts/lib/workflow_lock.py`（约 80~100 行），参照 `run_state.py` 已有 `fcntl.flock`（来源：scripts/lib/run_state.py:313）实现：

1. **取锁**：`runs/.locks/<run-id>.lock` 写 `{"pid": os.getpid(), "created_at": <ts>}`，`fcntl.LOCK_EX|LOCK_NB` 非阻塞取锁；requirement 类 run 同时建 `requirements/.locks/<req-id>.lock` → `../../runs/.locks/<run-id>.lock` symlink。
2. **stale 清理**：取锁失败时读锁文件 pid + created_at，`os.kill(pid, 0)` 检测存活；pid 不存在（ProcessLookupError）→ stale 锁删除重试；pid 存在 → 打印 `"another continue is running, pid=N, started_at=T"` + exit 1。
3. **释放**：`atexit.register(release_lock, lock_file)` + 删锁文件。

**macOS / Linux 行为一致性**：`fcntl.flock(LOCK_EX|LOCK_NB)` 和 `os.kill(pid, 0)` 在 macOS（Darwin 25.4）与 Linux 行为一致，均为 BSD flock 语义。pid 复用极小概率下可能误清新锁，靠 created_at 二次校验缓解（来源：requirements/REQ-2026-011/plan.md:77）。

**工作量估算**：1.5~2.5 天（design 0.5 / dev 1 / test 0.5~1）

**风险**：symlink 建立需 `runs/.locks/` 目录预先存在，`acquire_lock` 中需 `mkdir -p`（likelihood: low, impact: medium）。

---

### 3.6 AC-06 status doctor 增强（P1）

**现状**：`_render_status()`（来源：scripts/lib/workflow_status.py:22）仅输出 run_id / state / current_node / completed 列表，无 ready / blocked / paused 节点区分，无 stale 检测。

**heartbeat 写入策略**：每次 `dispatch_node()` 调用前写 `heartbeat` 事件（新增到 `VALID_EVENT_TYPES`，约 5 行），`RunState.rebuild` 记录 `last_heartbeat_ts`。备选：不新增事件类型，直接从 `last_event_ts` 推算（零成本，粒度粗）[待用户确认]（详见 §待澄清清单 Q-04）。

**D-03 预研结论**：stale 阈值候选 15/30/60 分钟。`standard-8phase.yaml` 中 agent 节点（如 req-quality-review）使用 `model: opus[1m]`，预计 5~30 分钟；bash 节点 <5 秒。建议默认 30 分钟，但以 detail-design 阶段真实节点执行时长统计为准 [待用户确认]（详见 §待澄清清单 Q-05）。

**`--verbose` 增量**：基于 `topological_layers()`（来源：scripts/lib/topological_sort.py:25）计算 ready/blocked 集合（约 20 行新逻辑）；每节点显示 `[completed]` / `[ready]` / `[blocked by: X, Y]` / `[running]` / `[failed]` 标记。三类 stuck 场景由 pytest fixture 构造测试。

**工作量估算**：1.5~2.5 天（design 0.5 / dev 0.7~1 / test 0.5~1）

---

### 3.7 AC-07~10 P2 体验项

**AC-07 loop until_bash（P2）**：`_dispatch_loop_node()`（来源：scripts/lib/workflow_dispatcher.py:386）已实现 `max_iterations` 计数，缺 `until_bash` 分支。改造：增加 `loop.until_bash` bash 命令执行（约 25 行），returncode=0 时触发 `loop_done`，否则继续迭代。工作量：1~1.5 天。风险：`until_bash` 无限循环需 `max_iterations` 硬上限兜底。

**AC-08 sub_workflow 父子回填（P2）**：`_dispatch_sub_workflow_node()`（来源：scripts/lib/workflow_dispatcher.py:430）创建子 run 后返回 `sub_workflow_pending`，main loop 的 `sub_workflow_pending` 分支（IB-13 拆模块后此 outcome 路由分支已移入 workflow_outcome_router.py 的 `_route_outcome`；来源：scripts/lib/workflow_outcome_router.py:225）直接 return False 不做任何处理。改造：在此分支增加子 run jsonl 轮询逻辑（约 40~60 行），子 run 终态后写父 run `child_*` 事件 + 父节点 `node_completed/node_failed`，尊重 `on_subworkflow_failure`。工作量：1.5~2.5 天。风险：子 run 路径查找依赖 D-007 双轨兼容。

**AC-09 fuzzy routing + workflow list --json（P2）**：launcher 增加 `difflib.get_close_matches` 编辑距离 ≤ 2 的 fuzzy 匹配（无新依赖，约 20 行）；`workflow list` 增加 `--json` 输出（约 30 行）。工作量：1~1.2 天。风险：fuzzy 匹配阈值过低会误触发。

**AC-10 Claude 运行参数白名单（P2）**：在 `workflow_loader.py` 节点 schema 校验中补充 `allowed_tools / denied_tools / mcp / skills / agents / idle_timeout / output_format` 字段类型校验；dispatcher 层读取并透传。工作量：1~1.5 天。风险：字段透传格式需与 Claude Code API 严格对齐。

---

## 4. 工作量汇总

| AC | 优先级 | design | dev | test | 合计（天） |
|---|---|---|---|---|---|
| AC-01 DAG scheduler | P0 | 0.5 | 1 | 0.5~1 | **2~2.5** |
| AC-02 artifact dispatcher | P0 | 0.3 | 0.5~1 | 0.5 | **1.3~1.8** |
| AC-03 approval 闭环（a+b+c）| P0 | 0.5 | 2~3 | 0.5~1 | **3~4.5** |
| AC-04 AI 节点完成契约 | P1 | 0.5 | 1~1.5 | 0.5~1 | **2~3** |
| AC-05 path-lock 三件套 | P1 | 0.5 | 1 | 0.5~1 | **2~2.5** |
| AC-06 status doctor 增强 | P1 | 0.5 | 0.7~1 | 0.5~1 | **1.7~2.5** |
| AC-07 loop until_bash | P2 | 0.3 | 0.7 | 0.3~0.5 | **1.3~1.5** |
| AC-08 sub_workflow 回填 | P2 | 0.3 | 1~1.5 | 0.5~0.7 | **1.8~2.5** |
| AC-09 fuzzy + list --json | P2 | 0.2 | 0.5~0.7 | 0.3 | **1~1.2** |
| AC-10 运行参数白名单 | P2 | 0.2 | 0.7~1 | 0.3 | **1.2~1.5** |

**P0 小计**：6.3~8.8 天 | **P1 小计**：5.7~8 天 | **P2 小计**：5.3~6.7 天

**总计：17.3~23.5 天**（中位约 20 天）

不确定度来源：AC-03b on_reject 语义确认（±1 天）、AC-08 sub_workflow 轮询策略（±1 天）。

**关键路径**：`AC-01 DAG scheduler → AC-02 artifact dispatcher e2e → AC-03 approval 闭环`（P0 三件串行，约 6~9 天）→ P1 三件并行可展开。

---

## 5. 风险量化

| 编号 | 类别 | 描述 | 可能性 | 影响 | 缓解策略 |
|---|---|---|---|---|---|
| R-01 | tech | DAG scheduler 切换无 feature flag，旧 yaml 退化兼容（仅 `next` 字段）覆盖不足导致所有已有 yaml 跑失败 | medium | high | development 阶段强制对 standard-8phase / code-review-embedded / 含 sub_workflow 的 yaml 三类做全量回归（来源：requirements/REQ-2026-011/plan.md:39）|
| R-02 | security | approval/reject 改动（追加写 node_completed/node_failed）必须保持 isatty 校验（来源：scripts/lib/workflow_reject.py:39）和 D-006 hook 拦截不减弱；改动在 tty 校验通过后执行 | low | critical | 改动限定在写事件逻辑中，不触碰入口 isatty 校验；补 CLI tty 校验测试 |
| R-03 | tech | `node_ready` / `awaiting_claude_action` 新事件/状态未同步 `VALID_EVENT_TYPES`（来源：scripts/lib/run_state.py:54）、`RunState.rebuild`（来源：scripts/lib/run_state.py:133）、`DispatchOutcome`（来源：scripts/lib/workflow_dispatcher.py:37）三处，append_event 会抛 WorkflowError | medium | high | AC-04 实施时以三处同步更新为 checklist 项，PR 合入前回归验证 |
| R-04 | tech | on_reject 运行时语义（重试同节点 vs 跳转独立节点）未在 yaml schema 层明确，AC-03b 实现可能与真实使用意图偏差 | high | medium | detail-design 阶段优先对齐 on_reject 语义；必要时补 loader schema `on_reject.node` 字段校验 |
| R-05 | ops | path-lock pid 复用极小概率误清新进程的锁 | low | low | 锁文件写 pid + created_at 双字段校验（来源：requirements/REQ-2026-011/plan.md:77）；detail-design 输出误清概率上界分析 |

---

## 待澄清清单

**本报告关闭（无需用户决策或延期）**：

- ✅ **D-01 artifact dispatcher 复用入口**：预研结论为复用 `run_artifact_checks()`（来源：scripts/lib/run_artifact_checks.py:145），detail-design 可直接使用。
- ✅ **D-02 approval attempt 默认值**：yaml schema 层已强制 `max_attempts` 必填（来源：scripts/lib/workflow_loader.py:400），引擎侧无需维护默认值，每个 approval 节点自带。

**⏳ 延期 detail-design**：

- ⏳ **D-03 stale 阈值默认 N 分钟**（来源：requirements/REQ-2026-011/artifacts/requirement.md:165）：建议 30 分钟（依据见 §3.6），detail-design 阶段根据真实节点执行时长统计后最终确认（inline 标记见 §3.6）。

**新发现（用户决策类）**：

- **Q-01 on_reject 运行时语义**：yaml schema 无 `on_reject.node` 字段（来源：scripts/lib/workflow_loader.py:400），实际 yaml 示例（来源：.claude/workflows/requirement/standard-8phase.yaml:156）`on_reject.prompt` 是"给 AI 的修订指引"。选项 A（推荐）：reject 后重试同 approval 节点，以 `on_reject.prompt` 为修订上下文；选项 B：补 `on_reject.node` 字段，reject 后跳到指定修订节点；选项 C：整体语义定义作为 detail-design 第一个设计决策。
- **Q-02 D-02 关闭确认**：yaml 层 `max_attempts` 必填，引擎侧无需维护默认值——此结论是否同意？若同意则 D-02 关闭。
- **Q-03 save_node_result.py 是否需要 D-006 hook 拦截**：建议不拦截（主 Claude Code 合法调用场景），CLI 内部以 state=`awaiting_claude_action` 校验兜底，非此状态 exit 1——是否同意此方案？
- **Q-04 heartbeat 事件写入策略**：选项 A（建议）：每次 `dispatch_node()` 前写新 `heartbeat` 事件类型；选项 B：不新增事件，从 `last_event_ts` 推算活动时间（零成本，粒度粗）。
- **Q-05 stale 检测基准**（与 Q-04 联动）：基于 `heartbeat` 事件 ts 还是 `last_event_ts`？选 A 则 heartbeat 事件为主依据，粒度细；选 B 则 last_event_ts 为主依据，可直接用现有 `RunState.last_event_ts` 字段（来源：scripts/lib/run_state.py:127）。
