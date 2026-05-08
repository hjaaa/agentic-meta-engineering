# REQ-2026-009 · 自定义工作流改造

## 目标

把 17 Skill / 25 Agent / 8 阶段硬编码 / 8 个 `/requirement:*` 命令统一到 yaml-driven 的 workflow 引擎；改阶段顺序只改 1 个 yaml，零代码改动。MVP 锁定 `standard-8phase` + `code-review-embedded` 两套模板，验证 `sub_workflow` 嵌套字段；lite-3phase / hotfix 移到 Post-MVP 第一批。

## 范围

- 包含：
  - workflow yaml schema v2（含 `sub_workflow` 节点类型，8 种节点）+ JSON Schema 校验 + DAG 校验（Plan 1 已合并到 develop, commit 6d55eaf）
  - workflow-engine Skill：拓扑排序 / 节点执行决策表 / `run-state.jsonl` 读写 + RunState 重建 / approval 状态机 + on_reject 重做 / loop 节点（含 `$LOOP_OUTPUT` 变量）/ sub_workflow 节点（创建子 run + 父子状态联动 + 嵌套深度 ≤ 2）
  - `standard-8phase.yaml` 完整化（38 节点 + 8 阶段 prompt 抽到 `.claude/workflows/prompts/`）
  - `code-review-embedded.yaml`（8 critic 并发 + critic 对抗 + 综合裁决）+ 验证 sub_workflow
  - 11 个 `/workflow:*` 命令 + `managing-workflow-runs` 伞形 Skill + `workflow-launcher` 关键词触发 Skill + `/workflow:status` 父子树 + `/workflow:rollback` 跨父子规则
  - 8 个 `/requirement:*` 别名（3 月兼容期；`/requirement:next` 立即删除）+ pre-commit hook 拦截旧引用
  - 自举验证（第 4 周起用新引擎承载本次改造剩余阶段）
  - 阶段 7 清理：删 `PHASE_REQUIREMENTS` / `phase_enum.py` / `code_review_signoff.py` / `/requirement:next`；CLAUDE.md / agentic-engineer-guide.md / 全部 SOP 文档更新；老 `requirements/` → `runs/` 批量 rename 工具
- 不包含：
  - 多 provider 共存（MVP 仅 claude）/ git worktree 强制隔离 / 独立 daemon / HTTP API server / Web Dashboard / Postgres 持久化
  - `lite-3phase` / `hotfix` / `release-cut` / `codex-review-loop` / `pr-feedback-handle` / `extract-experience` / `generate-sop` / `general-assist` 模板（Post-MVP 第一批）
  - `maxBudgetUsd` 节点级硬熔断（Post-MVP）
  - 兼容期到期后旧别名的自动清理 CI 门禁（D-003 锁定为人工清理）

## 里程碑

| 阶段 | 预期完成 | 关键交付 |
|---|---|---|
| definition | 2026-05-08 | requirement.md + 4 项决策（D-001 ~ D-004）+ 5 项待澄清 |
| tech-research | 2026-05-09 | 自举失败回退方案 / sign-off 安全替代 / launcher 关键词冲突仲裁 评估 |
| outline-design | 2026-05-12 | 引擎模块划分 / loader 双路径识别 / 父子状态机时序图 |
| detail-design | 2026-05-15 | 11 个命令接口签名 + features.json + 节点级 prompt 文件清单 |
| task-planning | 2026-05-18 | tasks/ 拆分（≤ 38 节点 + 11 命令 + 别名 + 清理任务） |
| development | 2026-06-22 | Plan 1 已合并；Plan 2-N 按 spec §12 阶段 2-7 顺序推进 |
| testing | 2026-06-26 | AC-01~AC-CLEAN 全部通过 + 自举验证 |

总工期 ~7 周（与 spec §12 锁定一致）。

## 风险

- **风险 1：自举切换失败导致整体延期** — 第 4 周从旧引擎切到新引擎自举，若新引擎在自举期间出现严重 bug，无明确 fallback 会延迟整体上线。应对：tech-research 阶段评估"保留旧 `/requirement:*` 命令实现而非仅别名"作为 fallback，待 OQ-C 用户确认。
- **风险 2：sign-off 深防御层删除引入安全回归** — `code_review_signoff.py` tty 双校验删除后，AI 可能绕过 sign-off。应对：detail-design 阶段与 `/workflow:approve` 命令的人机鉴别逻辑一并设计，hook 拦截 AI shell。OQ-D 待确认。
- **风险 3：rollback 归档原路径处理不一致** — spec §11.3 未说明归档后原路径是否 clean，残留旧产物会让用户混淆 rollback 语义。应对：detail-design 阶段锁定（建议归档后删除原路径）。OQ-02 待确认。
- **风险 4：父子 run 状态联动语义复杂导致 bug** — 父 paused 时子独立运行的设计取舍，加上本需求的 cancel 联动底线（D-004），父子状态联动有 4 种独立分支。应对：阶段 4 code-review-embedded yaml 实现时同步写状态联动 e2e 测试。
- **风险 5：主对话上下文压力** — 单需求 30 节点 50-100K token；同时 active 3 需求 150-300K token。Sonnet 200K 用户会触压。应对：`/workflow:save` 检查点续接 + spec §13 已记录。
- **风险 6：jsonl 损坏** — 启动时校验 jsonl 可解析；坏行跳过并 warn；最坏从头跑（spec §13 已记录）。
- **风险 7：bash 节点幂等性假设失效** — bash 节点的副作用（如 git commit）由开发者负责。应对：SKILL.md 强约束 + 节点 idempotent 命令 / UPSERT 等。

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 MVP 模板范围

- **Context**：spec §1.2 顶部"至少 standard-8phase / lite-3phase / hotfix 三套模板共存"与 §16/§17 决策矩阵"MVP 仅 standard-8phase + code-review-embedded"存在口径冲突。
- **Decision**：MVP 锁定 (b) 二套：`standard-8phase` + `code-review-embedded`（验证 sub_workflow 嵌套字段）；lite-3phase / hotfix 列为 Post-MVP 第一批。
- **Consequences**：好——MVP 工期 7 周可控；差——lite-3phase / hotfix 用户需等待 Post-MVP。
- **时间**：2026-05-08 11:55:53
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1212

### D-002 旧 `requirements/` 目录过渡时机

- **Context**：MVP 期 REQ-2026-009 自身就在 `requirements/REQ-2026-009/`，如果立即批量 rename 到 `runs/` 会引入路径自举风险。
- **Decision**：MVP 期 `requirements/` 与 `runs/` 双轨共存；loader 同时识别两个路径前缀（`requirements/REQ-*` 与 `runs/REQ-*` 都能命中）；阶段 7 再用批量 rename 工具统一迁移。
- **Consequences**：好——降低自举切换风险；差——loader 实现要兼容两套路径，少量复杂度。
- **时间**：2026-05-08 12:00:00
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1109

### D-003 兼容期 3 个月到期后旧别名清理

- **Context**：8 个 `/requirement:*` 别名 3 月兼容期到期后由谁触发清理，spec 未明确。
- **Decision**：选项 (b) 阶段 7 任务清单人工清理，依赖 spec §12 阶段 7 的"pre-commit hook 拦截旧 `/requirement:` 引用"作为底线兜底；不引入"时间型 CI 自动门禁"。
- **Consequences**：好——避免引入额外的时间型自动门禁机制；差——存在兼容期被无限延长的风险，依赖人工纪律。
- **时间**：2026-05-08 12:00:00
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1110

### D-004 父 run paused 时子 sub_workflow run 联动

- **Context**：spec §11.2 明确"父 run paused（用户主动）→ 子 run 不联动，独立运行（设计取舍）"，但未在 cancel 行明示父 cancel 时子是否联动。
- **Decision**：采纳 spec §11.2 设计取舍（子 run 独立运行），并在此基础上明示底线："父 run cancel → 子 run 写 `parent_cancelled` 事件 → cancel"（spec §11.2 cancel 行已经描述了，本需求只是显式确认采用）。
- **Consequences**：好——用户主动 paused 时子 run 可独立完成，避免双向阻塞；父 cancel 时子立即终止，避免孤儿产物；差——paused 期间父 vs 子状态可能瞬时不同步，UI 需要显示 `paused_in_subworkflow` 提示用户。
- **时间**：2026-05-08 12:00:00
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1020,context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1024
