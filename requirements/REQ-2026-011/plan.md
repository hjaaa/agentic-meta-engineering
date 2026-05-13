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
- 风险 2：DAG 调度器重构是 runtime 主路径变更 —— 必须 feature-flag 化 + 全量回归 standard-8phase / code-review-embedded / sub_workflow 三类 YAML
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

### D-001 <决策标题>
- **Context**：做决策时的背景 / 约束
- **Decision**：选了什么，没选什么
- **Consequences**：好的后果、不好的后果
- **时间**：2026-05-13 08:36:31
- **Supersedes**：D-NNN（废弃前一决策时才有）
