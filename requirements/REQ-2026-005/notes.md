# REQ-2026-005 Notes

## 背景

本需求覆盖经对抗式 review-critic 验证后成立的 10 条 finding，被驳回的 F3 不入范围。

## Finding 清单

- **F1**（P0）：`scripts/gates/audit.py:111` `calc_exit_code` 在 --strict 时不读 `vars["warnings"]`，多个插件（sourcing/meta_schema/index_integrity/plan_freshness）的 warning 被吞
- **F2**（P0）：`.claude/settings.json:27` matcher `Bash|Edit|Write` 不匹配 MultiEdit；protect_branch.py:27 内部支持 MultiEdit 但 hook 不被拉起。本项目决定不维护 codex 双轨，所以仅修 `.claude` 侧
- **F4**（P1）：`scripts/gates/run.py:281` `filter_gates` 仅按 trigger 过滤；registry.yaml 的 `applies_when.changed_files / target_phase / current_phase_in / transition / requires` 在 runner 层零消费
- **F5**（P1）：`scripts/gates/run.py:333` `_validate_phase_args` 仅查 phase 是否在 canonical 集合，不查相邻表
- **F6**（P1）：`scripts/gates/run.py:516` `_handle_escape_hatch` 命中后不区分 finding 类别，所有 error gate 失败一律返 0；对比 `legacy-requirement` 有 `skips_gates_with_tag: [review-verdict]`，本参数无任何 tag 限定
- **F7**（P1）：submit.md 列出 7 项硬门禁，`scripts/gates/triggers/submit.py:74` 仅透传 `--trigger=submit --req=<id>`；`base_reachable.py:58` 不读 `cli_flags.target`，submit.md `--target` 参数链路不通
- **F8**（P1）：`reviews_consistency.py:21` 自带 `triggers={"pre-commit"}` + 显式 Skip 非 pre-commit；CI 不跑该 gate
- **F9**（P2）：`traceability.py:39-49` 仅 `to_phase=="testing"` 真跑；`_feature_mentioned` 用 `re.search(re.escape(feature_id), text)` 字符串包含
- **F10**（P2）：`pr_state.py:82-93` gh 失败 → PASS+WARNING；CLOSED 显式 PASS
- **F11**（P2）：`.github/workflows/quality-check.yml` 仅 5 step，无 build / test / lint；roadmap.md G1/G4 自承待办

## 不入范围

- F3：已被 review-critic 驳回

## tech-research 阶段 reviewer 评审结论

requirement-quality-reviewer 给出 **looks_clean（86 分）**，但因 review-schema.yaml `enums.phase` 仅支持 [definition, outline-design, detail-design, code]，**tech-research 阶段无法落正式 verdict**——按 PHASE_REQUIREMENTS（scripts/lib/check_reviews.py:58）设计，tech-research 不是 reviewer 卡点（outline-design → 只要求 definition 评审通过）。本结论以 notes 形式记录，作为下游 outline-design 阶段的输入。

### Finding（已全部修复）
- **major**：§1.3 R1-1 / §3.3 R3-3 / §5.3 R5-3 末尾"详见待澄清清单第 N 条"悬空引用——已改为引用 §9 决议
- **minor**：§1.1 未提示 audit log 副作用——已加"warning-only 入 FAIL 列 release notes 提示"
- **minor**：§5.1C ruff `line-length=120` 与 `ignore=["E501"]` 矛盾——已删 ignore
- **minor**：§4.1B argparse 双 add_argument 同 dest 风险——已在 R4-3 标注 Python 3.11/3.12 验证
- **minor**：FG-001 验证命令 `<测试 REQ>` 占位符——已改为 REQ-2026-005 + sandbox 命名前缀提示

### Schema 阻塞备忘
review-schema.yaml 缺 tech-research 阶段。后续若希望强制 tech-research 评审，需扩 schema 枚举 + check_reviews.PHASE_REQUIREMENTS。本需求不在范围内。

## outline-design 阶段 reviewer 评审结论

REV-REQ-2026-005-outline-design-001 → **looks_clean 86**（已写入 meta.yaml，待 sign-off）。

reviewer 明确 5 条 finding **均不阻断 looks_clean**，其中 2 条 major 是 detail-design 必须解决的开放点，3 条 minor 是建议。本次按"reviewer looks_clean 后不再改主产出"原则，全部留 detail-design 阶段处理（避免改 outline-design.md 触发 stale 重审死循环）。

### detail-design 必须收口的 2 条 major

1. **meta.legacy 误用防护**（outline-design.md §5 X3）：未来 REQ 可能误设 `meta.legacy=true` 跳过 traceability 校验。**detail-design 需补强制校验点**：例如 `meta_schema` plugin 检查 `legacy=true` 仅当 `phase ∈ {completed, archived}` 才允许，否则报 `R-LEGACY-MISUSE`。
2. **ruff 预扫量化阈值**（outline-design.md §5 X4）：缓解仅写"auto-fix PR 先行"不可执行。**detail-design 需给阈值表**：例如 < 50 直接 auto-fix；50-200 独立 PR；> 200 降级到 `select=["F"]` 起步再渐进。

### detail-design 可选优化的 3 条 minor

1. §3.1 strict 升级 vs §3.4 INFO 语义共享 `vars` 字段——两套语义的字段命名/优先级在 detail-design 接口契约表中明确（如 `vars["warnings"]` vs `vars["severity_hint"]` 不会冲突）
2. §4 实施 DAG 视觉箭头与"5 组无强依赖"措辞冲突——detail-design 可改为正交 DAG 图 + 实施顺序建议两节分开
3. §3.2 + 待澄清 1：detail-design 在动 registry tags 字段前先定位 S1-S10 schema 校验代码位置（候选：`scripts/gates/registry.py` 或 `scripts/lib/check_registry.py`）

## F-005 development 阶段补充 / D-008 见 plan.md（ruff select 起步降级）

一审（REV-REQ-2026-005-code-F-005-001）发现 quality-check.yml `--select=F` 与详设 §5.3 字面 `--select=E,W,F` 不一致。降级原因（E501=289 条历史问题，命中 >200 阈值）属合理实施决策，已在 plan.md D-008 小节补完整 ADR。不修改 detailed-design.md / features.json，避免 detail-design 阶段 stale 重审循环。

## F-003 development 阶段验收数据（baseline + 21 gate 过滤一致性）

### TC-FG3-3 性能 baseline 对比

测量方法：`python3 scripts/gates/run.py --trigger=ci --req=REQ-2026-005`，11 次 perf_counter 中位数。

- **Baseline**（commit `5e799e8`，F-003 实施前）：median **0.2107s**，stdev 2.0ms
- **After**（HEAD `1d6636c`，F-003 实施完成）：median **0.2210s**，stdev 1.8ms
- **涨幅 +4.88%**，远低于 +20% 阈值，**不触发降级方案** ✅

注：detail-design TC-FG3-3 原文「5 次中位数」首次跑出 0.21→0.26（+23.8%）是 50ms 量级抖动放大，扩到 11 次 perf_counter 后稳定到 +4.88%。结论以稳健测量为准。

### 21 条 gate 过滤结果一致性回归

通过对比 baseline / after 两个 worktree 的实际 audit log：

| Trigger | Baseline | After | 一致性 |
|---|---|---|---|
| ci | 5 PASS + 1 FAIL（GATE-REVIEWS-CONSISTENCY）/ exit=1 | 同上 | ✅ |
| submit | 9 PASS + 1 SKIP（GATE-PR-MERGED-STATE: pr_number 缺失）/ exit=0 | 9 PASS / GATE-PR-MERGED-STATE 在 runner filter_gates 阶段过滤掉 / exit=0 | ✅（执行集合一致）|
| post-dev / pre-tool-use | dry-run 计划列表完全相同 | 同左 | ✅ |
| pre-commit | dry-run 列出 6 个 gate（含 5 个 changed_files-aware）；plugin 内自行 skip | dry-run 仅列 1 个（其余 5 个 runner 层 changed_files 空集过滤）| ✅（最终执行集合一致）|

**关键判定**：dry-run 输出条目数差异是**预期**——F-003 把 changed_files / requires 等 5 个 applies_when 字段消费从 plugin 内 precheck 上移到 runner filter_gates 一处（D-003 决策）；最终「真跑 + 通过 / 失败 / 不跑」的 gate 集合在 baseline / after 完全等价。

baseline worktree：`/tmp/req-2026-005-baseline`（验证完成已清理）。
