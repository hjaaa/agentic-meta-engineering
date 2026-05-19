# 20260519-remove-human-signoff · 移除 human sign-off，改为软性人工确认

## 目标

把当前嵌入 code review 的硬性 `human_signoff` 数据字段 + gate 门禁 + CLI/wrapper/skill/命令/测试 全套完整下线，仅保留"用户对当前流程动作的软确认"体验，让 review verdict 回到机器结论单一职责（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md §背景 §目标）。

## 范围

- 包含：
  - **review schema 删字段**：`enums.signoff_decision` / `enums.signoff_source` / `fields.human_signoff` / CR-1 中 `is_signed_off(verdict)` 条件 / CR-4 中 `is_signed_off(verdict) == False` 条件 / CR-8（来源：spec §数据模型变更 §review schema）
  - **删除入口与 wrapper**：`scripts/lib/signoff.py` / `scripts/check-signoff.sh` / `.claude/commands/code-review/signoff.md` / `.claude/skills/code-review-signoff/` / `tests/commands/test_signoff_command.py` / `tests/integration/test_feature_lifecycle_signoff_gate.py` / `tests/lib/test_signoff_no_circular_import.py`（来源：spec §实现边界 §删除或退役）
  - **save_review.py 退化**：移除 `signoff` 子命令 parser 分支 + re-export；保留 `save` verdict 职责（来源：spec §实现边界 §删除或退役）
  - **修改 review gate 判定**：`check_reviews.py` 删除 `SIGNOFF_PASS` / `is_signed_off` / R003/R007 签字检查；`save_review.py` 删除 CR-1/CR-4 对 `is_signed_off` 依赖与 CR-8；`scripts/gates/plugins/review_verdict.py` 与 `review_verdict_ci.py` 沿用新规（来源：spec §实现边界 §修改）
  - **修改文案与 agent 指令**：`feature-lifecycle-manager` 把 "check-signoff wrapper 判定" 改为 "软确认 + review conclusion 判定"；`code-review-report` 模板 "待 sign-off 提示" → "人工确认提示"；`code-quality-reviewer` agent 改为 "reviewer 只输出机器结论"（来源：spec §实现边界 §修改）
  - **workflow 节点改名**：`.claude/workflows/requirement/standard-8phase.yaml` 中 `req-signoff` / `tech-research-signoff` / `outline-design-signoff` / `detail-design-signoff` / `task-signoff` / `test-final-signoff` 6 节点 ID + 依赖 + 文案 全部 `*-signoff` → `*-confirm`；`pr-merged-gate` 保持；`workflow/approve.md` / `reject.md` 文案对齐"人工确认动作"（来源：spec §workflow approval 节点）
  - **文档清理**：`context/team/engineering-spec/specs/2026-04-30-code-review-human-checkpoints.md` / `design-guidance/gate-system-architecture.md` / `context/team/ai-collaboration.md` / onboarding / learning-path / experience / 当前需求 task 文件中"sign-off=approved" 验收项 全面替换（来源：spec §文档清理）
  - **数据迁移**：仓库内当前 active 与可清理 review JSON 中 `human_signoff` 字段删除（不动 review_id / conclusion / score / reviewed_artifacts；process.txt 的 `[signoff]` 时间线保留作历史事件）（来源：spec §review JSON 历史内容）
  - **测试同步**：单元（check_reviews / save_review CR 规则）+ 集成（feature lifecycle 转 done / phase-transition / CI gate）+ 删除 signoff CLI / tty / trivial / 循环导入测试；schema 校验逻辑迁移到非 signoff 测试（来源：spec §测试策略）
  - **顺带修复**（D-001 决策；REQ-2026-014 命名迁移遗漏的 ID 校验回归点）：
    - `scripts/gates/run.py:127` `_REQ_ID_PATTERN` 扩为同时接受新格式 `YYYYMMDD-<slug>[-NN]` 与旧 `REQ-YYYY-NNN`（直接复用 `scripts/lib/requirement_naming.py` 的两类正则）
    - `scripts/gates/plugins/features_schema.py:106` requirement_id 校验同步扩格式
    - 顺带补回归测试：`tests/gates/test_run.py` + `tests/gates/test_features_schema.py` 新增 20260519-remove-human-signoff 等新格式入参 case
- 不包含：
  - workflow 引擎 `approval` 节点类型本身（保留）
  - AI review 自动合并 / 自动转 done（仍需用户对当前流程给出软确认）
  - review conclusion 枚举值 `looks_clean` / `needs_attention` / `blocked` 变更
  - artifact hash drift / schema 合法性 / supersedes 链 / done feature review 覆盖 等质量 gate 变更
  - GitHub PR review / CI 规则（除非现有文档把它们误描述为 human sign-off）
  - 历史已 archived 的 completed 需求 review JSON 的强制迁移（开放问题 §2）[待用户确认]

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | 2026-05-19 |
| tech-research | 2026-05-19 |
| outline-design | 2026-05-20 |
| detail-design | 2026-05-20 |
| task-planning | 2026-05-20 |
| development | 2026-05-22 |
| testing | 2026-05-23 |

## 风险

- **R1：signoff.py re-export 残留** — 删除 `signoff.py` 后 `save_review.py` 若仍引用旧 re-export 会破坏 import。缓解：先删 parser 分支，再跑 import smoke test（来源：spec §风险与缓解）
- **R2：历史 review JSON 漂移** — 删字段可能导致 reviewed_artifacts hash 或 fixture 漂移。缓解：迁移只改 review JSON 不动 reviewed artifacts；fixtures 与期望同步更新（来源：spec §风险与缓解）
- **R3：workflow 节点改名破坏 run-state** — `*-signoff` → `*-confirm` 可能与既有 jsonl run-state 不兼容。缓解：旧 run 保留兼容或只对新 workflow 生效；当前唯一活跃 run（本 REQ）就在 bootstrap，自身可承接（来源：spec §风险与缓解）
- **R4：`needs_attention` 误当成通过** — 软确认语义不清。缓解：feature lifecycle 明确 `needs_attention` 默认不自动 done，除非用户显式接受风险（来源：spec §风险与缓解）
- **R5：文档残留误导** — "AI 禁止签字" 等旧机制说明残留。缓解：实施末尾用 `rg` 残留扫描并逐项分类处理（来源：spec §风险与缓解 §验证命令）

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-000 spec 为权威单源，definition–detail-design 压缩抽取
- **Context**：本需求源 spec `docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md` 已覆盖目标 / 设计原则 / 目标行为 / 数据模型变更 / 实现边界（删除+修改+文档清理）/ 测试策略 / 迁移步骤 / 验证命令 / 风险与缓解 / 开放问题 / 成功标准；与 REQ-2026-014 的 spec 单源压缩模式同构（来源：requirements/REQ-2026-014/plan.md D-000）
- **Decision**：阶段 2-5 产出物（requirement / tech-feasibility / outline-design / detailed-design）对照 spec 抽取相应章节并补缺口（业务术语 / 验收标准 / 模块接口签名 / features.json），不从零撰写。代码契约、删/改清单、测试矩阵以 spec §实现边界 §测试策略 §验证命令 为权威
- **Consequences**：节奏与 REQ-2026-014 对齐，减少重复推导；风险——若 spec 漏写细节（如未定义 features 拆分粒度、未给具体 schema 改动 diff），需在补缺口时显式标 [待用户确认] 而非默默推断
- **时间**：2026-05-19 11:25:00

### D-001 把 REQ-2026-014 命名迁移漏改的 ID 校验回归点纳入本需求范围
- **Context**：bootstrap 后跑 `scripts/gates/run.py --trigger=phase-transition --req=20260519-remove-human-signoff` 直接 reject，原因 `scripts/gates/run.py:127` `_REQ_ID_PATTERN = r"^REQ-\d{4}-\d{3}$"` 仍硬编码旧格式（来源：scripts/gates/run.py:127）；同时扫到 `scripts/gates/plugins/features_schema.py:106` 错误提示也写死"id 格式须为 ^F-\\d{3}$，requirement_id 格式须为 ^REQ-\\d{4}-\\d{3}$"（来源：scripts/gates/plugins/features_schema.py:106）。REQ-2026-014 spec §6.1 列入回归点扫描时遗漏了 gate runner / features_schema plugin
- **Decision**：本期 development 阶段顺带修两点 + 加新格式回归用例。修复原则——复用 `scripts/lib/requirement_naming.py` 已有的 `_LEGACY_REQUIREMENT_KEY_RE` 与 `_NEW_REQUIREMENT_KEY_RE` 两个正则，不要再写一份。当前 definition→tech-research 切换走 process.txt [phase-transition] 兜底（同 REQ-2026-014 `infer_run_id_from_branch` 兜底先例：requirements/REQ-2026-014/notes.md 2026-05-18 00:03:37），不在 definition 阶段提前 patch
- **Consequences**：本需求范围扩到不止 human-signoff（多了 ID 校验回归）；好处——把 REQ-2026-014 的漏改一次性收口，避免后续每个新 REQ 都被 gate runner 拦；风险——若开发期间发现还有第三处漏改，由 D-001 兜底，开发记录列入；scope 微膨胀不触发 plan rollback（与 spec §设计原则"最小可验证路径"一致）
- **时间**：2026-05-19 11:28:00
