# REQ-2026-011 · 笔记与沉淀

> 本文件记录研究发现、临时结论、待确认项、经验教训。
> 不是正式文档，随时追加，不删历史条目。

## 背景

本需求基于对本项目与 `/Users/richardhuang/open-source/Archon` 工作流实现差异的研究分析发起。
原始研究产出（仓库根 `findings.md`，由 planning-with-files skill 在 2026-05-13 产出）已归档至
`artifacts/research.md`，并删除根目录的 `progress.md` / `task_plan.md` 临时文件。

## 用户最终意图（来自 2026-05-13 主对话）

> 「根据项目目录下的 findings.md 中的内容新增需求，走 req 需求的工作流，将 findings.md
> 内容转成 `context/team/engineering-spec/specs/` 中的文档」

也就是说：本需求最终交付物之一是一份 spec 文档，位于
`context/team/engineering-spec/specs/2026-05-13-workflow-runtime-dag-completion-design.md`
（已对齐 specs/INDEX.md 既有 `YYYY-MM-DD-<topic>-design.md` 命名 pattern；
原拟定 `*-completion.md` 由 reviewer 在 definition 评审中纠正），承载 P0/P1/P2
优化方案的设计正文。该交付物预计在 **outline-design / detail-design 阶段**产出。

## research.md P0/P1/P2 摘要

- **P0** 真实 YAML 能闭环：DAG ready-node scheduler / `artifact` dispatcher / approval 闭环（含 `on_reject`）
- **P1** Claude Code 集成语义 + 状态保护：AI 节点完成契约（`node_ready` / `awaiting_claude_action`）/ active-run path lock / status doctor
- **P2** 体验增强：loop 两步落地 / 子工作流父子完成回填 / 路由 fuzzy / Claude 运行参数白名单

## 待确认项

- [ ] 与 REQ-2026-010（workflow 引擎 main loop 与 bootstrap 完整化）的边界划分：哪些 P0 项目实际已在 REQ-010 落地、哪些是 REQ-011 增量
- [ ] spec 文档命名是否沿用 `YYYY-MM-DD-<topic>-design.md` 模板（看 specs/INDEX.md 决定）
- [ ] 节点 dispatcher 增补是否拆 PR：`artifact` / `approval-close-loop` / `subworkflow-backfill` 是否合并到同一 PR

## 经验 / 风险

- 风险：与 REQ-2026-010 高度重叠，需求 definition 阶段必须明确"增量范围"，避免重做已 ship 的工作
- 风险：Archon 是远程平台架构，照搬会破坏本项目"轻量本地 Claude Code 集成"的定位；P0/P1/P2 已做取舍说明，definition 阶段要把"不照搬什么"写清楚（如多 provider / DB 状态存储）
