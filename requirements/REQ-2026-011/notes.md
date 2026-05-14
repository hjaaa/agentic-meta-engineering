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
- **状态（2026-05-14 17:05）**：✅ F-004 task.md frontmatter `touches` 已补 `scripts/lib/run_state.py`（D-015 #3 真值源补丁，不动 features.json hash 锁）；常量抽取本体由 F-004 implementer 实施时一并落地（验收已在 task 描述中明示「implementation 阶段抽到 scripts/lib/run_state.py 共享常量永久消除复发风险」）。
- **来源**：`reviews/detail-design-007.json:68`（suggestion #1）+ `reviews/detail-design-008.json:81/91`（recommendation #2 + modules 缺失提示）。

### IB-02 · outline-design.md:135 末节点判定文案 readability 清理（P3）

- **现状**：outline-design.md:135 同一表格格内出现 4 种表述并存——「成功类终态 / SUCCESS_TERMINAL / completed / skipped」，正确性已闭环（v8 P3 修订），但可读性偏低。
- **目标**：把 outline-design.md:135 的术语统一为「SUCCESS_TERMINAL ({completed, skipped})」单一表述，配套备注「与 detailed-design §3.6.3 同源」。
- **执行时机修订（2026-05-14 17:05）**：原拟「与 F-004 同 PR 顺带 fix」改为「与 D-015 #4 detailed-design.md commit 数矛盾同批次，归入 development→testing phase-transition 前 doc-refresh PR」。
  - **原因**：outline-design.md 被 `outline-design` review hash 锁定（meta.yaml:106 hash=379fb36d…），F-004 开发中任何 PR touch outline-design.md 会触发 R005 stale → 强制 outline 重审，破坏 4 轮 looks_clean(92) signoff 评审结果。
  - **替代方案**：与 D-015 #4 detail-design commit 数 fix 合并到 development→testing 切换前的 single doc-refresh batch（已预留「单独走 1 轮 detail-design refresh 评审」窗口，可顺带捎上 outline-design refresh），把 R005 触发集中到一次。
- **优先级**：P3 minor，不阻塞 F-004 派发。
- **来源**：`reviews/detail-design-008.json:71`（minor #3）+ ADR D-015 #4。

## F-001 rev2 follow-up minors（2026-05-14 16:23 沉淀）

> 来源：`reviews/code-F-001-002.json` 各维度 issues（5 条 minor 全部 `required_fixes=[]` 不阻断 sign-off，已 approved；按 D-014 trend-G-meta 警戒解除）。
> 处置原则：F-002~F-008 实施过程中**顺手**修复（不单开 task），若到 development→testing 仍有遗漏，列入 doc-refresh 批次或 IB 后续需求。

### IB-03 · append_events.py:195 LOCK_UN 缺显式 try/except（EH-005）

- **现状**：`_append_index_line` 中 `fcntl.flock(LOCK_UN)` 释放锁缺显式 try/except 兜底，rev1 未修，依赖 fd close 隐式释放。
- **目标**：补一段 `try: fcntl.flock(fd, LOCK_UN) except OSError: pass`（POSIX 上仅 EBADF 触发，极罕见但显式更稳）。
- **维度**：error_handling（92 → 一处 minor）。
- **来源**：`reviews/code-F-001-002.json:50-54`。

### IB-04 · append_events.py:234,286 慢路径 json.dumps encode 2 次（PERF-003）

- **现状**：`append_events_with_manifest` 慢路径触发时同事件 `json.dumps` encode 2 次（dry-run 检测 + 重 dry-run 实际写），仅 ≥4KB 慢路径影响，整体 < 10KB。
- **目标**：把 dry-run 编码结果缓存复用，避免二次 encode（约 10~20 行重构）。
- **维度**：performance（88 → 一处 minor）。
- **来源**：`reviews/code-F-001-002.json:62-68`。

### IB-05 · append_events.py:200-290 函数 91 行接近 100 行阈值（CMP-1）

- **现状**：`append_events_with_manifest` 现 91 行（rev1 Args docstring 补全 +3 行），接近 100 行阈值但未越线。
- **目标**：抽 `_check_payload_size` / `_persist_field_to_manifest` 等内联段为独立 helper（建议保 70 行内）。
- **维度**：complexity（84 → 一处 minor）。
- **来源**：`reviews/code-F-001-002.json:40-46`。

### IB-06 · append_events.py:254 event_id 格式偏离 detailed-design §3.5 命名（DC-1）

- **现状**：`event_id` 格式 `ts-type-uuid-seq` 与 detailed-design §3.5 描述的 `node_id-purpose` 命名规约偏离；F-001 接口未传入 node_id/purpose 参数，属另派文档同步项。
- **目标**：F-004 / F-009 之后 `dispatch_node` 调用点开始传入 node_id 时同步对齐 event_id 命名，或反向修订 detailed-design §3.5（看哪条 cost 更低）。
- **维度**：design_consistency（88 → 一处 minor）。
- **依赖**：F-004 (workflow_continue 调用 append_events) / F-009 (artifact dispatcher)
- **来源**：`reviews/code-F-001-002.json:22-30`。

### IB-07 · 私有函数 docstring 风格扩张（SPEC-013 follow-up）

- **现状**：rev1 仅把 SPEC-013（公开 API Args 段补全）扩到 `append_events` 自身合规；私有函数（如 `_persist_field_to_manifest` / `_append_index_line` 等）docstring 风格未对齐。
- **目标**：F-002 / F-003 触及 append_events.py 时顺手把 4~5 个私有函数 docstring 风格补齐（Args / Raises / Returns 段统一）。
- **维度**：auxiliary_spec（95，跨多个私有函数累积 minor）。
- **来源**：`reviews/code-F-001-002.json:77`（suggestion #1 末段「私有函数不属首轮 finding 范围」）。

### IB-08 · 既有 approval_pending / approved / rejected 三分支终态守卫缺失（F-002 rev2 同模式扫描沉淀）

- **现状**：`scripts/lib/run_state.py` 既有 L219-231 三分支 `approval_pending` / `approval_approved` / `approval_rejected` 与 F-007 同类终态守卫缺失——事件序列 `[..., workflow_failed, approval_pending(N)]` 下 state 会被覆盖回 `approval_pending`，污染 `/workflow:status` 显示和 D-011 stale 检测。
- **目标**：把 `TERMINAL_STATES` 终态守卫扩到既有 approval_* 三分支（与 F-002 rev2 的 node_ready / approval_repair_started / approval_repair_completed 守卫同构）。
- **维度**：error_handling（既有技术债，与 F-007 同根因）。
- **执行时机**：与 IB-01 (SUCCESS_TERMINAL) 一并在 F-004 PR 处理（顺手扩，与 D-014 同模式扫描一致），或独立 hardening task。
- **来源**：F-002 rev2 subagent D-014 同模式扫描产出（详见 reviews/code-F-002-001.json 报告 + receipt.json D-014 扫描结论）；critic 已确认超 F-002 acceptance 范围，不在 rev2 commit 修复。
