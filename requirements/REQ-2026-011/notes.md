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

## 回退记录

### 2026-05-13 11:25 · tech-research → definition

- **回退原因**：需要重新讨论需求
- **归档位置**：`artifacts/.rollback-20260513-112537/tech-research.md`
- **保留**：requirement.md / research.md / plan.md（D-001~D-005 ADR）/ reviews/（definition-001 + definition-002 含 sign-off）
- **下游影响**：
  - tech-research 产出（feasibility=high / 17~23 天估算 / D-01/D-02 关闭结论 / D-03 延期、Q-01~Q-05 新发现）全部作废，重做时需重审
  - reviews.definition.latest = REV-002 looks_clean(92) + tty signoff approved 状态保留；若 requirement.md 在 definition 重做时再次变更，会触发 R005 stale，需要走第三轮评审
  - meta.yaml.gates_passed 历史保留 bootstrap→definition / definition→tech-research 两条；下次切换 phase 时门禁 runner `_validate_phase_args` 会基于当前 phase（已回到 definition）做相邻校验

## Implementation backlog（task-planning 阶段沉淀，2026-05-14）

> 来自 detail-design v8 评审遗留，不阻塞 task-planning → development，但 implementation 起步时必须处理。

### IB-01 · SUCCESS_TERMINAL 抽共享常量（F-004 实施前置）

- **现状**：`SUCCESS_TERMINAL = {"completed", "skipped"}` 字面集合在 `detailed-design.md` 四处局部定义（§3.3.5 line 767-771 / §3.6.2 line 1012 / §3.6.3 line 1035 / §5.4 line 1692-1694），靠注释「与 §3.6.3 同源」维持一致——已连续三轮（v6→v7→v8）出现不对称 drift。
- **目标**：implementation 起步时把常量提到 `scripts/lib/run_state.py`（建议命名 `NodeState.SUCCESS_TERMINAL = frozenset({"completed", "skipped"})`），让 `workflow_continue.py` 的 `_ready_nodes` / `_select_next_dispatch_target` / `_finalize_after_rebuild_if_last_topology_node` 四处 import 同一常量。
- **F-004 modules 补丁**：当前 modules 含 `workflow_loader.py / workflow_continue.py / standard-8phase.yaml + 测试 6 项`，缺 `scripts/lib/run_state.py`——F-004 进入 development 前需补到 modules 列表。
- **来源**：`reviews/detail-design-007.json:68`（suggestion #1）+ `reviews/detail-design-008.json:81/91`（recommendation #2 + modules 缺失提示）。

### IB-02 · outline-design.md:135 末节点判定文案 readability 清理（P3）

- **现状**：outline-design.md:135 同一表格格内出现 4 种表述并存——「成功类终态 / SUCCESS_TERMINAL / completed / skipped」，正确性已闭环（v8 P3 修订），但可读性偏低。
- **目标**：在 implementation PR 一并把 outline-design.md:135 的术语统一为「SUCCESS_TERMINAL ({completed, skipped})」单一表述，配套备注「与 detailed-design §3.6.3 同源」。
- **优先级**：P3 minor，可与 F-004 同 PR 顺带 fix，不单开任务。
- **来源**：`reviews/detail-design-008.json:71`（minor #3）。
