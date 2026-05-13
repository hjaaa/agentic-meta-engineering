---
id: REQ-2026-011
title: workflow runtime DAG 调度与节点 dispatcher 补全（参考 Archon 设计）
created_at: 2026-05-13T08:45:00+08:00
refs-requirement: true
---

# REQ-2026-011 · workflow runtime DAG 调度与节点 dispatcher 补全（参考 Archon 设计）

## 背景

REQ-2026-009 完成了自定义 workflow 引擎的脚手架与设计、REQ-2026-010 在此基础上落地了 bootstrap 完整化与 main loop 7 类节点派发（来源：requirements/REQ-2026-010/artifacts/requirement.md:1）；但运行时距离"真实 YAML 能完整闭环"仍存在多处可观察到的差距：

- **DAG 推进路径仍是单链**：`workflow_continue._next_node` 只读 `current_node.next`，未消费 loader 已展开的 `depends_on` 拓扑信息（来源：scripts/lib/workflow_continue.py:37）。当 yaml 中节点用 `depends_on` 而非显式 `next` 描述顺序时，引擎实际无法推进。
- **`artifact` 节点缺 dispatcher**：`workflow_dispatcher.dispatch_node` 派发表只覆盖 7 类 agent/skill/prompt/bash/approval/loop/sub_workflow（来源：scripts/lib/workflow_dispatcher.py:110），但 `standard-8phase.yaml` 首节点 `bootstrap-validate` 即 `artifact` 类（来源：requirements/REQ-2026-011/artifacts/research.md:53）；当前命中即 dispatch 异常。
- **approval 闭环未关**：`workflow_approve` 只写 `approval_approved` 并把状态机置回 `running`（来源：scripts/lib/workflow_approve.py:66），未把 approval 节点本身置为 `node_completed` / 未推进下游；`workflow_reject` 同形（来源：scripts/lib/workflow_reject.py:83），其注释明确 `on_reject 路径由 main loop (F-006) 处理`（来源：scripts/lib/workflow_reject.py:95），但 F-006 已合入 REQ-010 而 `on_reject` 跳转未实现。
- **AI 节点完成契约模糊**：`skill / prompt / agent` 节点在 dispatcher 中可能在未真实执行业务的情况下直接写 `node_completed`（来源：requirements/REQ-2026-011/artifacts/research.md:15）；缺乏"等待外部 Claude Code action"的中间态，导致表面绿但实际无产物。
- **无 run-level lock**：requirement 类 run 借助 feature branch 形成天然隔离，但非 requirement 类 run（`workflow:run` 未来扩展点）缺少 active-run / path-lock，重复 `continue` 或并发 hand-edit 同一 checkout 会写坏 jsonl（来源：requirements/REQ-2026-011/artifacts/research.md:39）。
- **status / doctor 能力薄弱**：当前 `/workflow:status` 输出粗粒度，不区分 ready / running / blocked / paused；无 heartbeat / stale 检测，半写 jsonl 或卡在 approval pending 时缺诊断手段 [待用户确认]。

参照 `/Users/richardhuang/open-source/Archon` 的 `packages/workflows/src/dag-executor.ts` Kahn-拓扑层并发执行 + workflow_runs/events 表 + path-lock 设计（来源：requirements/REQ-2026-011/artifacts/research.md:17）（来源：requirements/REQ-2026-011/artifacts/research.md:39），本项目应在**保持 Claude Code 本地、jsonl 轻量、可审计**定位的前提下，定向补齐上述差距，让 `standard-8phase.yaml` / `code-review-embedded.yaml` / 含 `sub_workflow` 的 yaml 能基于 `depends_on` DAG 跑出完整闭环。

需求最终交付物之一是设计留档 `context/team/engineering-spec/specs/2026-05-13-workflow-runtime-dag-completion-design.md`（沿用既有命名 `YYYY-MM-DD-<topic>-design.md`，来源：context/team/engineering-spec/specs/INDEX.md）；spec 文档在阶段 4-5 概要/详细设计阶段产出，不在本 requirement 主体验收标准里。

## 目标

- **主目标**：让基于 `depends_on` DAG 描述的真实 yaml workflow（standard-8phase / code-review-embedded / 含 sub_workflow 的 yaml）通过 `/workflow:run` + `/workflow:continue` 端到端完整闭环跑完，**P0 三件**全部落地并配套 e2e。
- **次要目标**：
  - 明确并实现 AI 节点的完成契约（`node_ready` / `awaiting_claude_action`），消除"未真执行就 node_completed"。
  - 引入轻量 run-level path-lock，覆盖非 requirement 类 run 的并发隔离场景。
  - 强化 `/workflow:status` 输出粒度与 heartbeat / stale 检测，给 doctor 类排障奠基。
  - P2 体验项（loop 两步落地 / subworkflow 完成回填 / 路由 fuzzy / Claude 运行参数白名单）一并落地（已确认 P0+P1+P2 全做）。

## 用户场景

### 场景 1：用 depends_on DAG 描述的 yaml 能跑完首节点

- 角色：需求负责人 / 工作流编排者
- 前置：clean develop 分支 + 一份用 `depends_on` 而非 `next` 描述顺序的 yaml（如 `standard-8phase.yaml`）
- 主流程：
  1. 用户敲 `/workflow:run standard-8phase "<title>"`
  2. 引擎 bootstrap 完成（REQ-010 已落地）
  3. 用户立刻敲 `/workflow:continue`
  4. **引擎从 `depends_on` 拓扑计算首层 ready 节点集**，找到 `bootstrap-validate`（`artifact` 类）
  5. `_dispatch_artifact_node` 校验 `must_exist` 列表 → 写 `node_started` + `node_completed`
  6. 主 loop 推进到第二层 ready 节点
- 期望结果：首节点 PASS；用户在主对话看到 "next: req-input-normalize"；jsonl 完整。

### 场景 2：approval 节点 approve 后真的关闭并推进

- 角色：需求负责人（人类，tty 终端）
- 前置：某 run 已写 `approval_pending` 事件，main loop 已 return
- 主流程：
  1. 用户在 tty 敲 `/workflow:approve`
  2. CLI 校验 tty（fail-closed）、git email、role
  3. 写 `approval_approved` + **写当前 approval 节点的 `node_completed`** + 把 run state 推进
  4. 用户敲 `/workflow:continue`
  5. main loop 派发 approval 节点下游
- 期望结果：approval pending → completed → next node ready，全过程在 jsonl 可追溯。reject 路径同形：`approval_rejected` + 触发 `on_reject` 配置的跳转 / 失败上限。

### 场景 3：AI 节点不假装"完成"

- 角色：主 Claude Code（执行体）
- 前置：DAG 派发到一个 `skill` 节点（例 `requirement-doc-writer`）
- 主流程：
  1. dispatcher 写 `node_started` + `node_ready`（**新事件**），状态机入 `awaiting_claude_action`
  2. main loop **不立即写 `node_completed`**，return
  3. 主 Claude Code 真实执行该 skill 产出 artifact
  4. 主 Claude Code 调用统一保存接口 `scripts/lib/save_node_result.py`（已确认，与 `save_review.py` 平级独立模块）
  5. 保存接口验证产物 + 写 `node_completed`，状态机回 `running`
- 期望结果：jsonl 区分"派发完成"与"执行完成"两个事件；半执行场景可由 doctor 诊断 `awaiting_claude_action` 滞留过久。

### 场景 4：path-lock 阻止并发写坏 jsonl

- 角色：两个并行触发的 `/workflow:continue` 进程
- 前置：同一 run 目录，第二个进程在第一个未完成时启动
- 主流程：
  1. 第一个进程取 `requirements/<id>/.run.lock` `fcntl.LOCK_EX`
  2. 第二个进程取锁失败 → 输出 "another continue is running, pid=N, started_at=T" → exit≠0
- 期望结果：jsonl 不出现交错写；用户得到明确指引。

## 非功能需求

- **性能**（已确认：软约束 + 1 处 micro-benchmark 验证）：
  - DAG ready-node 计算（首层 + 增量）≤ 50ms（节点 ≤ 50 个的 yaml）——软约束，micro-benchmark 单测覆盖即可，不进 CI 增量回归。
  - path-lock 抢占判定 ≤ 100ms——同上软约束。
- **兼容性**（已确认延续 D-007 双轨）：
  - 保留 D-007 双轨期（`runs/<id>/` 与 `requirements/<id>/` 都合法），新增能力沿用 `_resolve_run_dir`（来源：requirements/REQ-2026-010/artifacts/requirement.md）（来源：scripts/lib/workflow_loader.py）。
  - 旧 `current_node.next` 字段保留为兼容路径：仅当 `depends_on` 为空时退化生效（避免破坏已有简单 yaml）。
- **安全/合规**：
  - approval / reject CLI 的 tty 校验 + Hook 拦截 AI 自动调用（来源：context/team/ai-collaboration.md:38）必须保持不变；本期不放松任何 D-006 拦截。
  - path-lock 文件需 `pid 文件 + atexit + 失活 pid 自动清理 stale 锁` 三件套（已确认）：进程死亡时由 atexit 删锁；意外退出（kill -9 / power loss）残留的锁文件由下次取锁时检测 pid 是否存活，pid 不存在则视为 stale 自动清理。

## 范围

### 包含（拟定，待用户确认范围切割）

| AC | 内容 | 验证手段 | 档位 |
|---|---|---|---|
| AC-01 | DAG `depends_on` ready-node scheduler：`_next_node` 升级为 `_ready_nodes`，按 Kahn 拓扑层从已完成事件推算 ready 集；保留 `next` 字段为退化兼容 | e2e：起一个仅用 `depends_on` 的最小 yaml（≥ 5 节点），跑过两层；`code-review-embedded.yaml` 8 个 checker 被识别为同层 ready | P0 |
| AC-02 | `_dispatch_artifact_node` 实现：调用既有 artifact 校验入口（候选 `scripts/lib/check_*.py` [待用户确认]——技术预研阶段对比 check_meta / check_sourcing 等已有脚本后定稿）+ 写 node_started/node_completed/node_failed | e2e：`standard-8phase.yaml` 的 `bootstrap-validate` artifact 节点跑通 | P0 |
| AC-03 | approval 闭环 + on_reject：**AC-03a** approve 后写当前 approval 节点 `node_completed` + 推进下游；**AC-03b** reject 后写 `node_failed` 并跳到 `on_reject` 节点；**AC-03c** attempt 计数（默认上限 N=3 [待用户确认]，可由节点 yaml `on_reject.max_attempts` override），达上限写 `workflow_failed` | e2e：AC-03a pending → approve → next node ready；AC-03b pending → reject → on_reject 节点跑；AC-03c 三次 reject 后 jsonl 末尾出现 `workflow_failed` 事件且 reason=`approval_attempts_exhausted` | P0 |
| AC-04 | AI 节点完成契约：`skill/prompt/agent` dispatcher 写 `node_ready` + 状态机 `awaiting_claude_action`；新增 `scripts/lib/save_node_result.py`（已确认接口路径）由主 Claude Code 调用写 `node_completed` | e2e：派发 skill 节点 → jsonl 含 node_ready → 调 `python3 scripts/lib/save_node_result.py --run=<id> --node=<id> --output=<json>` → 含 node_completed | P1 |
| AC-05 | active-run / path-lock：实锁 `runs/.locks/<run-id>.lock` + requirement 类 symlink `requirements/.locks/<req-id>.lock`（已确认双轨方案）；`fcntl.LOCK_EX` + `pid 文件 + atexit + 失活 pid 自清理` 三件套（已确认）；`/workflow:continue` 启动即取锁 | 并发测试：起两个 continue 子进程，第二个**在第一个写入第一条事件后 ≤ 100ms 内启动**，明确报错退出且输出含 `another continue is running, pid=N` | P1 |
| AC-06 | `/workflow:status --verbose` + doctor 基础：**树形文本输出**（已确认，与现有 status 风格一致），呈现 ready / running / blocked / paused 节点 + 阻塞原因；heartbeat 写入（每 dispatcher 调用前写一次） + stale 检测（> N 分钟未更新提示，N 默认值 [待用户确认]——detail-design 阶段定稿） | e2e（驱动方式细化）：用 pytest fixture 构造 3 类 stuck 场景：(a) 直接写一条 `approval_pending` 事件后 30 分钟前的 heartbeat 时间戳，调 `/workflow:status --verbose` 断言输出含 `stale: heartbeat outdated`；(b) 写一条 `node_started` 但无后续 `node_completed/failed`，断言输出含 `blocked: incomplete dispatch`；(c) 直接 `chmod 000` jsonl 模拟读失败，断言 `status --verbose` 退出码 != 0 且输出含 `error: jsonl unreadable` | P1 |
| AC-07 | loop 两步落地：第一步实现 `until_bash` + `max_iterations` 确定性 loop（AI loop / interactive 留待后续需求） | e2e：构造 `until_bash` loop yaml，跑 3 轮后退出 | P2 |
| AC-08 | sub_workflow 父子完成回填：子 run completed/failed/cancelled 后，父 run 写 `child_*` 事件 + 父节点 `node_completed/node_failed`；尊重 `on_subworkflow_failure` | e2e：父 yaml 含 sub_workflow，子 run 完成后父 run status 显示父节点 completed | P2 |
| AC-09 | 路由 fuzzy + `workflow list --json`：launcher 接 fuzzy 匹配（含模糊词典 / 编辑距离 ≤ 2），`workflow list --json` 输出可被外部脚本消费 | unit：fuzzy 词典 ≥ 10 词 hit；e2e：`workflow list --json` 输出有效 JSON | P2 |
| AC-10 | Claude 运行参数白名单：在 yaml 节点中保守接 `allowed_tools / denied_tools / mcp / skills / agents / idle_timeout / output_format` 字段透传到 Claude Code | schema 测：白名单字段被 loader 校验通过；e2e：派发节点时这些字段传入 Claude Code 调用 | P2 |

> **拆分策略（已确认：单 PR 上线）**：AC-01~10 全部归入同一 PR；commit 内按 P0 / P1 / P2 三组分组，便于 reviewer 分块阅读；不拆 PR-A/B/C。
>
> **降级条款（弹性兜底）**：若 P2（AC-07~10）在实施阶段（detail-design / development）被发现成本失控或外部依赖未就绪，可降级为后续需求 REQ-XXXX，不阻塞 P0+P1 合入；降级触发时需写 ADR D-NNN 记录原因 + 留 follow-up issue。

### 不包含

- **多 provider / provider model 体系**（Archon `provider/model/effort/thinking` 等多 provider 抽象）——本项目坚持 Claude Code 本地，**不引入**。
- **DB 状态存储**（Archon 的 `workflow_runs`/`workflow_events` 表）——保留 jsonl + RunState.rebuild 反扫模型，**不引入** SQLite/Postgres。
- **AI loop / interactive gate / session resume**（智能循环）——P2 仅做确定性 loop，AI loop 留给后续需求。
- **Archon-style AI router**（基于 description 的 AI 路由）——保留关键词 launcher + 新增 fuzzy，**不引入** AI 路由。
- **REQ-2026-010 已完成的工作**：bootstrap 完整化 / 7 类节点 dispatcher 框架 / 模板路径参数化 / 父子 run 路径收敛 / 2 条占位 e2e 替换。**不在本需求重做**。本需求是在 REQ-010 已落地的"框架可用"基础上补**具体语义**：DAG ready-node 推进、`artifact` 第 8 类 dispatcher、approval 节点真正闭环、AI 节点完成契约、`sub_workflow` 完成回填等；不重写 dispatcher 框架本身。
- **`/workflow:next` 命令落地**：F-012 的阶段切换归一化由独立需求处理（来源：CLAUDE.md:23）。
- **历史目录 `runs/` ↔ `requirements/` 物理迁移**：延续 D-007 双轨期（已确认）。

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| DAG 推进路径 | A: 新增 `_ready_nodes` 函数 + 保留 `_next_node` 兼容；B: 直接重写 `_next_node` 为返回集合；C: 引入新 main loop 文件 | **A** | 最小破坏面：现有仅含 `next` 的简单 yaml 自动退化；scripts/lib/workflow_continue.py:37 风格保留 |
| `artifact` dispatcher 复用层 | A: 调用既有 `scripts/lib/check_*.py`；B: 写新 `_dispatch_artifact_node` 内部 must_exist 逻辑 | **A** | 既有 check 脚本已被 hook / CI 复用，避免双实现；artifact 校验语义稳定 |
| approval 节点关闭时机 | A: approve CLI 内一并写 `node_completed`；B: 等下次 continue 由 main loop 关闭 | **A** | 与"approve 是状态机推进事件"语义自然契合；避免 continue 时还得识别"pending → 实际 done"的隐藏状态 |
| AI 节点中间态命名 | `node_ready` / `awaiting_claude_action` vs 新 `node_pending_external` | **node_ready + state=awaiting_claude_action**（用户已确认） | 与现有事件命名 `node_started/completed/failed` 风格一致；状态机已有 paused/approval_pending 等 awaiting 类 |
| path-lock 锁路径 | A: `requirements/.locks/`；B: `runs/.locks/`；C: 仓库根 `.locks/` | **`runs/.locks/` 实锁 + `requirements/.locks/` 软链**（用户已确认） | 与 D-007 双轨保持兼容：实际锁文件在 `runs/.locks/<run-id>.lock`，对 requirement 类 run 自动 symlink 到 `requirements/.locks/<req-id>.lock` |
| PR 拆分 | 单 PR / 拆 3 PR (P0/P1/P2) | **单 PR**（用户已确认） | commit 内按 P0/P1/P2 分组便于 reviewer 阅读；不拆 PR-A/B/C |
| NFR 性能指标硬度 | 硬指标（必测）/ 软约束（探针告警）/ 软约束 + 1 处 micro-benchmark | **软约束 + 1 处 micro-benchmark**（用户已确认） | 本期目标是"能闭环"而非"高性能"；硬指标会扩大测试面；micro-benchmark 单测可控 |
| D-007 双轨延续 | 延续双轨 / 收口到 `runs/` 单轨 | **延续双轨**（用户已确认） | 与 REQ-010 一致；不在本需求做物理迁移 |
| AC-04 AI 节点完成接口 | A 新建独立 `save_node_result.py` / B 扩展 `save_review.py` 子命令 / C 仅内部函数不暴露 CLI | **A 新建独立模块**（用户已确认） | 与 `save_review.py` 平级，职责单一；主 Claude Code 有明确 CLI 入口 |
| `/workflow:status --verbose` 输出格式 | A 树形文本 / B JSON / C 表格 / D 树形 + `--json` flag | **A 树形文本**（用户已确认） | 与现有 status 风格一致，父子 run 自然嵌套；JSON 后续按需新增 |
| path-lock 死亡兜底 | A 三件套 / B 仅 atexit / C 三件套 + mtime 超时 | **A 三件套**（用户已确认） | robust：意外退出残锁可由下次取锁的 pid 检测自动清理 |
| DAG scheduler feature flag | A 引入 env 双跑期 / B 不引入靠 `next` 退化 / C meta.yaml per-run 开关 | **B 不引入**（用户已确认） | 已有兼容路径（`depends_on` 为空 → 退化 `next`），加 flag 反增清理成本 |
| 档位字段是否进 features.json | A 加 `priority: P0\|P1\|P2` / B 不加只看 AC 表 / C 加 `tier` 中性命名 | **A 加 `priority` 字段**（用户已确认） | task-planning 拆 task 时按 priority 分组；与 issue tracker 语义相通 |

## 待澄清清单

> 前缀 ✅ 表示用户已确认；前缀 ⏳ 表示留给指定下游阶段定稿（不阻塞 definition → tech-research 切换）。

1. ✅ **C-01 范围切割**：P0+P1+P2 全做（AC-01~10 共 10 条全部纳入本需求）。
2. ✅ **C-03 approval 关闭时机**：A 方案 = approve CLI 内一并写 `node_completed`。
3. ✅ **C-04 AI 中间态命名**：`node_ready + state=awaiting_claude_action`。
4. ✅ **C-05 path-lock 锁路径**：B + 软链 A（实锁 `runs/.locks/`，requirement 类 symlink 到 `requirements/.locks/`）。
5. ✅ **C-06 PR 拆分**：单 PR，commit 内按 P0/P1/P2 分组。
6. ✅ **C-07 NFR 性能硬度**：软约束 + 1 处 micro-benchmark。
7. ✅ **C-08 D-007 双轨延续**：延续双轨，不做物理迁移。
8. ✅ **C-10 状态机扩展**：与 C-04 联动，`awaiting_claude_action` 作为合法新 state。
9. ✅ **C-11 P2 节奏**：随 C-01 纳入本需求。
10. ✅ **C-13 NFR 验证时机**：micro-benchmark 单测覆盖（不进 CI 增量回归）。
11. ✅ **C-14 锁路径与单轨耦合**：C-08 选双轨延续后此项消解。
12. ✅ **C-15 AC-04 AI 节点完成接口名**：新建独立模块 `scripts/lib/save_node_result.py`。
13. ✅ **C-16 `/workflow:status --verbose` 输出格式**：树形文本（与现有 status 风格一致）。
14. ✅ **C-17 path-lock 进程死亡兜底策略**：`pid 文件 + atexit + 失活 pid 自动清理 stale 锁` 三件套。
15. ✅ **C-18 DAG scheduler feature flag**：不引入；靠 `next` 退化兼容 + 回归测试覆盖。
16. ✅ **C-19 档位字段进 features.json**：加 `priority: P0|P1|P2` 字段，task-planning 阶段按 priority 分组。
17. ⏳ **D-01 AC-02 artifact dispatcher 复用入口** [待用户确认]：候选 `scripts/lib/check_*.py`，detail-design 阶段对比 `check_meta.py` / `check_sourcing.py` / `check_index.py` 等已有 must_exist / format 校验脚本后定稿具体复用对象。
18. ⏳ **D-02 AC-03 approval attempt 默认上限 N** [待用户确认]：当前文档暂用 N=3，detail-design 阶段评审节点 yaml `on_reject.max_attempts` override 机制后定稿默认值。
19. ⏳ **D-03 AC-06 stale 阈值默认 N 分钟** [待用户确认]：detail-design 阶段调研既有 CI 节点平均运行时长后定稿（候选 15 / 30 / 60 min）。
