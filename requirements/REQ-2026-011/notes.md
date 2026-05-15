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
- **状态（2026-05-14 20:53）**：✅ 闭环。`_atomic_write_jsonl` L80 与 `_append_index_line` L195 两处 LOCK_UN 释放均包 `try/except OSError: pass`；17/17 AC test 仍 pass，全套 1332 tests 无回归。

### IB-04 · append_events.py:234,286 慢路径 json.dumps encode 2 次（PERF-003）

- **现状**：`append_events_with_manifest` 慢路径触发时同事件 `json.dumps` encode 2 次（dry-run 检测 + 重 dry-run 实际写），仅 ≥4KB 慢路径影响，整体 < 10KB。
- **目标**：把 dry-run 编码结果缓存复用，避免二次 encode（约 10~20 行重构）。
- **维度**：performance（88 → 一处 minor）。
- **来源**：`reviews/code-F-001-002.json:62-68`。
- **状态（2026-05-14 20:53）**：✅ moot，不动代码。复核结论：fast path 已把 `_estimate_blob_bytes` 返回的 bytes 直接喂给 `_atomic_write_jsonl`（单次 encode 复用）；slow path 的两次 encode 编码的是 mutation 前后两份不同数据（先估算原始尺寸 → 走 manifest 外置 → 再估算外置后尺寸），无法缓存复用。原 IB-04 描述基于早期未复用 bytes 的实现，rev1 重构后已不成立。

### IB-05 · append_events.py:200-290 函数 91 行接近 100 行阈值（CMP-1）

- **现状**：`append_events_with_manifest` 现 91 行（rev1 Args docstring 补全 +3 行），接近 100 行阈值但未越线。
- **目标**：抽 `_check_payload_size` / `_persist_field_to_manifest` 等内联段为独立 helper（建议保 70 行内）。
- **维度**：complexity（84 → 一处 minor）。
- **来源**：`reviews/code-F-001-002.json:40-46`。
- **状态（2026-05-14 20:53）**：✅ 闭环。抽出 `_externalize_large_fields(events, large_field_paths, run_dir) -> None` 私有 helper 承担 mutation 循环；`append_events_with_manifest` 主体（去掉 docstring）压缩到 ~15 行，三段式（dry-run → fallback → 二段 dry-run + write）清晰可读。17/17 AC test pass。

### IB-06 · append_events.py:254 event_id 格式偏离 detailed-design §3.5 命名（DC-1）

- **现状**：`event_id` 格式 `ts-type-uuid-seq` 与 detailed-design §3.5 描述的 `node_id-purpose` 命名规约偏离；F-001 接口未传入 node_id/purpose 参数，属另派文档同步项。
- **目标**：F-004 / F-009 之后 `dispatch_node` 调用点开始传入 node_id 时同步对齐 event_id 命名，或反向修订 detailed-design §3.5（看哪条 cost 更低）。
- **维度**：design_consistency（88 → 一处 minor）。
- **依赖**：F-004 (workflow_continue 调用 append_events) / F-009 (artifact dispatcher)
- **来源**：`reviews/code-F-001-002.json:22-30`。
- **状态（2026-05-14 20:53）**：⏸ pending，本批次不动。F-004 / F-009 落地后 `dispatch_node` 调用点开始传 node_id 才有 ctx 落地，提前修反而要再返工；保留依赖锚定。

### IB-07 · 私有函数 docstring 风格扩张（SPEC-013 follow-up）

- **现状**：rev1 仅把 SPEC-013（公开 API Args 段补全）扩到 `append_events` 自身合规；私有函数（如 `_persist_field_to_manifest` / `_append_index_line` 等）docstring 风格未对齐。
- **目标**：F-002 / F-003 触及 append_events.py 时顺手把 4~5 个私有函数 docstring 风格补齐（Args / Raises / Returns 段统一）。
- **维度**：auxiliary_spec（95，跨多个私有函数累积 minor）。
- **来源**：`reviews/code-F-001-002.json:77`（suggestion #1 末段「私有函数不属首轮 finding 范围」）。
- **状态（2026-05-14 20:53）**：✅ 闭环。`_estimate_blob_bytes` / `_validate_and_stamp` / `_atomic_write_jsonl` / `_get_nested` / `_set_nested` / `_del_nested` 6 个私有函数 docstring 补齐 Args / Returns / Raises 段；`_persist_field_to_manifest` / `_append_index_line` 原已合规；新增 `_externalize_large_fields` 同模板。F-002 / F-003 未触及 append_events.py（其他文件），所以延后到本批次集中处理。

### IB-08 · 既有 approval_pending / approved / rejected 三分支终态守卫缺失（F-002 rev2 同模式扫描沉淀）

- **现状**：`scripts/lib/run_state.py` 既有 L219-231 三分支 `approval_pending` / `approval_approved` / `approval_rejected` 与 F-007 同类终态守卫缺失——事件序列 `[..., workflow_failed, approval_pending(N)]` 下 state 会被覆盖回 `approval_pending`，污染 `/workflow:status` 显示和 D-011 stale 检测。
- **目标**：把 `TERMINAL_STATES` 终态守卫扩到既有 approval_* 三分支（与 F-002 rev2 的 node_ready / approval_repair_started / approval_repair_completed 守卫同构）。
- **维度**：error_handling（既有技术债，与 F-007 同根因）。
- **执行时机**：与 IB-01 (SUCCESS_TERMINAL) 一并在 F-004 PR 处理（顺手扩，与 D-014 同模式扫描一致），或独立 hardening task。
- **状态（2026-05-14 22:30）**：⏸ pending。F-004 rev2 scope 严格控制在 acceptance 内未处理（subagent 已自报"同模式但不在 F-004 acceptance"）。建议在 IB-09 ~ IB-18 lint sweep 同 PR 顺手做，或独立 hardening task。
- **来源**：F-002 rev2 subagent D-014 同模式扫描产出（详见 reviews/code-F-002-001.json 报告 + receipt.json D-014 扫描结论）；critic 已确认超 F-002 acceptance 范围，不在 rev2 commit 修复。

## F-004 rev2 follow-up minors（2026-05-14 22:28 沉淀）

> 来源：`reviews/code-F-004-002.json` 各维度 issues（9 条 minor not_rebutted + 1 条 not_proven 降级；rev2 looks_clean(90) signoff approved）。
> 处置原则：**不阻塞 F-005 派发**；按 D-014 trend-G-meta 终结经验，建议归"lint + 形式正确性 assert + 模块拆分"三件套独立 PR；若到 development→testing 仍有遗漏，列入 doc-refresh 批次或后续需求。

### IB-09 · `_finalize_if_topology_done` 形式正确性 assert（EH-1 / F-CR2-001 critic not_proven 降级）

- **现状**：`scripts/lib/workflow_continue.py:404-408` 热路径 `_finalize_if_topology_done` 仍以 `current_node is None` 单条件写 `workflow_completed`，未接 rev2 新增的 `_is_dag_topology_done` helper（`_is_dag_topology_done` 仅在 `_finalize_after_rebuild_if_last_topology_node:624` 被调用，即 crash 恢复路径）。critic 反证：DAG happy path 下 `_advance_after_completed:438-446` + `_handle_skip/abort` 早返 `_route_outcome` → `current_node=None ⇔ 全节点 SUCCESS_TERMINAL`，所以形式 gap 存在但**不可触发**。
- **目标**：在 `_finalize_if_topology_done` DAG 分支补 `assert _is_dag_topology_done(run_state, workflow)`，让形式与 happy-path 语义一致——不动 happy path，仅防后续重构破坏不变量（如未来若新增节点失败处理路径不再走 `_handle_skip/abort` 早返，会触发误写 `workflow_completed`）。
- **维度**：error_handling + design_consistency。
- **来源**：`reviews/code-F-004-002.json` F-CR2-001（critic verdict not_proven，judge final_disposition downgrade → suggestions follow-up）。

### IB-10 · `_main_loop` bootstrap 返 None 静默 exit 0（F-CR2-002）

- **现状**：`scripts/lib/workflow_continue.py:671-674` bootstrap 阶段 `_select_next_dispatch_target` 返 None 时（DAG yaml 全空 / 全 awaiting / yaml-jsonl 不一致），while 不进入，函数静默返回，main() exit 0。调用方拿到成功码但什么都没做。
- **目标**：next_id is None 时打 WARN（`WARN: bootstrap 阶段无可派发节点，state=running 但 workflow 停止推进，yaml/jsonl 可能不一致`），对齐 `_finalize_after_rebuild:493` 风格。
- **维度**：error_handling minor。
- **来源**：`reviews/code-F-004-002.json` F-CR2-002（critic not_rebutted）。

### IB-11 · `_resume_run:740` print 缺 `ERROR:` 前缀（F-CR2-003）

- **现状**：`scripts/lib/workflow_continue.py:740` `print(str(exc), file=sys.stderr)` 缺 `ERROR:` 前缀；同文件其他错误日志（L749/773/797/802/831/849/859）均带 `ERROR:` 前缀。
- **目标**：改为 `print(f'ERROR: {exc}', file=sys.stderr)` 对齐全文风格，便于日志聚合统一过滤。
- **维度**：error_handling minor。
- **来源**：`reviews/code-F-004-002.json` F-CR2-003。

### IB-12 · `_finalize_after_rebuild` CCN at-threshold 余量耗尽（F-CR2-005）

- **现状**：`scripts/lib/workflow_continue.py:565-632` `_finalize_after_rebuild_if_last_topology_node` rev1→rev2 CCN 18→10（恰好等于阈值），下次再加一条 if 分支就超。L591 复合守卫 `current_node is not None or state != 'running'` 算 2 决策点，是 CCN 上界的主贡献。
- **目标**：把 WARN-and-scan 块（L595-621）抽 `_scan_last_visited(events, node_map) -> (last_node_or_none, emitted_warn: bool)`，主函数 CCN≈6 拓宽余量，同时给反扫逻辑独立可测 seam。
- **维度**：complexity minor。
- **来源**：`reviews/code-F-004-002.json` F-CR2-005。

### IB-13 · `workflow_continue.py` 拆模块（F-CR2-008，原 F-CR-010 反向恶化）

- **现状**：`scripts/lib/workflow_continue.py` 860 行（rev1 726→rev2 +134）反而长了 18%，已超 500 阈值 72%。rev2 通过 helper 拆解换 CCN 余量，但代码总量上行。
- **目标**：拆两个新模块：
  - `scripts/lib/workflow_scheduler.py`：`_dag_next` / `_legacy_first_node` / `_legacy_resume_from_last_visited` / `_legacy_bootstrap_or_resume` / `_legacy_advance` / `_select_next_dispatch_target` / `_ready_nodes` / `_is_dag_topology_done` / `_is_legacy_topology_done` / `_finalize_after_rebuild_if_last_topology_node` / `_finalize_if_topology_done`
  - `scripts/lib/workflow_outcome_router.py`：`_route_outcome` / `_handle_retry` / `_handle_skip` / `_handle_abort` / `_handle_failure` / `_advance_after_completed`
- **预估**：拆分后 `workflow_continue.py` ~520 行；`workflow_scheduler.py` ~120 行；`workflow_outcome_router.py` ~150 行。
- **维度**：complexity minor（独立 PR，IB 中**最大单项**）。
- **执行时机**：建议独立 PR，**不要与 IB-09 ~ IB-12/14~17 lint sweep 混合**——拆模块 PR 应只含纯重构（move + rename + import 同步 + tests 不动）。
- **来源**：`reviews/code-F-004-002.json` F-CR2-008（原 F-CR-010 rev2 反向恶化）。

### IB-14 · `_is_dag_topology_done` 参数顺序与文件惯例反（F-CR2-009）

- **现状**：`scripts/lib/workflow_continue.py:536` `_is_dag_topology_done(workflow, run_state)` 签名 `workflow` 在前；文件其他双参函数（`_ready_nodes` / `_dag_next` / `_legacy_bootstrap_or_resume` / `_select_next_dispatch_target` / `_advance_after_completed`）均 `(run_state, workflow, ...)` 顺序。调用点 L624 已对齐反序，但签名本身违反全文惯例。
- **目标**：签名改 `_is_dag_topology_done(run_state, workflow) -> bool` + 调用点同步。
- **维度**：design_consistency minor。
- **来源**：`reviews/code-F-004-002.json` F-CR2-009。

### IB-15 · 新 helper docstring 缺 Returns 段（F-CR2-010 critic not_proven）

- **现状**：rev2 新增 7 个私有函数（`_dag_next` / `_legacy_first_node` / `_legacy_resume_from_last_visited` / `_legacy_bootstrap_or_resume` / `_legacy_advance` / `_is_dag_topology_done` / `_is_legacy_topology_done`）docstring 均未含「返回值」段；文件内 `_ready_nodes` / `_handle_retry` / `_handle_skip` 等既有函数有「返回：」或 `Returns:` 段。critic 反证既有 `_advance_after_completed` 也无 → 文件风格非全统一，降级为 follow-up。
- **目标**：在 docstring 风格统一 PR 中一并补齐 7 个新 helper 的「返回：`<类型>` — `<语义>`」行。
- **维度**：auxiliary_spec minor。
- **来源**：`reviews/code-F-004-002.json` F-CR2-010（critic not_proven 降级 follow-up）。

### IB-16 · 测试文件死 import + 死变量（F-CR2-011 / F-CR2-012）

- **现状**：
  - `tests/e2e/test_standard_8phase_dag.py:172` `from workflow_dispatcher import DispatchResult as _DR  # noqa: F401` 是死 import + noqa 压制（L145 已有同名 `DispatchResult` import）
  - `tests/e2e/test_standard_8phase_dag.py:107` `completed_node_ids = [...]` 死变量（赋值后未读取）
- **目标**：两处直接删除（违反 CLAUDE.md §5「外科手术式修改」无死代码原则）。
- **维度**：auxiliary_spec minor。
- **来源**：`reviews/code-F-004-002.json` F-CR2-011 / F-CR2-012。

### IB-17 · 新 e2e 测试函数名未沿用同目录混合命名惯例（F-CR2-013）

- **现状**：rev2 新增 `tests/e2e/test_standard_8phase_dag.py:53,131` 两个测试函数纯英文（`test_dag_multi_sink_full_chain` / `test_standard_8phase_dag_bootstrap_validate_first_then_second_layer`），未沿用同目录 `test_legacy_next_chain.py` 已建立的"英文场景词_中文期望"混合命名（如 `test_legacy_next_chain_跑通到workflow_completed` / `test_standard_8phase_首节点为bootstrap_validate`）。
- **目标**：改成混合格式，如 `test_dag_multi_sink_full_chain_三节点依次派发到workflow_completed` 等。
- **维度**：auxiliary_spec minor（低优先级，**非阻断**；可在测试统一命名时回头改齐）。
- **来源**：`reviews/code-F-004-002.json` F-CR2-013。

### IB-18 · `auxiliary-spec-checker` rev2 跨文件命名风格 drift（F-CR2-014 critic rejected，作为团队规范沉淀）

- **现状**：`tests/skills/test_workflow_continue_main_loop.py` 同文件 14 测试全英文，与 `tests/lib/test_run_state_new_events.py`（F-002 引入中文命名）跨文件分裂。critic rejected（同文件一致优先于跨文件），但作为**团队规范议题**值得统一。
- **目标**：在 CLAUDE.md §0 或 `context/team/engineering-spec/` 补「测试函数名允许中文以提升 AC 可读性」豁免条款，统一规范后再回头处理这类 finding，避免后续 reviewer 反复触发同一 finding。
- **维度**：团队规范层（非代码 IB，跟 F-CR-005 类似归"风格双标"）。
- **来源**：`reviews/code-F-004-002.json` F-CR2-014（critic rejected）+ 之前的 F-CR-005（F-003 同模式 follow-up）。


## 会话经验（2026-05-14 22:33）

_[hook-skipped: claude-exit-143]_


## F-005 rev2 follow-up minors（2026-05-15 09:13 沉淀）

> 来源：`reviews/code-F-005-002.json` 各维度 issues（6 follow-up not_rebutted/not_proven + 1 dropped；rev2 looks_clean(82) signoff approved）。
> 处置原则：**不阻塞 F-006 派发**；trend-G-meta 未触发（修复必然代价非纯倒退）；建议归"同函数 / 拆模块 / hardening"三件套独立 PR。

### IB-19 · `_render_artifact_spec` 同函数 PR（F-CR2-001 + F-CR2-002 + F-CR2-004 合并）

- **现状**：rev2 新增 `scripts/lib/workflow_dispatcher.py:537-600` `_render_artifact_spec` 函数 4 类字段平铺（must_exist/not_exist + schema_check + must_contain_sections + must_match_regex），CCN=26（critic 实测，超阈值 10 的 2.6 倍）；同时 `_dispatch_artifact_node:603` 参数=6 含 dead `run_dir`（grep 验证函数体内 0 引用）；line 595-598「其余字段原样保留」浅拷贝引用共享潜在 mutation（生产 yaml 字段全集 = {must_exist, schema_check, must_contain_sections} 全命中显式拷贝路径，line 595-598 永不触发但防御性不足）。
- **目标**：单 PR 1 commit（同函数同次重构最经济）：
  1. 拆 4 子 helper：`_render_list_field(spec, key, fn) -> list` / `_render_schema_check_items(items, fn) -> list` / `_render_must_contain_items(items, fn) -> list` / `_render_must_match_items(items, fn) -> list`；每个 CCN ≤ 5
  2. `_render_artifact_spec` 主函数仅做字段存在性判断 + 调各 helper + 原样保留其余字段，CCN ≤ 6
  3. 删 `_dispatch_artifact_node` 的 `run_dir` 参数（dead）→ 6 → 5 阈值内；调用点同步删
  4. 「其余字段原样保留」改为 `copy.deepcopy(val)` 或仅 list/dict 深拷贝
- **预估**：30 行变更 + 2-3 个新 unit test 覆盖各 helper 边界 + 既有 9 TC 全过
- **维度**：complexity (主) + error_handling (mutation 防御性)
- **来源**：`reviews/code-F-005-002.json` F-CR2-001 (major) + F-CR2-002 (minor) + F-CR2-004 (minor)。

### IB-20 · `artifact_spec_renderer.py` 拆模块独立 PR（F-CR2-003）

- **现状**：`scripts/lib/workflow_dispatcher.py` 文件 650 行（rev1 580 +70），超 500 阈值 +150（rev1 baseline +80 → rev2 +150 恶化）；rev2 新增 `_render_artifact_spec` ~70 行是主因。critic 确认属"修复必然代价"（为修 F-CR-001 必须新增 spec 展开 helper），非纯倒退。
- **目标**：独立 PR 纯重构（move + rename + import 同步 + tests 不动）：
  1. 移 `_render_artifact_spec`（含 IB-19 拆出的 4 子 helper）到 `scripts/lib/artifact_spec_renderer.py` 独立模块
  2. `workflow_dispatcher.py` 仅保留 `from artifact_spec_renderer import _render_artifact_spec`
  3. 对齐 IB-13 `workflow_continue.py` 拆模块同模式
- **预估**：拆分后 `workflow_dispatcher.py` 可降回 ~580 行（仍超阈值 +80 但回到 rev1 baseline）；`artifact_spec_renderer.py` ~80 行
- **执行时机**：建议**在 IB-19 之后**，避免 IB-19 拆 helper 与 IB-20 拆模块同 PR 混合
- **维度**：complexity（独立 PR，IB 中**最大单项**）
- **来源**：`reviews/code-F-005-002.json` F-CR2-003 (major pre_existing 恶化)。

### IB-21 · `run_artifact_checks` 异常包装 hardening（F-CR2-007 + F-CR2-006 同模块）

- **现状**：
  - `scripts/lib/workflow_dispatcher.py:631` `failures = run_artifact_checks(spec, cwd=root)` 无 try/except 包装；run_artifact_checks 若内部抛 `OSError` / `PermissionError` 等会逃逸到 `dispatch_node:159` except Exception 通用兜底，`node_failed.data.error` 为 Python 原生异常字符串而非业务可读消息
  - `scripts/lib/workflow_dispatcher.py:111` `dispatch_node` CCN=11 pre_existing 未恶化（rev1 = rev2）
- **目标**：同模块 IB sweep 一并：
  1. `run_artifact_checks(spec, cwd=root)` 调用外加 `try/except (OSError, ScriptError) as exc: raise WorkflowError(f"artifact 节点 {node_id!r} 校验失败：{exc}") from exc`
  2. `dispatch_node` 字典分发表替换 elif 链（IB-09 ~ IB-12 sweep 同模式扩展），CCN 回到常数 ≈4
- **执行时机**：建议合并到 IB-09 ~ IB-12 lint sweep 一次 hardening 单 PR；亦可与 F-CR-004（rev1 dropped scope-out，run_artifact_checks._check_schema 改 OSError）合并
- **维度**：error_handling minor + complexity minor
- **来源**：`reviews/code-F-005-002.json` F-CR2-006 (pre_existing 未恶化) + F-CR2-007 (suggestion pre_existing) + 关联 rev1 F-CR-004 (dropped scope-out)。

## F-008 rev2 follow-up minors（2026-05-15 14:18 沉淀）

> 来源：`reviews/code-F-008-002.json` 9 follow-up（rev2 looks_clean(87) signoff approved；rev1 5 keep finding 全闭合）。
> 处置原则：**不阻塞 F-009 派发**；trend-G-meta SUPPRESSED；建议归"atexit/fd 生命周期" + "docstring 三段对称" + "复杂度可选拆函数"三件套独立 PR。

### IB-22 · `atexit.unregister(release)` 跨 handle 误删（F2-CR-004 major→follow-up）

- **现状**：`scripts/lib/path_lock.py:319` `atexit.unregister(release)` 不传 args，Python 按函数对象匹配 → 移除该函数的所有注册（含其它 handle 的 partial bindings）
- **可达性**：当前 acquire 仅 `workflow_continue.py:260` 单点调用 + 单进程单锁主流场景**不可达**；未来扩展任务级锁 / 并发持多锁场景即触发跨 handle 误删
- **目标**：用 `functools.partial(release, handle)` 注册 + 用 `atexit.unregister(<partial 对象>)` 精确匹配；或在 release 内用 `atexit._exithandlers` 按 handle 条件 unregister
- **维度**：concurrency major（critic 降级，scope 内单进程不可达）
- **执行时机**：建议合并 IB-23 (F2-CR-005) 同 PR — 同属 atexit / fd 生命周期管理
- **来源**：`reviews/code-F-008-002.json` F2-CR-004。

### IB-23 · `_write_lock_json` 抛 WorkflowError 时 fd 泄漏（F2-CR-005 minor）

- **现状**：`scripts/lib/path_lock.py:293` acquire 取锁成功后调 `_write_lock_json`，若抛 WorkflowError，fd 已持锁但 atexit.register 在 304 还未执行
- **影响**：OS 退出自愈 + 下次 acquire 走 stale 路径自愈双保险，实际影响 <1e-6/op
- **目标**：line 293 处包 `try/except WorkflowError as exc: os.close(fd); raise`（与 _retry_after_stale 内 OSError 兜底风格对齐）
- **维度**：error_handling + security minor（critic 降级）
- **来源**：`reviews/code-F-008-002.json` F2-CR-005。

### IB-24 · `_retry_after_stale` close+unlink 共享 except（F2-CR-006 minor）

- **现状**：`scripts/lib/path_lock.py:199-200` os.close + os.unlink 共享同一 try/except OSError；若 close 失败则 unlink 跳过，logger.debug 后继续
- **目标**：拆为两段 try/except 分别区分 close-fail vs unlink-fail（可观测性 nit；非必须）
- **维度**：error_handling minor
- **来源**：`reviews/code-F-008-002.json` F2-CR-006。

### IB-25 · 模块 docstring 未提 atexit.unregister（F2-CR-008 minor）

- **现状**：`scripts/lib/path_lock.py:1-11` 三件套介绍段 release 描述未提及 `atexit.unregister` 精确语义
- **目标**：在三件套介绍段补一句 atexit 注册/反注册的精确语义（按函数对象匹配 + 配合 functools.partial 实现 per-handle 反注册的注意事项）
- **维度**：design_consistency minor
- **执行时机**：与 IB-22 修复同 PR 一并更新 docstring
- **来源**：`reviews/code-F-008-002.json` F2-CR-008。

### IB-26 · 三进程 TOCTOU inode 分裂（F2-CR-012 minor，spec ack）

- **现状**：`scripts/lib/path_lock.py:262-273` _retry_after_stale 中 close+unlink+open 三步无原子性；进程 B 的 unlink 删掉 A 刚 open 的新文件 → 后续进程 C 创建又一个新 inode → 双持锁
- **状态**：spec §5.1（detailed-design.md:1604-1614）明文承认 ≤1e-7/op + pid 死 + mtime 二次校验双层拦截；保留现状
- **可选优化**：在 unlink 前再读一次 inode 比对（O(1) syscall），进一步降低概率到 ≤1e-9/op
- **维度**：concurrency minor（critic 降级）
- **来源**：`reviews/code-F-008-002.json` F2-CR-012。

### IB-27 · SIGTERM 在 atexit 注册前窗口残锁（F2-CR-013 minor，spec ack）

- **现状**：`scripts/lib/path_lock.py:293-305` `_write_lock_json` 后 → `atexit.register` 前窗口期收到 SIGTERM，默认 handler 不走 atexit → 真残锁；mtime ≥1s 阈值会阻止 1s 内自动清理
- **状态**：spec §5.1 明文 best-effort，下次 acquire stale 自愈；保留现状
- **可选优化**：调换顺序 — 先 `_setup_signal_handlers(handle)` 再 `_write_lock_json`（窗口期缩短至毫秒级）；需评估 handler 在 lock JSON 未写入时调 release 的安全性
- **维度**：concurrency minor（critic 降级）
- **来源**：`reviews/code-F-008-002.json` F2-CR-013。

### IB-28 · retry 失败二次 `_read_lock_json`（F2-CR-017 minor）

- **现状**：`scripts/lib/path_lock.py:276` `_retry_after_stale` 返 None 时 acquire 再次调 `_read_lock_json`，与 line 257 重复 read_text
- **影响**：罕见连续竞争路径 +1 syscall，< 1ms 性能 nit
- **目标**：让 `_retry_after_stale` 返回 None 时一并返回 retry_data；或保留现状（影响可忽略）
- **维度**：performance minor
- **来源**：`reviews/code-F-008-002.json` F2-CR-017。

### IB-29 · docstring 三段对称（F2-CR-020+021 minor）

- **现状**：
  - `_retry_after_stale` (`path_lock.py:185-194`) docstring 三段已含，与 IB-07 Google docstring 风格基本对齐，仅缩进微差（critic 降级）
  - `_is_stale_by_mtime` (`path_lock.py:74-95`) docstring 有 Args/Returns，缺 Raises 段（实际 except 兜底吞所有异常）
- **目标**：
  1. `_retry_after_stale` docstring 缩进对齐 IB-07 模板
  2. `_is_stale_by_mtime` 补 `Raises: 不抛（OSError/ValueError 由 except 兜底返 False）` 一行
- **维度**：design_consistency / auxiliary_spec minor
- **执行时机**：与 IB-22/23 atexit 修复 PR 一并 docstring sweep
- **来源**：`reviews/code-F-008-002.json` F2-CR-020 + F2-CR-021。

### IB-30 · acquire 复杂度可选拆函数（F2-CR-001+002+003 not_proven → 可选）

- **现状**：`scripts/lib/path_lock.py:223-307` rev2 已抽 `_retry_after_stale` 显著降复杂度；reviewer 用 span 行数（85）/ 误数嵌套深度 7（实际 5）/ CCN=9 无 spec 阈值依据 — critic 4 项 not_proven 全部成立
- **可选优化**：进一步抽 `_handle_lock_conflict(fd, lock_path) -> int | None` 子函数，把 line 255-290 的 `if not ok` 取锁失败路径整体抽出；acquire 主路径降至 ≤ 50 行 / 嵌套 ≤ 2 层
- **维度**：complexity（非必须，reviewer 弱证据，建议结合 IB-22/23 同模块改造时一并）
- **来源**：`reviews/code-F-008-002.json` F2-CR-001 + F2-CR-002 + F2-CR-003（critic 全 not_proven，judge 聚合降级 minor）。

