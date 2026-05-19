---
id: 20260519-remove-human-signoff
phase: tech-research
created_at: 2026-05-19T03:35:00Z
---

# 技术预研 · 20260519-remove-human-signoff

> 设计权威单源同 requirement.md：`docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md`（来源：requirements/20260519-remove-human-signoff/plan.md:62）。本文档对 spec 给出的删/改清单做"可行性 / 工作量 / 风险"维度补缺。

## 0. 总评

**可行性结论：high**。本需求以"删除字段 + 改名节点 + 文案清理 + 数据迁移"为主，不引入新依赖、不改外部契约、不改 review conclusion 枚举（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:30）。所有删/改入口在 spec §实现边界 已精确定位（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:108）。

**总工作量估算**：30 ~ 40 工程小时。分布——schema/CLI/wrapper 退化 8h，文案与 agent 指令 5h，workflow yaml 改名 3h，数据迁移 4h，文档清理 5h，回归测试与残留扫描 5h，D-001 顺带 ID 校验回归 5h，余量缓冲 5h。

## 1. 可行性逐项分析

### 1.1 review-schema.yaml 删字段

- 入口：`context/team/engineering-spec/review-schema.yaml`（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:85）
- 删除项：`enums.signoff_decision` / `enums.signoff_source` / `fields.human_signoff` / CR-1 `is_signed_off(verdict)` 条件 / CR-4 `is_signed_off(verdict) == False` 条件 / CR-8（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:85）
- 保留收紧：required_fixes 非空 → conclusion ∈ {needs_attention, blocked}；score 低于阈值 → conclusion ≠ looks_clean；blocker issue → conclusion = blocked（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:94）
- 可行性：纯 yaml 删块；判定 helper 由 F-002 同步删除
- 风险：schema 字段消失后历史 review JSON 加载需"忽略未知字段"或"批量迁移"（开放问题 §2）；待澄清 C-2

### 1.2 判定 helper 退化

- 入口：`scripts/lib/check_reviews.py` / `scripts/lib/save_review.py` / `scripts/gates/plugins/review_verdict.py` / `scripts/gates/plugins/review_verdict_ci.py`（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:124）
- 删除：`SIGNOFF_PASS` / `is_signed_off` / R003 R007 签字检查（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:125）；save_review CR-1/CR-4 中 `is_signed_off` 依赖 / CR-8（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:126）
- 可行性：现有代码中 `is_signed_off` 是单点函数，调用关系清晰；删后插件 fallback 到 conclusion 判定
- 关键 grep：在 worktree 内验证（开发阶段实测）
- 风险：save_review.py 若仍 re-export `signoff` 入口需同步删（R1，来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:192）

### 1.3 signoff CLI / wrapper / skill / 命令 / 测试删除

- 删除文件清单（7 项）：`scripts/lib/signoff.py` / `scripts/check-signoff.sh` / `.claude/commands/code-review/signoff.md` / `.claude/skills/code-review-signoff/` / `tests/commands/test_signoff_command.py` / `tests/integration/test_feature_lifecycle_signoff_gate.py` / `tests/lib/test_signoff_no_circular_import.py`（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:111）
- 可行性：纯删除；save_review.py 同步删 signoff 子命令 parser 分支与 re-export（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:120）
- 风险：删除顺序——先删 parser 分支再删 signoff.py，再跑 import smoke test（spec §风险与缓解 R1）

### 1.4 feature-lifecycle-manager + code-review-report + code-quality-reviewer

- 入口：`.claude/skills/feature-lifecycle-manager/SKILL.md` / `.claude/skills/code-review-report/SKILL.md` 及模板 / `.claude/agents/code-quality-reviewer.md`（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:127）
- 改动：把 "check-signoff wrapper 判定" 改为 "等待用户软确认 + review conclusion 判定"；"待 sign-off 提示" 改为 "人工确认提示"；reviewer agent 删 "human_signoff 是卡点 B 专属字段" 改为 "reviewer 只输出机器结论"
- 可行性：纯文档/SKILL.md 文案改动；需补 needs_attention 软确认分支语义（spec §目标行为 §代码审查后 第 4 步；待澄清 C-1）
- 风险：feature lifecycle 删 check-signoff.sh 依赖后，转 done 路径需替代——本期采"用户在主对话给软确认 → main agent 触发 lifecycle 进入 done"（C-1 假设方向）

### 1.5 workflow standard-8phase.yaml 节点改名

- 入口：`.claude/workflows/requirement/standard-8phase.yaml`（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:130）
- 改名映射（6 节点）：见 plan.md 范围条目 §workflow 节点改名
- 可行性：节点 ID + 依赖项 + 文案三处都改；用 sed/Edit 替换；接 `pr-merged-gate` 不动
- 风险：旧 run-state.jsonl 含 `*-signoff` 事件时反扫不识别（spec §风险与缓解 R3 + 开放问题 §3）；当前唯一活跃 run（本 REQ）在 bootstrap 节点，jsonl 不含 signoff 事件，无 break 面；待澄清 C-3

### 1.6 文档清理

- 入口：`context/team/engineering-spec/specs/2026-04-30-code-review-human-checkpoints.md` / `context/team/engineering-spec/design-guidance/gate-system-architecture.md` / `context/team/ai-collaboration.md` / onboarding / learning path / experience / 当前需求 task 文件（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:135）
- 改动：把 sign-off 段落改为 "软确认"；2026-04-30 的 spec 保留并加废弃声明（不删，按 D-001 同模 supersedes 链）
- 可行性：以 rg 残留扫描驱动；白名单见待澄清 C-4
- 风险：误清理掉历史记录（spec §风险与缓解 R5）

### 1.7 数据迁移

- 入口：仓库内当前 review JSON `requirements/*/reviews/*.json`（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:102）
- 改动：删 `human_signoff` 字段；不动 review_id / conclusion / score / reviewed_artifacts；`process.txt` 的 `[signoff]` 时间线保留
- 可行性：写一个 one-off 迁移脚本（jq 或 Python json 库）；fixtures 同步更新
- 风险：reviewed_artifacts 含字段 hash 时若误改 → 漂移；只 in-place 删字段 + 重写 JSON（R2 缓解，来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:194）

### 1.8 D-001 顺带：ID 校验回归

- 入口：`scripts/gates/run.py:127` `_REQ_ID_PATTERN` 与 `scripts/gates/plugins/features_schema.py:106` 错误文案 + 正则（来源：scripts/gates/run.py:127）。本期决策见（来源：requirements/20260519-remove-human-signoff/plan.md:68）
- 改动：扩为同时接受 `^REQ-\d{4}-\d{3}$` 与 `^\d{8}-[a-z0-9]+(?:-[a-z0-9]+)*(?:-\d{2})?$`；直接复用 `scripts/lib/requirement_naming.py` 的两个公开正则（`_LEGACY_REQUIREMENT_KEY_RE` / `_NEW_REQUIREMENT_KEY_RE`），通过 `is_legacy_requirement_key()` / `is_new_requirement_key()` 任何一方 True 即合法
- 可行性：纯局部改 + 2 行 import + 2 个 unit test
- 风险：requirement_naming 内 `_NEW_REQUIREMENT_KEY_RE` 当前是私有；若不便复用考虑加公开 helper `is_new_requirement_key(key)`（来源：scripts/lib/requirement_naming.py:17）

## 2. 工作量估算（细分）

| Feature | 范畴 | 工作量 (h) | 复杂度 |
|---|---|---|---|
| F-001 review-schema.yaml 删字段 + 收紧规则注释 | schema | 2 | light |
| F-002 check_reviews.py + save_review.py 退化（含 signoff 子命令删除） | code | 4 | medium |
| F-003 删 signoff CLI + wrapper + skill + 命令 + 3 测试 | delete | 2 | light |
| F-004 review_verdict.py / review_verdict_ci.py plugin 同步 | code | 1 | light |
| F-005 feature-lifecycle-manager + code-review-report + reviewer agent 文案 | doc-code | 4 | medium |
| F-006 standard-8phase.yaml 6 节点改名 + approve/reject 文案 | yaml-doc | 2 | light |
| F-007 文档清理（4 篇 + onboarding + experience + 当前需求 task） | doc | 5 | medium |
| F-008 数据迁移：current review JSON 删 human_signoff | migration | 3 | light |
| F-009 D-001 顺带：gate runner / features_schema 接受新格式 + 测试 | code | 4 | medium |
| F-010 testing：残留扫描 / pytest / scripts/gates/run.py --trigger=ci --strict | test | 4 | medium |
| 余量 | buffer | 5 | — |
| **合计** | | **36** | — |

## 3. 风险（spec §风险与缓解 + 本期补充）

| ID | 风险 | 概率 | 影响 | 缓解 | 来源 |
|---|---|---|---|---|---|
| R-1 | save_review.py 仍 re-export 旧 signoff 入口 → import 错乱 | 中 | 高 | 先删 parser 分支再跑 import smoke test（F-003 顺序约束） | spec:191 |
| R-2 | review JSON 删字段引发 reviewed_artifacts hash 漂移 | 低 | 高 | 迁移只改 review JSON 不动 reviewed_artifacts；fixtures 同步 | spec:194 |
| R-3 | `*-signoff` workflow 节点改名 break 旧 run-state | 低 | 中 | 当前活跃仅本 REQ 在 bootstrap，无 break 面；旧 completed run 不影响 | spec:196 |
| R-4 | needs_attention 被误当作通过 | 中 | 中 | feature-lifecycle-manager 明确 needs_attention 默认不转 done；显式接受风险才继续 | spec:198 |
| R-5 | 文档残留"AI 禁止签字"误导后续开发 | 高 | 中 | testing 末尾 rg 残留扫描分类处理；白名单见 C-4 | spec:200 |
| R-6 | D-001 顺带修可能扫到第三处漏改导致 scope 再扩 | 低 | 低 | testing 残留扫描 + git grep "_REQ_ID_PATTERN" 全仓兜底 | plan.md D-001 |

## 4. 待澄清清单（与 requirement.md C-1~C-4 对应）

直接引用 requirements/20260519-remove-human-signoff/artifacts/requirement.md §待澄清清单 中的 C-1 ~ C-4，本阶段不重复展开。tech-feasibility 视角的备注：

- C-1（needs_attention 是否允许软确认转 done）：建议 detail-design 阶段决定 feature-lifecycle-manager SKILL.md 写法；本期推荐"允许但需用户显式接受风险"
- C-2（历史 completed review JSON 是否全量迁移）：建议本期仅清当前活跃；review-schema 改 "忽略未知字段" 兼容历史（实施成本最低）
- C-3（workflow 节点改名是否兼容旧 run-state.jsonl）：建议不兼容旧 run-state；当前无 break 面
- C-4（残留扫描白名单）：建议 `context/team/experience/*.md` + 历史 spec（加废弃声明）+ `requirements/*/notes.md` 历史记录三类

## 5. 验收 GO/NO-GO

- **结论：GO**
- 依据：spec §成功标准 6 条 + 本文档 §1 全部高可行；R-1~R-6 均有低成本缓解；待澄清 C-1~C-4 不阻塞起步，可在 detail-design 收口
