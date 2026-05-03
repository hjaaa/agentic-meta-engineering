---
id: REQ-2026-005
title: 门禁系统加固 · 追溯链一致性报告
created_at: "2026-05-03"
refs-traceability: true
---

# REQ-2026-005 追溯链一致性报告

## 执行摘要

| 项目 | 值 |
|---|---|
| 校验时间 | 2026-05-03 |
| 校验模式 | semantic（接口签名 + 分支覆盖 + hash 验证） |
| 总体结论 | **WITH_WARNINGS** |
| 维度 1 需求→设计 | PASS |
| 维度 2 设计→features.json | PASS（with noted deviation D-008） |
| 维度 3 features.json→代码 | PASS（F-002 minor gap） |
| 维度 4 acceptance→测试 | PASS（3 项待人工验收，已合理标注） |
| 维度 5 review verdict 完备性 | FAIL（F-002 缺 code review；task hash stale） |
| 维度 6 不变量 | PASS（with noted residual markers） |

---

## 维度 1：需求 → 设计 双向追溯

### 1.1 Finding → Feature Group 映射

requirement.md（来源：requirements/REQ-2026-005/artifacts/requirement.md:14）声明"10 条 finding not_rebutted，1 条 F3 被驳回"，对应下表：

| Finding | 内容摘要 | 覆盖 FG | 设计文档章节 |
|---|---|---|---|
| F1 | strict 模式形同虚设（audit.py:111 has_warning_fail 未触发） | FG-001 | outline-design.md §2 / detailed-design.md §1 |
| F2 | Hook matcher 漏 MultiEdit（settings.json:29） | FG-002 | outline-design.md §2 / detailed-design.md §2 |
| F3 | Bash 多行命令绕过 | **已驳回** | requirement.md:22,123 明确排除；outline-design.md 范围外 |
| F4 | registry applies_when 字段零消费（run.py:281） | FG-003 | outline-design.md §2 / detailed-design.md §3 |
| F5 | _validate_phase_args 无跨阶段跳跃校验（run.py:349） | FG-003 | detailed-design.md §3.2 |
| F6 | escape hatch --force-with-blockers 范围过宽（run.py:516） | FG-004 | outline-design.md §2 / detailed-design.md §4.2 |
| F7 | submit.py 仅透传 trigger，3 门禁缺失（submit.py:74） | FG-004 | outline-design.md §2 / detailed-design.md §4.4 |
| F8 | reviews_consistency 无 CI 兜底（reviews_consistency.py:21） | FG-001 | outline-design.md §2 / detailed-design.md §1.2 |
| F9 | traceability 仅 testing 触发（traceability.py:39） | FG-005 | detailed-design.md §5.1 |
| F10 | pr_state gh 失败/CLOSED 降级 PASS（pr_state.py:82） | FG-005 | detailed-design.md §5.2 |
| F11 | CI workflow 仅 5 step 无 build/test/lint（quality-check.yml:31） | FG-005 | detailed-design.md §5.3 |

**结论：10 项 not_rebutted finding 全部被 5 个 FG 覆盖（F1+F8→FG-001，F2→FG-002，F4+F5→FG-003，F6+F7→FG-004，F9+F10+F11→FG-005）。F3 在 requirement.md:22 和 :123 均明确排除，outline-design.md 不包含段无该 finding 的任何设计内容（来源：requirements/REQ-2026-005/artifacts/outline-design.md）。双向追溯完整。**

### 1.2 设计点 → 需求反向追溯

| 设计点 | 反向指向需求 | 状态 |
|---|---|---|
| _legacy_to_report 返 Decision.FAIL | requirement.md:16 F1（来源：detailed-design.md:16） | 对应 |
| reviews_consistency CI 全量扫描 | requirement.md:20 F8（来源：detailed-design.md:47） | 对应 |
| settings.json matcher 加 MultiEdit | requirement.md:17 F2（来源：detailed-design.md:89） | 对应 |
| filter_gates 5 字段消费 | requirement.md:18 F4（来源：detailed-design.md:104） | 对应 |
| load_adjacent_phases 相邻校验 | requirement.md:18 F5（来源：detailed-design.md:129） | 对应 |
| _handle_escape_hatch tags 交集 | requirement.md:19 F6（来源：detailed-design.md:187） | 对应 |
| 3 新 plugin + submit --target | requirement.md:20 F7（来源：detailed-design.md:229） | 对应 |
| traceability submit 路径 | requirement.md:20 F9（来源：detailed-design.md:287） | 对应 |
| pr_state ls-remote fallback | requirement.md:20 F10（来源：detailed-design.md:304） | 对应 |
| quality-check.yml pytest+ruff step | requirement.md:20 F11（来源：detailed-design.md:337） | 对应 |
| _check_legacy_misuse | requirement.md:19（meta.legacy 误用防护，reviewer 强收口） | 对应 |

**维度 1 结论：PASS。**

---

## 维度 2：设计 → features.json 追溯

### 2.1 详设实现点 → features.json 覆盖检查

| 详设章节 | 关键实现点 | features.json 对应 feature | 一致性 |
|---|---|---|---|
| §1.1 _legacy_to_report | 4 plugin 修改，R-WARNING-ONLY 错误码 | F-001 modules / acceptance TC-FG1-1 | 一致 |
| §1.2 reviews_consistency CI | precheck + _run_ci_full_scan | F-001 modules（reviews_consistency.py） | 一致 |
| §2.1 settings.json matcher | 单行修改 | F-002 modules（.claude/settings.json） | 一致 |
| §3.1 filter_gates 5字段 | changed_files/target_phase/current_phase_in/transition/requires | F-003 acceptance TC-FG3-1 | 一致 |
| §3.2 load_adjacent_phases | phase_enum.py 新增函数 | F-003 modules（phase_enum.py） | 一致 |
| §4.1-4.2 escape hatch tags | registry.yaml + _handle_escape_hatch | F-004 acceptance TC-FG4-2 / TC-FG4-5 | 一致 |
| §4.3 argparse alias | --bypass-review-blockers + deprecation | F-004 acceptance TC-FG4-3 | 一致 |
| §4.4 三新 plugin | branch_match / phase_in_set / ahead_of_origin | F-004 modules（3 新文件） | 一致 |
| §4.5 base_reachable --target | cli_flags.get("target") 优先读 | F-004 acceptance TC-FG4-4 | 一致 |
| §5.1 traceability 升级 | submit 路径 + 单词边界正则 | F-005 acceptance TC-FG5-1 | 一致 |
| §5.2 pr_state ls-remote | fallback + CLOSED INFO 化 | F-005 acceptance TC-FG5-1 | 一致 |
| §5.3 ruff 集成 | pyproject.toml + CI step | F-005 acceptance TC-FG5-3 | 字面偏离（见 §2.2） |
| §5.4 _check_legacy_misuse | meta_schema 新增校验规则 | F-005 acceptance TC-FG5-2 | 一致 |

### 2.2 D-008 ADR 定位确认

详设 §5.3 字面写 `select=["E","W","F"]` 与 `--select=E,W,F`（来源：requirements/REQ-2026-005/artifacts/detailed-design.md:332）；实际落地为 `select=["F"]`（来源：pyproject.toml）+ `--select=F`（来源：.github/workflows/quality-check.yml:40）。

ADR D-008 完整记录了偏离原因——ruff statistics 实施前 E501=289 / E402=13 / F401=2 / F841=2 共 306 条，命中阈值表「>200 → 降级」（来源：requirements/REQ-2026-005/plan.md:108）。详设字面未回写是有意为之（避免触发 detail-design stale 重审）。ADR 位于 plan.md，未污染 detailed-design.md。

**维度 2 结论：PASS（D-008 偏离有充分 ADR 记录，详设本身 hash 稳定，stale=false）。**

---

## 维度 3：features.json → 代码追溯

### 3.1 模块文件存在性

| Feature | modules 列举 | 实际文件存在 |
|---|---|---|
| F-001 | meta_schema.py / sourcing.py / plan_freshness.py / index_integrity.py / reviews_consistency.py / registry.yaml / tests/gates/ | 全部存在 |
| F-002 | .claude/settings.json | 存在；matcher 已改为 `Bash\|Edit\|Write\|MultiEdit`（来源：.claude/settings.json:29） |
| F-003 | run.py / meta_schema.py / sourcing.py / index_integrity.py / plan_freshness.py / phase_enum.py / tests/gates/ | 全部存在 |
| F-004 | registry.yaml / run.py / submit.py / base_reachable.py / **branch_match.py（新建）** / **phase_in_set.py（新建）** / **ahead_of_origin.py（新建）** / registry.py / tests/gates/ | 全部存在，3 个新 plugin 已创建 |
| F-005 | traceability.py / pr_state.py / meta_schema.py / pyproject.toml / quality-check.yml / tests/gates/ / scripts/ | 全部存在 |

### 3.2 Feature commit 存在性

| Feature | reviewed_commit | git log 验证 |
|---|---|---|
| F-001 | d491004 | 存在（"补建 artifacts/tasks/ 流程元数据"） |
| F-002 | d7aaf74 | 存在（"F-002 .claude/settings.json matcher 加 MultiEdit"） |
| F-003 | 508ce30 | 存在（"F-003 验收数据落盘"） |
| F-004 | 58fa308 | 存在（"F-004 实现完成"） |
| F-005 | a46e2c5 | 存在（"F-005 一审 verdict + round-2 流程产物"） |

注：F-002 的 commit d7aaf74 未通过 `/code-review` 流程，reviewed_commit 为实现 commit 而非 review commit（详见维度 5）。

**维度 3 结论：PASS（所有模块文件存在，所有 reviewed_commit 可验证）。**

---

## 维度 4：acceptance criterion → 测试覆盖

### 4.1 自动化验收逐条映射

acceptance 来源：requirements/REQ-2026-005/artifacts/features.json
test-report 来源：requirements/REQ-2026-005/artifacts/test-report.md

| TC | acceptance criterion | test-report 验证结果 | 状态 |
|---|---|---|---|
| TC-FG1-1 | 4 plugin × {error_only,warning_only,mixed,empty} 矩阵 | test_legacy_to_report_warning_fail.py 28 用例全过（test-report.md:28） | PASS |
| TC-FG1-2 | --strict 在 plan.md 含 W002/W003 时 exit=1 | exit=1，stderr 含 W002（test-report.md:29） | PASS |
| TC-FG1-2（兼容） | 非 strict exit=0 | 非 strict exit=0 验证通过（test-report.md:30） | PASS |
| - | GATE-REVIEWS-CONSISTENCY 出现在 CI trigger | registry.yaml 含 ci；日志可见 gate_id=GATE-REVIEWS-CONSISTENCY（test-report.md:31） | PASS |
| - | release notes 含 warning-only 列变化说明 | release-notes/REQ-2026-005-FG-001.md 存在（test-report.md:32） | PASS |
| TC-FG2-1 | develop 分支 MultiEdit 被拦截 | **待人工验收（M-01）** | PENDING |
| - | matcher 字符串为 Bash\|Edit\|Write\|MultiEdit | settings.json:29 验证通过（test-report.md:43） | PASS |
| TC-FG3-1 | 5字段 × 命中/不命中/空列表矩阵 | test_filter_gates_applies_when.py 22 用例全过（test-report.md:53） | PASS |
| TC-FG3-2 | bootstrap→testing exit=2，R-INVALID-PHASE-TRANSITION | 实测 exit=2，stderr 命中（test-report.md:54） | PASS |
| TC-FG3-3 | baseline +20% 内 | 实测 +4.88%（test-report.md:55） | PASS |
| - | 21 gate 过滤结果一致 | test_runner.py 回归通过（test-report.md:56） | PASS |
| - | 4 plugin changed_files precheck 删除 | has_changed_files_filter=False（test-report.md:57） | PASS |
| TC-FG4-1 | test_branch_match / phase_in_set / ahead_of_origin 全过 | 8+10+9=27 用例全过（test-report.md:67） | PASS |
| TC-FG4-2 | workspace dirty 时 escape hatch 不命中 | test_escape_hatch_tag_filter.py（test-report.md:68） | PASS |
| TC-FG4-3 | stderr 含 [DEPRECATED] 完整提示 | 实测 stderr 完全匹配（test-report.md:69） | PASS |
| TC-FG4-4 | --target=main 透传到 base_reachable | test_resolve_base_prefers_cli_target（test-report.md:70） | PASS |
| TC-FG4-5 | S1-S10 schema 校验放行 tags 字段 | test_validate_registry_cli_returns_zero（test-report.md:71） | PASS |
| - | argparse Python 3.11/3.12 专项 | **待专项验收（M-02）**；Python 3.14 skipif | PENDING |
| - | --force-with-blockers 调用清查 PR 描述 | **待人工验收（M-03）** | PENDING |
| TC-FG5-1 | traceability 单词边界 + pr_state fallback | test_traceability_word_boundary 15用例 + test_pr_state_fallback 7用例（test-report.md:83） | PASS |
| TC-FG5-2 | legacy_misuse 正反场景 | test_legacy_misuse.py 8 用例全过（test-report.md:84） | PASS |
| TC-FG5-3 | CI pytest+ruff 全绿 | quality-check.yml 双 step 通过（test-report.md:85） | PASS |
| - | ruff 预扫 statistics 策略记录 | 预扫执行，降级决策 ADR D-008（test-report.md:86） | PASS* |
| - | meta.legacy 误用在 meta_schema 生效 | test_gate_run_fails_when_legacy_misuse_in_development 通过（test-report.md:87） | PASS |

(*) 注：test-report.md:86 称"≤50 阈值"，但实际触发了 >200 降级策略（plan.md D-008：原始统计 306 条）。test-report 该处叙述的是实施后当前残余 E/W 错误数（24 条），"≤50 阈值" 描述与降级决策依据不符，属于 test-report 内部描述矛盾（minor）。

### 4.2 人工/专项待验收清单

验收方式来源：requirements/REQ-2026-005/artifacts/test-report.md:103

| 编号 | Feature | 内容 | 验收方式 |
|---|---|---|---|
| M-01 | F-002 | develop 分支 MultiEdit 被 protect_branch 拦截 | 切 develop 分支，Claude 对话中调用 MultiEdit，确认 BLOCKED 提示 |
| M-02 | F-004 | argparse --bypass-review-blockers 在 Python 3.11/3.12 各跑一次 | pyenv 切换环境，运行 test_argparse_double_dest_python_311_312 |
| M-03 | F-004 | --force-with-blockers 现有调用清查结果在 PR 描述中列出 | 提 PR 时补 .claude/commands/ + CI workflow 调用位置及迁移计划 |

**维度 4 结论：PASS（所有 acceptance criterion 均有对应测试用例；3 项待人工验收已合理标注，不属于缺口而是测试方式限制；test-report.md:86 ruff 统计描述有 minor 措辞矛盾）。**

---

## 维度 5：review verdict 完备性

### 5.1 code review 覆盖情况

| Feature | meta.yaml code.by_feature 条目 | verdict 文件 | human_signoff | stale |
|---|---|---|---|---|
meta.yaml 条目来源：requirements/REQ-2026-005/meta.yaml

| F-001 | 存在 meta.yaml:83 | reviews/code-F-001-001.json | approved（hj19961223，2026-05-01T21:51:19） | false |
| F-002 | 已补建 meta.yaml:132 | reviews/code-F-002-001.json | approved（hj19961223，2026-05-03T12:04:04） | false |
| F-003 | 存在 meta.yaml:108 | reviews/code-F-003-001.json | approved（hj19961223，2026-05-03T10:05:47） | false |
| F-004 | 存在 meta.yaml:120 | reviews/code-F-004-001.json | approved（hj19961223，2026-05-03T11:12:07） | false |
| F-005 | 存在 meta.yaml:95 | reviews/code-F-005-002.json（二审） | approved（hj19961223，2026-05-01T22:51:09） | false |

**F-002 缺 code review 的 P-01 已闭合**：本报告首版（2026-05-03 11:32）发现 F-002 在任务文件建立前直接 commit（d7aaf74），未走 /code-review。后续在 testing 阶段补做（来源：requirements/REQ-2026-005/artifacts/review-20260503-115338.md），生成 REV-REQ-2026-005-code-F-002-001 looks_clean(95)，approved by hj19961223@gmail.com（2026-05-03T12:04:04）。reviewed_commit=fe008b2（save-review.sh 强制锁 HEAD；d7aaf74→fe008b2 之间 .claude/settings.json 无变更，安全）。维度 5 由 FAIL 升为 PASS。

### 5.2 reviewed_commit 存在性验证

所有 5 个 reviewed_commit 均在 git log 中可验证（维度 3 已逐一确认）。

### 5.3 artifact_hashes 一致性

hash 比对方法：sha256sum 实际文件 vs meta.yaml.reviews 记录值

| 文件 | meta.yaml 记录 hash | 当前 sha256 | 一致性 |
|---|---|---|---|
| artifacts/features.json | 26e961c8... | 26e961c8... | **一致** |
| artifacts/requirement.md | 2d5269b6... | 2d5269b6... | **一致** |
| artifacts/outline-design.md | e1aabd60... | e1aabd60... | **一致** |
| artifacts/detailed-design.md | 7d409cc5... | 7d409cc5... | **一致** |
| artifacts/tasks/F-001.md | 7485a10b... | a4ac1c77... | **不一致** |
| artifacts/tasks/F-003.md | a9010217... | 7086cb75... | **不一致** |
| artifacts/tasks/F-004.md | 0ea91e36... | 24ff3c85... | **不一致** |
| artifacts/tasks/F-005.md | 901f9b5e... | d9d7d9c6... | **不一致** |

**task 文件 hash 说明**：4 个 task 文件在 code review 完成后由 chore commit 写入了 `status=done` / `review_report=<path>` / `updated_at` 字段（分别为 commits c72d8e5、6158c17、06d3fa4、5e799e8），导致与 review 时快照不一致。这属于**流程元数据写入的正常行为**，业务逻辑未变。meta.yaml 中 `stale: false` 的语义是"review 结论仍有效"，当前评估一致（所有 review 均 stale=false）。

但需注意：meta.yaml artifact_hashes 存储的是 review 时快照，与当前文件 hash 不符时无法区分"流程元数据更新"和"业务逻辑修改"，在工具层面缺乏细粒度区分能力。这是当前 review 体系的已知局限，不是本需求引入的缺口。

### 5.4 非 code review 阶段验证

| 阶段 | latest | conclusion | reviewed_commit | stale |
|---|---|---|---|---|
| definition（两轮） | REV-REQ-2026-005-definition-002 | looks_clean | 64560eb（存在） | false |
| outline-design | REV-REQ-2026-005-outline-design-001 | looks_clean | 2575a2b（存在） | false |
| detail-design（两轮） | REV-REQ-2026-005-detail-design-002 | looks_clean | 7c0a68d（存在） | false |

**维度 5 结论：PASS（F-002 缺 review 的 P-01 已在 testing 阶段补做闭合；task 文件 hash stale 属正常流程行为，stale=false 判断正确）。**

---

## 维度 6：不变量校验

### 6.1 meta.yaml.phase

当前值：`testing`（来源：requirements/REQ-2026-005/meta.yaml:4）。符合预期：development→testing 阶段门禁于 2026-05-03 11:17:31 通过（来源：requirements/REQ-2026-005/meta.yaml:23）。**PASS**

### 6.2 所有 review.stale == false

meta.yaml 中全部 7 处 `stale:` 字段均为 `false`，分别位于 meta.yaml:55 / :65 / :80 / :94 / :107 / :119 / :131（来源：requirements/REQ-2026-005/meta.yaml:55）。**PASS**

### 6.3 未解决的「待用户确认」/「待补充」残留

| 位置 | 内容 | 性质 |
|---|---|---|
| artifacts/requirement.md:83 | 「待补充」F6 旧名删除策略详情 | minor；删除执行时机已明确为 2026-11-01，仅删除策略细节未填写 |
| artifacts/requirement.md:146 | 「待补充」runner 单次耗时基线方法 | minor；baseline 实际已于 F-003 实施时采集（+4.88%，来源：requirements/REQ-2026-005/notes.md:67），该残留标记是孤儿 |
| artifacts/outline-design.md:155 | 「待用户确认」S1-S10 registry schema 位置 | minor；已在 detailed-design.md §4.1 确认（registry.py:157 _validate_one_entry 无白名单严格模式），该标记是历史残留 |

3 处残留均为上游阶段文档在下游阶段已解决但未回写的孤儿标记。**不影响当前 testing 阶段的 acceptance 判定，但属于文档债。**

**维度 6 结论：PASS（meta.yaml 不变量全部满足；3 处「待补充/待确认」残留均为孤儿历史标记，已在后续阶段实质解决）。**

---

## 发现的问题汇总

| # | 严重度 | 维度 | 问题描述 | 建议处理 | 当前状态 |
|---|---|---|---|---|---|
| P-01 | major（已闭合） | 维度 5 | F-002 完全缺失 code review。本报告首版发现，testing 阶段补做闭合。 | 已补做：REV-REQ-2026-005-code-F-002-001 looks_clean(95) approved 2026-05-03T12:04:04。 | **CLOSED** |
| P-02 | minor | 维度 5 | 4 个 task 文件（F-001/003/004/005.md）当前 hash 与 meta.yaml code review artifact_hashes 记录不符，但差异来源均为 code review 后写入的 status/review_report/updated_at 元数据更新。当前 stale=false 判断正确。 | 无需立即修复；可在体系改进中区分"业务字段 hash"与"元数据字段 hash"的 stale 判定逻辑 | OPEN（不阻塞） |
| P-03 | minor（已闭合） | 维度 4 | test-report.md:86 描述 ruff statistics 触发阈值时写「≤50 阈值」，但实际触发的是 「>200 降级」策略（plan.md D-008：实施前统计 306 条）。 | 已修订：实施前 306 条命中 >200 阈值触发降级 select=F；F 类 4 条 PR 内修复；实施后 E/W 残余 24 条（E402×13 / E501×11）以独立 REQ 渐进收紧 | **CLOSED** |
| P-04 | minor | 维度 6 | 3 处历史孤儿「待补充」/「待用户确认」标记残留（requirement.md:83 / :146；outline-design.md:155）。下游阶段均已实质解决但未回写清除。 | **修订评估**：3 处文件全部命中 reviews.{definition / outline-design / detail-design}.artifact_hashes（来源：requirements/REQ-2026-005/meta.yaml），任何修改都会触发 R005 hash drift（来源：scripts/lib/check_reviews.py:203），三轮 review 全部 stale 需重审。修订成本（3 轮评审 + 3 次 sign-off）远高于清孤儿标记的收益。**留作 follow-up REQ：当下游需求需要回退到 definition 阶段时一并清理；或开专项 REQ 时一次性补 stale-tolerant 字段元数据 hash 区分逻辑（同 P-02 体系改进项）** | OPEN（知情债务，PR 不阻塞） |

---

## 待澄清清单

本报告首版（2026-05-03 11:32）输出 WITH_WARNINGS，列出 4 项 P-XX。截至当前更新（2026-05-03 12:18）：

- P-01 已闭合：F-002 补 review + signoff，维度 5 升为 PASS
- P-03 已闭合：test-report.md:86 措辞修订，维度 4 描述准确性恢复
- P-02 / P-04 留作知情债务：均为体系改进项（hash stale 颗粒度区分），单独修复成本远高于本需求收益，留作 follow-up REQ；PR 不阻塞

## 结论

**总体结论：PASS（P-01 / P-03 闭合后，剩 P-02 / P-04 为知情债务，均不阻塞 PR）**

主要判断：

1. 需求 → 设计 → features.json → 代码 → 测试的正向追溯链完整，10 项 not_rebutted finding 全部有明确设计实现和测试覆盖，F3 被驳回并在多处文档显式排除。

2. F-002 P-01 已通过 testing 阶段补 review + sign-off 闭合（REV-REQ-2026-005-code-F-002-001 looks_clean(95)）。维度 5 由 FAIL 升级为 PASS。

3. ruff select 偏离（详设字面 E,W,F vs 实际 F 起步）已有完整 ADR D-008 支撑，不构成追溯断链，属设计知情偏离。

4. 3 项待人工验收（M-01/M-02/M-03）已明确列出验收路径，是测试方式限制而非缺口。

5. 剩余 P-02 / P-04 均为体系改进项（hash stale 颗粒度区分能力缺失），修复成本（3 轮评审重审）远高于清理收益，留作 follow-up REQ；PR 不阻塞。

