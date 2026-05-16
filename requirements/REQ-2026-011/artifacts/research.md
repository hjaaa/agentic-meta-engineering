# 发现记录：自定义工作流差异分析

## 需求
- 比较本项目与 `/Users/richardhuang/open-source/Archon` 的自定义工作流实现。
- 关注本项目已面向 Claude Code 集成的逻辑差异。
- 输出本项目优化方案，不直接改代码。

## 研究发现
- 本项目是面向 Claude Code 的工程骨架，工作流相关线索集中在 `.claude/commands/workflow/`、`.claude/skills/`、`.claude/hooks/`、`scripts/lib/workflow_*`、`scripts/lib/run_state.py`、`scripts/lib/workflow_loader.py`、`requirements/REQ-2026-009/`。
- Archon 是远程 Agentic Coding 平台，工作流核心集中在 `packages/workflows/src/`，并通过 `.archon/workflows/`、`.archon/commands/`、`packages/cli`、`packages/core`、Provider 适配层执行。
- Archon 文档显示其 workflow CLI 支持 `list/run/status/resume/abandon/cleanup/event emit/validate`，并有 DAG 节点、状态表、事件表和 provider 抽象。
- 本项目文档显示其目标是把 workflow 收口到 Claude Code slash command + skill + Python lib 的分层：L1 command、L2 skill、L3 lib、L4 文件状态。
- 本项目 workflow loader 是手写强校验，支持 `skill/agent/prompt/prompt_file/bash/loop/approval/artifact/sub_workflow` 互斥节点、隐式顺序依赖、`when`、变量引用、prompt_file 白名单、sub_workflow 嵌套深度 ≤ 2。
- 本项目运行态用 `run-state.jsonl` + `RunState.rebuild`，事件追加使用 `fcntl.LOCK_EX` + `O_APPEND`，状态从事件流反扫恢复；状态文件在 `requirements/<REQ-ID>/` 或 `runs/<RUN-ID>/`。
- 本项目主循环目前是 Python 侧顺序推进 `current_node`，`skill/prompt/agent` 多数只写完成事件或输出占位，真实 Claude Code 执行仍依赖主 Claude/后续集成；DAG 并发层没有在 Python 主循环中真正执行。
- Archon 使用 Zod schema 校验，节点类型包括 `command/prompt/bash/script/loop/approval/cancel`，支持 provider/model、output_format、tool 限制、hooks、mcp、skills、agents、effort/thinking、sandbox、fallback/cost cap 等配置。
- Archon `dag-executor.ts` 按 Kahn 算法构建拓扑层，同层 `Promise.allSettled` 并发执行；支持 trigger_rule、when、retry、AI streaming、tool 事件、idle timeout、cancel 检查、活动心跳和结构化输出。
- Archon 运行态落在 DB：`workflow_runs` 表状态为 `pending/running/completed/failed/cancelled/paused`，`workflow_events` 记录节点、loop、approval、tool 事件；失败/暂停可由 CLI/操作层恢复。
- Archon CLI 默认创建 worktree 隔离，支持 `--branch/--no-worktree/--resume`，并有 path-lock 防止同 checkout 并发写冲突。
- Archon approval/reject 会写事件并把 run 转为可 resume 状态；标准 approval 的 node_completed 由 approve 操作写入，interactive loop 则保留循环上下文，由下一次执行恢复。

## 关键差异
1. 执行模型：
   - Archon 是中心化 DAG executor，负责调度、AI provider、工具事件、状态落库和恢复。
   - 本项目是 Claude Code 原生集成，slash command/Skill/Python lib 分层更轻，但 runtime 尚未形成完整 DAG scheduler。
2. DAG 推进：
   - Archon 会构建拓扑层，同层并发执行，并按 `depends_on`、`trigger_rule`、`when` 判断 ready 节点。
   - 本项目 loader 已校验并展开 `depends_on`，但 `workflow_continue.py` 仍主要依赖 `current_node.next`；真实 YAML 大量使用 `depends_on`，新 run 又只写 `workflow_started`，容易出现 `/workflow:continue` 无节点可跑。
3. 节点执行：
   - Archon 的 `command/prompt/bash/script/loop/approval/cancel` 都有明确 runtime 语义。
   - 本项目的 `skill/prompt/agent` 当前更像占位完成事件；`artifact` 在 loader 中是合法节点，但 dispatcher 未见对应派发分支；`sub_workflow` 已能创建子 run，但父子完成回填仍需补齐。
4. Approval：
   - Archon approve/reject 操作会把 approval 节点与 run 状态推进到可恢复状态，reject 可进入 `on_reject`。
   - 本项目 approve/reject 当前主要写 `approval_approved`/`approval_rejected`，未完整关闭 approval 节点，也未实现 `on_reject` 主路径。
5. Loop：
   - Archon loop 支持 AI iteration、until signal、until bash、interactive approval、session 恢复。
   - 本项目 loop 当前主要写 iteration 事件并按次数返回，尚未形成真实 Claude Code 循环执行。
6. 并发与隔离：
   - Archon 默认 worktree 隔离，并有 path-lock 防同 checkout 并发。
   - 本项目 requirement run 会切 feature branch，但缺通用 active-run/path lock；非 requirement run 更依赖操作者避免冲突。
7. 状态存储：
   - Archon 使用 DB run/event 表，适合平台化和远程执行。
   - 本项目使用本地 jsonl 事件流，轻量、可审计、适合 Claude Code，但需要补充锁、heartbeat、doctor/status 诊断能力。

## 本项目优化方案
### P0：先让真实 YAML 能闭环运行
1. Runtime 改为基于 DAG 的 ready-node scheduler：
   - 从 `workflow_loader.py` 的 `depends_on` 结果出发，计算已完成、失败、阻塞、ready 节点。
   - `current_node` 为空时从第一层 ready 节点启动，而不是退出。
   - `/workflow:continue` 不再依赖 `node.next` 作为主路径，只把它保留为兼容字段或显式 override。
   - 验证：`/workflow:run requirement:standard-8phase` 后立刻 `/workflow:continue` 能进入首节点；`code-review-embedded` 能识别 8 个 checker 为同层 ready。
2. 补 `artifact` dispatcher：
   - loader 已把 `artifact` 当合法节点，dispatcher 需要增加 `_dispatch_artifact_node`，调用既有 artifact check 脚本或统一校验入口。
   - 验证：`standard-8phase.yaml` 首个 `bootstrap-validate` artifact 节点可执行并写 `node_completed/node_failed`。
3. 修 approval 闭环：
   - approve 后关闭当前 approval 节点并推进下游。
   - reject 后实现 `on_reject` 路径、attempt 计数和失败上限。
   - 保留 hook 阻断 AI 自动调用 approve/reject 的安全边界。
   - 验证：pending -> approve -> continue 跑下一个节点；reject -> on_reject -> 再次 pending 或达到上限失败。

### P1：把 Claude Code 集成语义说清并补状态保护
1. 明确 AI 节点完成契约：
   - `skill/prompt/agent` 不应在没有真实执行时直接写 `node_completed`。
   - 增加 `node_ready`/`awaiting_claude_action`，由主 Claude Code 或子 agent 完成实际工作后通过统一保存接口写结果。
2. 增加 active-run/path lock：
   - 保留 jsonl，不引入 DB。
   - 借鉴 Archon path-lock，在 `requirements/.locks` 或 `runs/.locks` 中按 repo/branch/run 加锁，避免重复 continue 或并发修改同一 checkout。
3. 增强 status/doctor：
   - `/workflow:status --verbose` 显示 ready/running/blocked/paused/completed 节点及阻塞原因。
   - 增加 heartbeat/stale 检测，处理半写 jsonl、approval pending、缺 current_node 等常见恢复场景。

### P2：体验与能力增强
1. Loop 分两步落地：
   - 先实现确定性的 `until_bash`/max_iterations。
   - 再实现 AI loop、interactive gate、session resume。
2. 子工作流完成回填：
   - 子 run completed/failed/cancelled 后，父 run 写 `child_*` 与父节点 `node_completed/node_failed`。
   - 尊重 `on_subworkflow_failure`。
3. 路由与发现优化：
   - 保留关键词 launcher，但增加 fuzzy/ambiguous 处理和 `workflow list --json`。
   - 用 workflow `description/applicable_when` 辅助路由，不必直接照搬 Archon AI router。
4. Claude 运行参数白名单：
   - 保守支持 `allowed_tools/denied_tools/mcp/skills/agents/idle_timeout/output_format` 等 Claude Code 相关字段。
   - 暂不引入 Archon 的多 provider/provider model 体系。

## 技术决策
| 决策 | 原因 |
|------|------|
| 从源码入口、配置文件和文档共同定位工作流实现 | 仅凭文件名容易漏掉 Claude Code 集成逻辑 |

## 问题记录
| 问题 | 处理 |
|------|------|

## 资源
- 本项目：`/Users/richardhuang/learnspace/agentic-meta-engineering`
- Archon：`/Users/richardhuang/open-source/Archon`
- 本项目入口文档：`CLAUDE.md`
- Archon 入口文档：`/Users/richardhuang/open-source/Archon/CLAUDE.md`
