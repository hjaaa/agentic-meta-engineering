# REQ-2026-005 · 门禁系统加固：strict 失效 / Hook 覆盖 / submit 门禁等 10 项缺陷修复

## 目标

修复经对抗式 review-critic 验证后成立的 10 条门禁系统缺陷（F1/F2/F4-F11），消除 strict 模式 warning 被吞、MultiEdit Hook 未被拉起、phase 相邻校验缺失、escape hatch 无 tag 限定、submit 门禁参数链路不通等高优问题，使门禁系统真正能拦截应拦截的场景。

## 范围

- 包含：
  - **FG-001**（F1 + F8）：strict 模式 warning 升级 + reviews_consistency CI 兜底
  - **FG-002**（F2，仅 .claude 侧）：Hook matcher 加 MultiEdit
  - **FG-003**（F4 + F5）：registry applies_when 字段消费 + phase 相邻表校验
  - **FG-004**（F6 + F7）：escape hatch tag 限定 + submit 门禁链路三件套
  - **FG-005**（F9 + F10 + F11）：traceability 收紧 + pr_state 降级路径 + CI build/test/lint
- 不包含：
  - F3（已被 review-critic 驳回，前提错误，不入本需求范围）
  - `.codex/` 双轨同步（项目决策不维护）
  - roadmap.md G2/G3/G5 等本轮未覆盖项（后续需求处理）
  - 门禁 runner 性能优化（即便存在性能瓶颈也不在本次范围；本次只动正确性）

详见 `artifacts/requirement.md`。

## 里程碑

| 阶段 | 预期完成 | 备注 |
|---|---|---|
| definition | 2026-05-01 | reviewer looks_clean 92 (REV-002, signed-off) |
| tech-research | 2026-05-01 | tech-feasibility.md 11 人天估算；schema 不支持本阶段 reviewer，结论入 notes.md |
| outline-design | 2026-05-01 | reviewer looks_clean 86 (REV-001, signed-off)；4 层架构影响视图 + 6 跨组接口契约 |
| detail-design | 2026-05-01 | reviewer looks_clean 92 (REV-002, signed-off)；6 finding 全修；S1-S10 兼容性收口 |
| task-planning | 2026-05-01 | features.json 已在 detail-design 阶段产出，5 个 feature 共 10.7 人天 |
| development | 进行中 | F-002 done (d7aaf74) / F-001 done (12354ca) / 剩 F-003 F-004 F-005 |
| testing | | CI 全绿 + acceptance 验证 |

## development 阶段进度（截至 2026-05-01）

- F-002 / FG-002 `.claude/settings.json` matcher 加 MultiEdit — done（commit d7aaf74）
- F-001 / FG-001 strict 模式 + reviews_consistency CI 兜底 — done（commits f453b67 / 8a3cdc8 / 12354ca），post-dev 验证待补
- F-003 / F-004 / F-005 — pending

## testing 阶段进度（截至 2026-05-03）

- 2026-05-03 11:17 phase-transition development → testing 通过（7 gate 全 PASS，无 warning）
- 2026-05-03 11:22 test-runner 跑出 pytest 375 passed / 0 failed / 1 skipped；CI trigger 非 strict exit=0；strict exit=1（plan.md W002 升阻断符合 F-001 设计）；ruff `--select=F` 0 error；artifacts/test-report.md 落盘
- 2026-05-03 11:32 traceability-consistency-checker 首版 WITH_WARNINGS（6 维 5 PASS / 维度 5 FAIL）；artifacts/traceability-report.md 落盘
- 2026-05-03 11:51 P-01 闭合：F-002 补 /code-review 出 looks_clean(95)；REV-REQ-2026-005-code-F-002-001 落盘
- 2026-05-03 12:04 REV-REQ-2026-005-code-F-002-001 approved by hj19961223@gmail.com
- 2026-05-03 12:10 traceability-report.md 修订为 PASS（P-01 CLOSED；P-02/03/04 minor 不阻塞）
- 待人工验收：M-01（develop 分支 MultiEdit 拦截）/ M-02（argparse Python 3.11/3.12 专项）/ M-03（force-with-blockers 调用清查写到 PR 描述）
- 2026-05-03 12:18 chore commit 47a9d7c：闭合 P-03（test-report.md:86 措辞）+ 修订 P-04 评估为知情债务（hash stale 重审成本远高于清孤儿标记收益，留作 follow-up REQ）
- 2026-05-03 16:13 phase 回退 completed → testing：submit 入口要求 phase ∈ {development, testing}；completed 需要 outcome / completed_at 字段，应在 PR 合并 + lessons 提取后由人工最终切换

## 风险

- **风险 1**：escape hatch / phase 校验改动可能影响现有合法流程，需回归所有已有需求的门禁通过路径（含 REQ-2026-001~003 的 submit 流程）
- **风险 2**：MultiEdit Hook 覆盖依赖 `.claude/settings.json` matcher 语法，需确认 Claude Code 版本行为一致性
- **风险 3**：submit 参数链路涉及多文件协同（submit.md / submit.py / base_reachable.py），改动面较宽
- **风险 4**：FG-003 引入 registry 字段消费可能让 runner 性能退化 > 20%；触发降级方案（保留 plugin 内 changed_files 副本）

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 不复用 REQ-2026-004 序号

- **Context**：REQ-2026-004 曾被分配后通过 git reset 撤销，目录已删除，但序号一旦分配不复用
- **Decision**：直接分配 REQ-2026-005，跳过 004
- **Consequences**：序号不连续（004 空缺），但避免历史混淆
- **时间**：2026-05-01 17:56:29

### D-002 修复颗粒度按 5 组归并

- **Context**：10 条 finding 是否每条独立 feature；归并标准
- **Decision**：5 组（FG-001~FG-005）；FG-001~004 按"同主题共享代码路径"归并；FG-005 按"P2 优先级 + CI workflow 调整窗口"归并
- **Consequences**：feature 状态机粒度变粗但 plan.md 冗余降低；FG-005 三处文件路径不重叠属预期分歧
- **时间**：2026-05-01 18:30:00

### D-003 F4 plugin 内 changed_files 一刀切删

- **Context**：registry applies_when 字段消费上移到 runner 后，plugin 内现有 changed_files 实现是否保留双轨
- **Decision**：一刀切删除（meta_schema / sourcing / index_integrity / plan_freshness 四处）；同步 F9 grandfather 判定也放在 runner 层（不下沉到 plugin）
- **Consequences**：避免双轨漂移；plugin 仅做执行不做过滤决策；F4 + F9 共享单源原则
- **时间**：2026-05-01 18:30:00

### D-004 F6 旧名 deprecation 6 个月按时无条件删

- **Context**：`--force-with-blockers` 旧名删除时机
- **Decision**：保留 alias + 新增 `--bypass-review-blockers`；2026-11-01 无条件删旧名（不绑硬指标避免"忘验证→永远不删"trap）
- **Consequences**：6 个月迁移窗口；命中旧名打 stderr deprecation；到期由 `/schedule` 提醒
- **时间**：2026-05-01 18:30:00

### D-005 F11 ruff 规则集起步仅 [E,W,F]

- **Context**：是否同时引入 I（isort）/ UP（pyupgrade）/ B（bugbear）规则
- **Decision**：起步仅 [E,W,F]；后续以独立需求渐进收紧
- **Consequences**：避免首次 PR 大量 reformat 噪音
- **时间**：2026-05-01 18:30:00

### D-006 F10 CLOSED PR 状态走 INFO 不参与 strict 升级

- **Context**：CLOSED 状态在 strict 模式下是否升级为 FAIL
- **Decision**：走 INFO 级（不升级）；strict 应升级"代码质量类 warning"而非"PR 状态类提示"
- **Consequences**：CLOSED 不阻断 submit；用户决策点保持轻量
- **时间**：2026-05-01 18:30:00

### D-007 F9 历史 REQ 加 meta.legacy=true grandfather 机制

- **Context**：现有 completed REQ（REQ-2026-001~003）执行 submit 时是否被新 traceability 校验回溯卡住
- **Decision**：复用 meta-schema.yaml 已定义的 `legacy: true` 字段；runner 层（filter_gates 阶段）判定
- **Consequences**：历史需求豁免；新需求严格校验；不对称是合理的
- **时间**：2026-05-01 18:30:00

### D-008 ruff --select 起步降级到 F（Spec 偏离决策记录）

- **Context**：详细设计 §5.3 + features.json TC-FG5-3 验收原文写 `ruff check scripts/ --select=E,W,F`。F-005 实施前本地跑 `ruff check scripts/ --select=E,W,F --statistics`，输出 E501=289 / E402=13 / F401=2 / F841=2，总计 306 条历史问题，命中详设阈值表「>200 → 降级 select=F 起步」。
- **Decision**：本次 PR 落地 `pyproject.toml [tool.ruff.lint] select=["F"]` + `quality-check.yml --select=F`，与详设伪码字面不一致；F 类问题 4 条已在本 PR 一并 fix（commit 92c8cb8）。
- **Consequences**：
  - 起步只拦 pyflakes 类（未用变量 / 未用 import）
  - E501 / E402 后续以独立 REQ 渐进收紧（ruff `--select=E` → `--select=W` → `--select=E,W,F` 三步走）
  - 详设字面与实现不一致是临时承担，本 ADR 即唯一决策记录；不修改 detailed-design.md 避免触发 detail-design 阶段 stale 重审
- **时间**：2026-05-01 22:37:25
