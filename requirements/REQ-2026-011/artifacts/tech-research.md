---
id: REQ-2026-011
phase: tech-research
created_at: 2026-05-14 08:59:51
prev_research_rolled_back: requirements/REQ-2026-011/artifacts/.rollback-20260513-112537/tech-research.md
---

# REQ-2026-011 · 技术预研（第 2 轮，基于四轮对抗审阅修订版 requirement.md）

## 可行性结论

**feasibility: feasible**

P0 三件（DAG scheduler / artifact dispatcher / approval 闭环含 on_reject inline repair）在现有代码库内有明确改造锚点，无新技术依赖，无新第三方库，无 DB 改动。P1 三件（AI 节点完成契约 / path-lock / status doctor）工作量确定性高；P2 四件（loop until_bash / sub_workflow 回填 / fuzzy routing / Claude 运行参数白名单）复杂度可接受，已有 AC-07~10 降级弹性条款兜底。

关键可行性证据：

- `topological_layers()` 已实现完整 Kahn 拓扑排序（来源：scripts/lib/topological_sort.py:25），DAG scheduler 是直接调用而非从零实现。
- `run_artifact_checks(spec, cwd)` 已覆盖 5 类校验（来源：scripts/lib/run_artifact_checks.py:145），`_dispatch_artifact_node` 是 1 个 if/elif 分支 + 1 个函数封装。
- `workflow_approve.py` 的修改锚点清晰：当前写 `approval_approved` 后直接 return（来源：scripts/lib/workflow_approve.py:64），追加 `node_completed` 约 10 行。
- `workflow_reject.py` 当前仅写 `approval_rejected` + 打印 "on_reject 路径由 main loop 处理"（来源：scripts/lib/workflow_reject.py:82），on_reject inline repair 事件流改造量确定。
- `VALID_EVENT_TYPES` / `RunState.rebuild` / `DispatchOutcome` 三处扩展点位置明确（来源：scripts/lib/run_state.py:54）（来源：scripts/lib/run_state.py:133）（来源：scripts/lib/workflow_dispatcher.py:37）；当前无任何 `awaiting_claude_action` / `node_ready` / `approval_repair_*` 相关代码（Grep 确认），扩展无历史包袱。

唯一值得重视的约束：`DispatchOutcome` Literal 枚举当前仅 7 项（来源：scripts/lib/workflow_dispatcher.py:37），`awaiting_claude_action` 作为第 8 项需同步扩展所有消费点；`CMD_ALLOWED_STATES` 的 `continue` 当前不含 `awaiting_claude_action`（来源：scripts/lib/workflow_state_validator.py:31），AC-04b 的"只读 continue"语义需在多个函数内联动，是本需求集成度最高的改造点。

## 风险识别

### 技术风险

**R-T01：DAG scheduler 主路径切换无 feature flag，退化兼容判定位置新增但尚未实现**

- severity: high
- description: `_expand_implicit_depends_on` 当前在所有缺省节点上写入 `[prev_id]`（来源：scripts/lib/workflow_loader.py:482），加载后 `depends_on` 永远非空，原本用 `depends_on==[]` 做退化判断的逻辑实际永不触发。AC-01 要求在该函数内补 `depends_on_explicit: bool` 标记位（来源：requirements/REQ-2026-011/artifacts/requirement.md:89），但该标记位本次需同时被 scheduler 新路径和退化路径双侧正确消费；任何一侧遗漏都会导致仅含 `next` 字段的历史 yaml 全部失败跑不通。另外 `_finalize_after_rebuild_if_last_topology_node`（来源：scripts/lib/workflow_continue.py:341）末节点判定当前用 `_next_node(last_node, None) is None`，DAG 切换后 DAG 末节点不一定有 `next` 字段，此函数需同步适配否则 `workflow_completed` 可能不写。
- likelihood: medium
- mitigation: AC-01 e2e 要求三路径全覆盖（depends_on yaml / next-only yaml / code-review-embedded 8 checker 串行），实施时以 `depends_on_explicit` 标记位添加 + `_finalize_after_rebuild_if_last_topology_node` 适配为同一 commit，PR 前强制跑三路径 e2e。

**R-T02：`node_ready` / `approval_repair_started` / `approval_repair_completed` 三个新事件需在 VALID_EVENT_TYPES / RunState.rebuild / DispatchOutcome 三处全部同步**

- severity: high
- description: `append_event` 在 `VALID_EVENT_TYPES` 白名单中找不到事件类型时直接抛 `WorkflowError`（来源：scripts/lib/run_state.py:299）；`read_events` 遇到非白名单类型则跳过并写 warning（来源：scripts/lib/run_state.py:276）。若任意一个新事件类型漏加白名单，写入时静默失败或抛异常；若 `RunState.rebuild` 漏处理 `approval_repair_started` 事件的 state 映射，状态机不会切到 `awaiting_claude_action`，后续 `save_node_result.py` 的 fail-closed 校验会拒绝合法调用。当前三处均无任何新事件的处理代码（Grep 确认）。
- likelihood: medium
- mitigation: AC-04b 实施时以三处同步更新为强制 checklist 项（加 PR description 模板）；unit test 对每个新事件类型的 `VALID_EVENT_TYPES` 成员资格 + `RunState.rebuild` 映射结果各写一条断言，断言先于实现写（TDD）。

**R-T03：on_reject inline repair 事件流中 `approval_repair_started` 是 synthetic 事件，RunState.rebuild 需正确处理 attempts 计数**

- severity: medium
- description: `workflow_reject.py` 需在一次 reject CLI 调用内**原子**写两条事件：`approval_rejected` + `approval_repair_started(attempt=N)`（来源：requirements/REQ-2026-011/artifacts/requirement.md:59）。"原子"在现有 jsonl 追加模型下意味着两次 `append_event` 顺序调用，无原子性保证——进程在两条写入之间崩溃时，jsonl 只有 `approval_rejected` 而无 `approval_repair_started`，rebuild 后 state 仍为 `running`（当前 `approval_rejected` handler 把 state 置 running，来源：scripts/lib/run_state.py:204），不会进入 `awaiting_claude_action`，下次 continue 可能重派 approval 节点而非等待修订。attempt 计数同样需要从 jsonl 历史事件中统计 `approval_rejected` 次数，而非独立计数器字段，边界判断需精确。
- likelihood: medium
- mitigation: `workflow_reject.py` 两条事件写入用 try/except 包裹，第一条失败则中止；两条都写成功后 print 成功信息。RunState.rebuild 中 `approval_rejected` 处理改为：state 切 `running` 仅在无后续 `approval_repair_started` 时；有 `approval_repair_started` 则继续处理到 `awaiting_claude_action`；实施前写 "两条中间 crash" 场景的 unit test 验证 rebuild 行为。

**R-T04：path-lock pid 复用 + macOS fcntl 语义**

- severity: low
- description: pid 复用在极小概率下（旧进程退出、pid 被新进程复用、在 created_at 二次校验窗口内触发）可能误清新进程的锁，导致两个 continue 进程并发写 jsonl。`fcntl.flock(LOCK_EX|LOCK_NB)` 在 macOS Darwin 25.4 为 BSD flock 语义（来源：requirements/REQ-2026-011/artifacts/.rollback-20260513-112537/tech-research.md:140），与 Linux 行为一致。pid 文件 + created_at 二次校验是 AC-05 已确认的三件套一部分（来源：requirements/REQ-2026-011/artifacts/requirement.md:92）。
- likelihood: low
- mitigation: pid 复用概率低（macOS 系统 pid 值域 ≥ 99999，回绕时间长）；created_at 二次校验将误清窗口缩到毫秒级；并发测试覆盖 "另一进程 ≤ 100ms 内启动 + 报错退出且 output 含 pid" 场景（AC-05 e2e 要求）。

### 集成风险

**R-I01：`save_node_result.py` 新模块的 D-006 hook 拦截边界**

- severity: medium
- description: `save_node_result.py` 与 `workflow_approve.py` / `workflow_reject.py` 的关键差异在于：前者允许主 Claude Code 调用（AI 节点执行完成后回写），后者必须 tty 拦截。D-006 hook 当前拦截列表仅包含 approve/reject（来源：context/team/ai-collaboration.md:38）。若 `save_node_result.py` 误被加入拦截列表，AI 节点无法完成写入；若完全不拦截，state 校验（`awaiting_claude_action` fail-closed）是唯一防止滥用的机制。requirement.md 已确认"允许 AI 调用 + CLI 内部 state 校验兜底"（来源：requirements/REQ-2026-011/artifacts/requirement.md:103），但 hook 层 `.claude/hooks/pre-tool-use-guard.sh` 需要明确配置排除 `save_node_result.py`，防止误加。
- likelihood: low
- mitigation: AC-04b 实施时检查 `.claude/hooks/pre-tool-use-guard.sh` 当前拦截列表（Grep 确认范围），明确 `save_node_result.py` 不在拦截范围内，并在 PR description 注明；`save_node_result.py` 内部增加 `state != awaiting_claude_action` 时 `exit 2` 的 fail-closed 作为唯一防线。

**R-I02：`_dispatch_artifact_node` 的 `node_started` 不重复写保证**

- severity: medium
- description: requirement.md AC-02 明确：外层 `dispatch_node` 已统一写 `node_started`（来源：scripts/lib/workflow_dispatcher.py:128），handler 只负责 success path 写 `node_completed`，不重复写 `node_started`（来源：requirements/REQ-2026-011/artifacts/requirement.md:101）。目前 `_dispatch_bash_node` 也遵循此约定，bash 节点自己只写 `node_completed/node_failed`（来源：scripts/lib/workflow_dispatcher.py:322）。`_dispatch_artifact_node` 需严格复用 bash 节点的模式——failure 由外层 try/except 转 `node_failed`，success 由 handler 写 `node_completed`。若实现时混淆了事件写入职责，会出现 `node_started` 双写或 `node_failed` 双写。
- likelihood: low
- mitigation: `_dispatch_artifact_node` 函数体内禁止调用 `node_started`；code review 强制 diff `node_started` 只在外层 `dispatch_node` 调用路径出现一次。

**R-I03：standard-8phase.yaml 引用的不存在脚本 `check_meta_schema.py`**

- severity: medium
- description: `.claude/workflows/requirement/standard-8phase.yaml:57` 的 `schema_check.script` 字段引用 `scripts/lib/check_meta_schema.py`，该文件在仓库内不存在（Grep 确认 `check_meta_schema` 出现在 yaml 中但没有对应的 `.py` 文件）。AC-02 要求改为 `scripts/lib/check_meta.py`（来源：requirements/REQ-2026-011/artifacts/requirement.md:101）。若 artifact dispatcher 实现后直接执行 `schema_check`，会触发 `FileNotFoundError`，`bootstrap-validate` 节点必然 `node_failed`，AC-01 + AC-02 的 e2e 全部失败。这是一个先决条件修复，必须在 `_dispatch_artifact_node` 实现之前或同 commit 完成。
- likelihood: high（当前代码确定存在此问题）
- mitigation: AC-02 已将此列为附带修正任务；实施顺序：先修 yaml（1 行 diff），验证 `check_meta.py` 存在后再实现 dispatcher，防止先写 dispatcher 后被 yaml bug 阻断 e2e。

### 性能风险

**R-P01：`_ready_nodes` 每次循环调用 `topological_layers` 的计算开销**

- severity: low
- description: AC-01 的 DAG scheduler 需在每次循环迭代时调用 `_ready_nodes` 重新计算 ready 集合。`topological_layers` 当前实现是完整 Kahn 算法（来源：scripts/lib/topological_sort.py:25），时间复杂度 O(V+E)，50 节点 yaml 约 5~10ms。requirement.md 已确认 DAG ready-node 计算软约束 ≤ 50ms（来源：requirements/REQ-2026-011/artifacts/requirement.md:85），不进 CI 增量回归，仅 micro-benchmark 单测覆盖。
- likelihood: low
- mitigation: 实施时增量计算 ready 集合（传入已完成节点集，过滤 `node_outputs` 中 state=completed 的节点，不重复计算整个 DAG）；micro-benchmark 写一个 50 节点 yaml 场景，断言 ≤ 50ms，不需进 CI。

### 安全风险

**R-S01：approval/reject isatty 校验在追加写入逻辑后必须保持 fail-closed**

- severity: critical
- description: AC-03a / AC-03b 要求 `workflow_approve.py` 追加写 `node_completed`，`workflow_reject.py` 追加写 `approval_repair_started`。isatty 校验是 `main()` 函数第一道保证（来源：scripts/lib/workflow_approve.py:37）（来源：scripts/lib/workflow_reject.py:39），新增写入逻辑必须在 isatty 校验通过之后执行，不得在函数重构中将写入逻辑提前或绕过 isatty 分支。当前 `check_tty_for_approval` 调用 `sys.exit(2)`（来源：scripts/lib/workflow_state_validator.py:81），无条件终止，无法被绕过，只要不在 isatty 之前插入新写入逻辑即安全。
- likelihood: low（只要不乱序插入代码）
- mitigation: 改动仅追加在 `append_event(approval_approved/rejected)` 之后，不移动 isatty 校验位置；PR review 对 approve/reject 文件 diff 强制确认 `check_tty_for_approval` 仍为函数体第一行。

## 工作量估算

| AC | 优先级 | 代码锚点摘要 | design (天) | dev (天) | test (天) | 合计 (天) |
|---|---|---|---|---|---|---|
| AC-01 DAG ready-node scheduler | P0 | `workflow_continue.py:37` 升级 `_ready_nodes`；`workflow_loader.py:475` 加 `depends_on_explicit`；`_finalize_after_rebuild_if_last_topology_node:341` 适配 | 0.5 | 1.5 | 1.0 | **3.0** |
| AC-02 artifact dispatcher + yaml 修正 | P0 | `workflow_dispatcher.py:153` 插入 elif；新增 `_dispatch_artifact_node`；`standard-8phase.yaml:57` 改脚本路径 | 0.3 | 0.7 | 0.5 | **1.5** |
| AC-03 approval 闭环（a+b+c） | P0 | `workflow_approve.py:64` 追加 `node_completed`；`workflow_reject.py:82` 追加 `approval_repair_started`；`run_state.py` approval_rejected handler 重写；attempt 计数逻辑 | 0.5 | 2.5 | 1.0 | **4.0** |
| AC-04a AI 节点完成契约（派发侧） | P1 | `workflow_dispatcher.py` AI 节点三处改写 `node_ready`；新建 `save_node_result.py`（~120 行） | 0.5 | 1.5 | 0.5 | **2.5** |
| AC-04b 状态机/命令侧同步 | P1 | `run_state.py:54` VALID_EVENT_TYPES 扩展；`run_state.py:133` rebuild 新增 4 事件；`workflow_state_validator.py:31` CMD_ALLOWED_STATES 扩展；`workflow_continue.py` awaiting 下只读逻辑 | 0.5 | 1.0 | 0.5 | **2.0** |
| AC-05 path-lock 三件套 | P1 | 新建 `scripts/lib/workflow_lock.py`（~90 行）；`workflow_continue.py` 入口取锁 | 0.5 | 1.0 | 0.7 | **2.2** |
| AC-06 status doctor 基础 | P1 | `workflow_status.py` `_render_status` 增强；heartbeat 事件新增；三类 stuck 场景 fixture | 0.5 | 1.0 | 0.8 | **2.3** |
| AC-07 loop until_bash | P2 | `workflow_dispatcher.py` `_dispatch_loop_node` 扩展 `until_bash` 分支（~25 行） | 0.3 | 0.7 | 0.5 | **1.5** |
| AC-08 sub_workflow 父子回填 | P2 | `workflow_continue.py` `sub_workflow_pending` 分支扩展（~50 行轮询逻辑） | 0.3 | 1.5 | 0.7 | **2.5** |
| AC-09 fuzzy + workflow list --json | P2 | launcher `difflib.get_close_matches`（~20 行）+ `--json` 输出（~30 行） | 0.2 | 0.5 | 0.3 | **1.0** |
| AC-10 Claude 运行参数白名单 | P2 | `workflow_loader.py` 节点 schema 补字段；dispatcher 透传 | 0.2 | 0.7 | 0.3 | **1.2** |

**P0 小计**：8.5 天 | **P1 小计**：9.0 天 | **P2 小计**：6.2 天

**总计：23.7 天（区间 21~27 天）**

不确定度来源：AC-03b on_reject repair 事件流的 `RunState.rebuild` 改造复杂度（±1 天）；AC-04b `awaiting_claude_action` 下 `continue` 只读语义在主循环多个函数内的联动点确认（±1 天）；AC-08 子 run 轮询策略是否需要 asyncio 或轮询轮次上限（±1 天）。

与前次预研（17.3~23.5 天，中位 20 天）相比，本轮估算高出约 3~4 天，原因见"与前次预研的差异"节。

## 影响模块

以下为 `meta.yaml:affected_modules` 已有模块 + 本轮新增标注：

**已有模块（meta.yaml 已列出）：**

- `scripts/lib/workflow_continue.py`（AC-01：`_ready_nodes` 新增；`_finalize_after_rebuild_if_last_topology_node` 适配；AC-04b：awaiting 下只读 continue 逻辑）
- `scripts/lib/workflow_dispatcher.py`（AC-02：第 8 类 artifact 分支；AC-04a：AI 节点三处改写 node_ready）
- `scripts/lib/workflow_approve.py`（AC-03a：追加 node_completed）
- `scripts/lib/workflow_reject.py`（AC-03b：追加 approval_repair_started；attempt 计数）
- `scripts/lib/workflow_status.py`（AC-06：verbose + heartbeat + stuck 诊断）
- `scripts/lib/run_state.py`（AC-04b：VALID_EVENT_TYPES + rebuild + 新 state 映射）
- `.claude/workflows/requirement/standard-8phase.yaml`（AC-02 附带：check_meta_schema.py → check_meta.py）

**本轮新增（meta.yaml 未列出，需 detail-design 阶段补录）：**

- `scripts/lib/workflow_loader.py`（AC-01：`_expand_implicit_depends_on` 加 `depends_on_explicit` 标记位）
- `scripts/lib/workflow_state_validator.py`（AC-04b：`CMD_ALLOWED_STATES` 加 `awaiting_claude_action`）
- `scripts/lib/run_artifact_checks.py`（AC-02 调用方，接口只读；确认签名 `run_artifact_checks(spec, cwd)` 不变）
- `scripts/lib/save_node_result.py`（AC-04a：新建，~120 行）
- `scripts/lib/workflow_lock.py`（AC-05：新建，~90 行）
- `.claude/hooks/pre-tool-use-guard.sh`（AC-04b / R-I01：确认 save_node_result.py 不在 D-006 拦截列表）

## 与前次预研的差异

**前次预研参考**：`requirements/REQ-2026-011/artifacts/.rollback-20260513-112537/tech-research.md`，feasibility=high，总计 17.3~23.5 天。

**feasibility 评定对比**：前次用 `high` 描述（该报告不使用本轮枚举格式），本轮评定 `feasible`。两者实质一致：均为无阻碍、可直接实施。

**工作量差异：+3~4 天（主要集中在 AC-01 / AC-03 / AC-04）**

1. **AC-01 从 2~2.5 天升至 3.0 天**：requirement.md 四轮对抗审阅新增了"兼容退化判定依据 = `depends_on_explicit` 标记位"（来源：requirements/REQ-2026-011/artifacts/requirement.md:89），这比前次预研的简单 `depends_on==[]` 判断多了 loader 层修改和标记位消费侧的联动点。同时 `_finalize_after_rebuild_if_last_topology_node` 适配（来源：scripts/lib/workflow_continue.py:341）是本轮阅读代码后新发现的改造点，前次预研未覆盖。

2. **AC-03 从 3~4.5 天升至 4.0 天**：前次预研对 on_reject 语义（Q-01）存在高风险不确定项（来源：requirements/REQ-2026-011/artifacts/.rollback-20260513-112537/tech-research.md:94）。requirement.md 修订版已明确 on_reject inline repair 事件流（来源：requirements/REQ-2026-011/artifacts/requirement.md:59）：reject CLI 需原子写两条事件 + 状态切 `awaiting_claude_action`，`save_node_result --kind=approval_repair` 路径需在 RunState.rebuild 中正确映射。语义已确认但改造量比前次预估的"追加 node_failed" 更重（前次 AC-03b 预估 1.5~2.5 天含不确定度，现在实现路径清晰但代码量更大）。

3. **AC-04 拆分为 AC-04a + AC-04b，合计从 2~3 天升至 4.5 天**：前次预研将 AC-04 作为单条估算。requirement.md 对抗审阅后明确了 `continue` 在 `awaiting_claude_action` 下的"只读 idempotent"行为（来源：requirements/REQ-2026-011/artifacts/requirement.md:104），这需要 `workflow_continue.py` 主循环识别 awaiting 状态并分支处理，比前次预估的"新建 save_node_result.py"要多约 1 天联动代码。

**新发现的技术风险（前次预研未包含）**：

- R-I02 dispatcher 不重复写 `node_started` 的职责边界（前次报告 D-01 已关闭但未单独作为风险列出）
- R-I03 `check_meta_schema.py` 不存在（前次预研未 Grep 验证，本轮阅读 yaml 后确认）
- R-T03 on_reject 两条事件写入的非原子性问题（前次预研 Q-01 尚未确定语义，无法评估此风险）

**前次预研 Q-01~Q-05 在修订版 requirement.md 中的关闭状态**：

- Q-01 on_reject 运行时语义：已定为 inline repair 事件流（来源：requirements/REQ-2026-011/artifacts/requirement.md:136）
- Q-02 D-02 max_attempts 默认值：暂定 N=3，detail-design 阶段确认（来源：requirements/REQ-2026-011/artifacts/requirement.md:171）
- Q-03 save_node_result.py D-006 拦截：允许 AI 调用 + state 校验兜底（来源：requirements/REQ-2026-011/artifacts/requirement.md:103）
- Q-04/Q-05 heartbeat 写入策略：每次 `dispatch_node` 前写 heartbeat 事件（来源：requirements/REQ-2026-011/artifacts/requirement.md:106）AC-06 描述

## 待澄清清单

**P0 阻塞（当前阶段切换不阻塞，但 detail-design 开始前需确认）**：

- 无。所有 P0 的技术判断均已有 file:line 锚点，可直接进入 outline-design 阶段。

**P1 detail-design 阶段处理**：

1. **D-02 approval attempt 默认上限 N=3**：当前 requirement.md 暂用 N=3（来源：requirements/REQ-2026-011/artifacts/requirement.md:171），detail-design 阶段确认 yaml `on_reject.max_attempts` override 机制后定稿默认值（yaml schema 已强制 `max_attempts` 必填，引擎侧默认值仅在 yaml 省略时兜底，当前 standard-8phase.yaml 已显式填写 3，来源：.claude/workflows/requirement/standard-8phase.yaml:168）。
2. **D-03 stale 阈值默认 N 分钟**：detail-design 阶段统计真实节点运行时长后定稿（来源：requirements/REQ-2026-011/artifacts/requirement.md:172），候选值 15/30/60 分钟。
3. **heartbeat 事件 vs `last_event_ts`**：AC-06 以"每次 `dispatch_node` 前写 heartbeat 事件"描述（来源：requirements/REQ-2026-011/artifacts/requirement.md:106），但若 heartbeat 作为新 VALID_EVENT_TYPES 成员，需同时补 RunState.rebuild 处理（不映射 state）；detail-design 确认是否用 heartbeat 事件或直接复用 `last_event_ts` 字段（来源：scripts/lib/run_state.py:127）。

**不阻塞本阶段切换**：

4. **D-04 AC-01 同层 ready 并发派发**：本期确定为串行，并发能力拉独立需求（来源：requirements/REQ-2026-011/artifacts/requirement.md:173）。
5. **P2 降级触发条件**：AC-07~10 已有降级弹性条款，若 detail-design 发现成本失控则写 ADR（来源：requirements/REQ-2026-011/artifacts/requirement.md:114）。
6. **`save_node_result.py` 的 `--kind` 校验是否需要独立 schema 文件**：detail-design 阶段按 `save_review.py` 同款模式设计即可，无需新增 schema 文件。
