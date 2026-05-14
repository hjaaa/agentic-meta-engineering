# REQ-2026-011 · workflow runtime DAG 调度与节点 dispatcher 补全（参考 Archon 设计）

## 目标

把 `artifacts/research.md` 中相对 Archon 识别出的 P0/P1/P2 工作流引擎差距落成可执行需求，让本项目的 standard-8phase yaml 等真实 workflow 能基于 `depends_on` DAG 完整闭环运行；最终输出沉淀为 `context/team/engineering-spec/specs/2026-05-13-workflow-runtime-dag-completion.md`。

## 范围

- 包含：
  - DAG ready-node scheduler 重构（runtime 改从 `workflow_loader.py` 的 depends_on 拓扑出发推进，弱化 `current_node.next` 主路径）
  - `artifact` 节点 dispatcher 补齐（loader 已合法但 dispatcher 缺分支）
  - approval 闭环修复（approve 后关闭节点并推进；reject 走 `on_reject` 路径 + attempt 上限；保留 hook 阻断 AI 自动调用）
  - AI 节点完成契约明确化（`skill/prompt/agent` 增 `node_ready` / `awaiting_claude_action`，禁止"未真执行就写 node_completed"）
  - active-run / path-lock（轻量 jsonl 路径，借鉴 Archon path-lock 思路，不引入 DB）
  - `/workflow:status --verbose` doctor 增强 + heartbeat / stale 检测
  - spec 文档 `context/team/engineering-spec/specs/2026-05-13-workflow-runtime-dag-completion.md` 产出
- 不包含：
  - 多 provider / Provider model 体系（Archon 平台化能力，本项目坚持 Claude Code 本地路径）
  - DB 状态存储（保留 jsonl 事件流，不引入 SQLite / Postgres）
  - AI loop / interactive gate / session resume 的"AI 智能循环"（先做 P0 确定性 loop，AI loop 留给 P2 后续需求）
  - Archon-style AI router（保留关键词 launcher + fuzzy，不引入 AI 路由）
  - 已在 REQ-2026-010 落地的 main loop 与 bootstrap 完整化（边界划分在 definition 阶段最终确认）

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | |
| tech-research | |
| outline-design | |
| detail-design | |
| task-planning | |
| development | |
| testing | |

## 风险

- 风险 1：与 REQ-2026-010 范围高度重叠 —— 在 definition 阶段必须精确划分增量 vs 已落地，避免重做 main loop / bootstrap dispatcher 相关工作
- 风险 2：DAG 调度器重构是 runtime 主路径变更 —— 不引 feature flag（见 D-004），依赖 `depends_on_explicit=False` 退化兼容路径（见 D-006）+ 全量回归 standard-8phase / code-review-embedded / sub_workflow 三类 YAML 兜底
- 风险 3：approval 闭环涉及人类卡点 + Hook 防护，回归覆盖不足会出"AI 自动 approve 绕过"严重事故 —— 必须保留 D-006 hook 拦截基线，并补 CLI tty 校验测试
- 风险 4：path-lock 在 macOS / Linux 文件锁语义差异 —— 必须显式选定 `fcntl.LOCK_EX`（与既有 jsonl 写一致）而非 flock(2)，避免跨平台不兼容

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 AC-04 AI 节点完成回写接口选 `scripts/lib/save_node_result.py`

- **Context**：AC-04 把"dispatcher 写 node_ready"与"主 Claude Code 真实执行后写 node_completed"分离，需要稳定 CLI 入口供主 Claude Code 调用。候选：A 新建独立模块 / B 扩展 `save_review.py` 子命令 / C 仅内部函数不暴露 CLI。来源：artifacts/requirement.md:69 / artifacts/requirement.md:137。
- **Decision**：选 A，新建 `scripts/lib/save_node_result.py`，与 `save_review.py` 平级独立模块；CLI 形式 `python3 scripts/lib/save_node_result.py --run=<id> --node=<id> --output=<json>`；不复用 `save_review.py`。
- **Consequences**：
  - + 职责单一，CLI 入口清晰，不污染 review 链；与 D-006 hook 拦截规则同模板复用。
  - + 主 Claude Code 显式调用，对应 jsonl 的 node_ready→node_completed 两阶段事件可追溯。
  - − 与 `save_review.py` 有少量 schema 校验代码重复；detail-design 阶段需评估是否抽公共 helper。
- **时间**：2026-05-13 09:08:39

### D-002 `/workflow:status --verbose` 输出格式选树形文本

- **Context**：AC-06 doctor 需输出 ready / running / blocked / paused 节点 + 阻塞原因。候选：A 树形文本 / B JSON / C 表格 / D 树形 + `--json` flag。现有 `/workflow:status` 父子 run 已为树形（来源：scripts/lib/workflow_status.py）。
- **Decision**：选 A，沿用现有树形文本风格；本期不引 `--json` flag，外部脚本消费走 AC-09 的 `workflow list --json`。
- **Consequences**：
  - + 与现有 status 风格一致，父子 run 嵌套自然；实现成本低。
  - + 给人类排障最直观，doctor 输出可直接贴对话。
  - − 外部脚本若需结构化 status，需后续需求新增 `--json`；本期不预留 schema。
- **时间**：2026-05-13 09:08:39

### D-003 path-lock 死亡兜底选三件套（pid 文件 + atexit + 失活 pid 自动清理）

- **Context**：AC-05 path-lock 需应对 kill -9 / power loss 等意外退出残留锁文件。候选：A 三件套 / B 仅 atexit / C 三件套 + mtime 超时。Archon `path-lock` 使用 pid + heartbeat 模型（来源：artifacts/research.md:39）。
- **Decision**：选 A 三件套——正常退出由 atexit 删锁；残留锁文件由下次取锁时检测 pid 是否存活，pid 不存在视为 stale 自动清理；**不引入** mtime 超时（避免"时间窗口判定"模糊性）。锁文件同时写入 pid + created_at，二者均参与校验以缓解 pid 复用误清。
- **Consequences**：
  - + 鲁棒，覆盖 99% 残锁场景；不依赖 heartbeat 超时阈值（heartbeat 仅供 doctor 诊断，不参与锁判定）。
  - + 跨平台一致（fcntl.LOCK_EX 在 macOS / Linux 行为一致，见 plan.md 风险 4）。
  - − pid 复用极小概率下可能误清新锁，靠 created_at 二次校验缓解；detail-design 阶段需输出"误清概率上界"分析。
- **时间**：2026-05-13 09:08:39

### D-004 DAG scheduler 重构不引入 feature flag

- **Context**：plan.md 风险 2 原文要求"DAG 调度器 feature-flag 化 + 全量回归"。但兼容路径已存在：`depends_on` 为空时退化为 `next` 链表（来源：artifacts/requirement.md:89 / AC-01）；双跑期会带来清理成本。候选：A 引入 env 双跑期 / B 不引入靠 `next` 退化 / C meta.yaml per-run 开关。
- **Decision**：选 B 不引入 feature flag；DAG 调度器一次性切换，配套全量回归 `standard-8phase.yaml` / `code-review-embedded.yaml` / 含 `sub_workflow` 的 yaml 三类。**Side effect**：plan.md 风险 2 同步修订为"不引 flag，依赖 next 退化兼容 + 全量回归兜底"（本次编辑已落地）。
- **Consequences**：
  - + 避免双跑期长期遗留 + 后续 flag 清理工作（与项目"轻量"定位一致）。
  - + `next` 退化路径已是合法兼容路径，覆盖既有简单 yaml 不需要重写。
  - − 一次性切换无灰度回退；必须靠回归测试覆盖度兜底，development 阶段 PR 合入前需跑通三类 yaml e2e。
- **时间**：2026-05-13 09:08:39

### D-005 features.json 增 `priority: P0|P1|P2` 字段

- **Context**：本需求 AC-01~10 分 P0/P1/P2 三档（来源：artifacts/requirement.md:100-109），task-planning 阶段需要按档位分组拆 task。features-schema.yaml 当前未含 priority 字段。候选：A 加 `priority: P0|P1|P2` / B 不加只看 AC 表 / C 加 `tier` 中性命名。
- **Decision**：选 A 加 `priority: P0|P1|P2` 字段；task-planning 按 priority 分组生成任务；detail-design 阶段同步扩展 `context/team/engineering-spec/features-schema.yaml` 允许 priority 枚举字段，相应 GATE-FEATURES-SCHEMA 跟着 schema 更新。
- **Consequences**：
  - + 与 issue tracker（Linear / Jira）priority 语义相通，跨团队对齐成本低。
  - + 配合 requirement.md 降级条款，P2（AC-07~10）成本失控时可整组降级为后续需求，不阻塞 P0+P1。
  - − features-schema.yaml 改动需 schema 测兜底（detail-design 阶段同步出 schema diff），并兼容历史 features.json 无 priority 的情况（必填 / 选填规则需 detail-design 定）。
- **时间**：2026-05-13 09:08:39

### D-006 DAG 兼容退化判定依据选 `depends_on_explicit` 标记位 + 同层 ready 串行派发

- **Context**：四轮对抗审阅指出原"`depends_on==[]` 时退化为 next"判定与 loader 现状冲突——`workflow_loader._expand_implicit_depends_on` 会给缺省节点自动补 `[prev_id]`（来源：scripts/lib/workflow_loader.py:475），导致加载后 `depends_on` 永远非空，兼容路径永不命中。同时 `code-review-embedded.yaml` 8 个 checker 设计为同层 ready，需明确本期是识别+串行 / 识别+并发 / 返回给 Claude Code 分批。候选 1：A 加载后判定 / B 在 loader 加 `depends_on_explicit: bool` 标记位；候选 2：a 识别+串行 / b 识别+并发（`RunState.current_node` 集合化）/ c 返回给 Claude Code。来源：artifacts/requirement.md:89 + AC-01 + 决策记录"兼容退化判定依据" + "同层 ready 节点本期执行策略"。
- **Decision**：兼容判定选 B（loader `_expand_implicit_depends_on` 内补 `depends_on_explicit: bool`，缺省 = False，scheduler 据此区分显式 DAG / 隐式链）；同层 ready 选 a（识别 + 按 yaml 出现顺序串行派发，保 `RunState` 单 `current_node` 模型；事件顺序确定可复现）；并发派发列入 follow-up 需求 D-04，本期不做。
- **Consequences**：
  - + 最小侵入：loader 标记位保留原始语义，scheduler 据此切两条路径，不破坏既有简单 yaml。
  - + 串行派发保持 RunState 单值不变，与 REQ-2026-010 main loop 兼容，e2e 行为确定。
  - − code-review-embedded.yaml 8 checker 本期跑 8 次串行派发，单次审查 wall-clock 偏长；并发能力需后续需求覆盖（D-04 follow-up）。
- **时间**：2026-05-14 08:36:53

### D-007 approval reject 走 inline `approval_repair` 事件流，复用 `awaiting_claude_action` 状态

- **Context**：四轮对抗审阅指出"reject 跳到 on_reject 节点"语义与真实 yaml 不符——`on_reject` 在真实 yaml 是 `approval.on_reject.prompt` inline 子结构（来源：.claude/workflows/requirement/standard-8phase.yaml:156），不是独立 DAG node；若直接把 approval 节点写 `node_failed`，DAG scheduler 会把下游 permanently blocked 或提前触发失败矩阵 retry。同时 approval_repair 中间态需选状态归属：A 复用 `awaiting_claude_action` / B 新增 `approval_repairing` / C 修订期间仍保持 `approval_pending`。来源：artifacts/requirement.md AC-03 + 决策记录"on_reject 事件流模型" + "approval_repair 中间态归属"。
- **Decision**：事件流选 inline synthetic repair：reject CLI 原子写 `approval_rejected + approval_repair_started(attempt=N)` 并把状态机切到 `awaiting_claude_action`（复用 AC-04 同款，不引第二个 awaiting 状态）→ 主 Claude 执行 inline `approval.on_reject.prompt` → 调 `save_node_result.py --kind=approval_repair` 写 `approval_repair_completed` → 状态回 `approval_pending` 等待下一次 approve/reject；达 `max_attempts`（yaml `approval.on_reject.max_attempts` override，默认 N=3，D-02 待 detail-design 定稿）才 `node_failed + workflow_failed` reason=`approval_attempts_exhausted`。
- **Consequences**：
  - + 事件流与 yaml 真实结构一致，attempts 计数与 yaml `max_attempts` 同源。
  - + 状态机不膨胀：`awaiting_claude_action` 同时承载 skill/prompt/agent 完成等待 与 approval repair 等待，`save_node_result --kind=skill_result|approval_repair` 子模式区分写入事件名。
  - + 保持 D-006 hook 拦截基线不变：reject CLI 仍走 tty fail-closed，AI 无法自动 reject。
  - − 实施细节：`save_node_result.py` 必须强制校验 RunState.state == `awaiting_claude_action`，否则给 AI agent 留绕过口；fail-closed 校验需 unit 测覆盖。
- **时间**：2026-05-14 08:46:41

### D-008 artifact / dispatcher 事件写入职责分工（外层写 started/failed，handler 只写 completed）

- **Context**：四轮对抗审阅指出 AC-02 原写法"`_dispatch_artifact_node` 写 node_started + node_completed + node_failed"会与外层 `dispatch_node` 双写 `node_started`——外层 dispatcher 进入即写 node_started（来源：scripts/lib/workflow_dispatcher.py:128）+ 异常分支统一转 `node_failed`。同时 `awaiting_claude_action` 状态下 `/workflow:continue` 行为未定义，可能引发重复派发。候选 1：A 外层 + handler 双写 / B 外层负责 started/failed，handler 仅 completed；候选 2：continue 在 awaiting 下 A fail-closed / B 只读不派发 / C 自动重派发。来源：artifacts/requirement.md AC-02 + AC-04b 决策记录"awaiting_claude_action 下 continue 语义"。
- **Decision**：事件写入分工选 B（外层 `dispatch_node` 进入即写 `node_started` + 异常 try/except 统一转 `node_failed`；所有 handler 包括 `_dispatch_artifact_node` 仅在 success path 写自己的 outcome 事件 如 `node_completed`/`node_ready`，禁止重复写 started）；continue 在 awaiting 下选 B（识别 awaiting → print `INFO: node <id> awaiting external save_node_result (kind=skill_result|approval_repair), no dispatch` → return 0；不写新事件、不推进 ready 集；保留 idempotent 语义）。
- **Consequences**：
  - + jsonl 中每节点 node_started/node_completed 各 1 条，事件成对，RunState.rebuild 计数不偏。
  - + continue 命令保持 idempotent，用户用 continue 试探状态不会被误拦或污染 jsonl。
  - + handler 职责单一，新增节点类型只需写 success path，failure 路径由外层兜底，新人理解成本低。
  - − 既有 dispatcher 单元测试需补"handler 不写 started"的负向断言（detail-design 阶段补 e2e fixture 兜底）。
- **时间**：2026-05-14 08:46:41
