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

- **风险 1：自举切换失败导致整体延期** — 第 4 周从旧引擎切到新引擎自举，若新引擎在自举期间出现严重 bug，无明确 fallback 会延迟整体上线。应对：D-009 锁定"3 月兼容期内旧 `/requirement:*` 命令保留实际实现作 fallback；`/requirement:next` 延后到 Plan 6 自举验证通过后才删除（覆盖 spec §4.3 / §15 立即删决策）"。
- **风险 2：sign-off 深防御层删除引入安全回归** — `code_review_signoff.py` tty 校验删除后，AI 可能绕过 sign-off。应对：D-006 锁定 B+C 双层组合——`pre-tool-use-guard.sh` hook 层拦截 AI shell 调 `/workflow:approve` / `/workflow:reject`（与原 isatty 校验同构、搬到 hook 层）+ ai-collaboration 规则三扩展为 sign-off / approval / reject 都是人类专属。
- **风险 3：rollback 归档原路径处理不一致** — spec §11.3 未说明归档后原路径是否 clean、跨父子 rollback 时子目录是否清空、多次 rollback 归档目录如何并存。应对：D-010 锁定 mv 语义 + 子 run 整目录 mv + 每次独立 timestamp 目录 + `.in_progress` atomic 标记；spec §11.3 同步 v2.2 修订。
- **风险 4：父子 run 状态联动语义复杂导致 bug** — 父 paused 时子独立运行（spec §11.2 设计取舍）+ 父 cancel 时子写 `parent_cancelled`（D-004）+ cancel 信号传递机制（D-005 子自检父）+ rollback 跨父子（D-010）= 父子状态联动共 4 类语义分支。应对：阶段 4 code-review-embedded yaml 实现时同步写状态联动 e2e 测试；smoke test 覆盖 cancel graceful + rollback 跨父子两条关键路径。
- **风险 5：主对话上下文压力** — 单需求 30 节点 50-100K token；同时 active 3 需求 150-300K token。Sonnet 200K 用户会触压。应对：`/workflow:save` 检查点续接 + spec §13 已记录。
- **风险 6：jsonl 损坏** — 启动时校验 jsonl 可解析；坏行跳过并 warn；最坏从头跑。Plan 2 `run_state.py` 单测必须覆盖"最后一行损坏"和"`node_started` 无对应 `node_completed`"两种残缺对场景；spec §13 已记录、tech-feasibility R-1 重估优先级。
- **风险 7：bash 节点幂等性假设失效** — bash 节点的副作用（如 git commit）由开发者负责。应对：SKILL.md 强约束 + 节点 idempotent 命令 / UPSERT 等。
- **风险 8：`PHASE_REQUIREMENTS` 删除时间点错位导致门禁空洞** — `scripts/lib/check_reviews.py:57` 的 `PHASE_REQUIREMENTS` 字典被 R001~R005 五个规则使用，是现有门禁的核心依赖；若在新引擎接管 artifact 校验之前删除，phase-transition 门禁会失效，允许未经评审的需求切换阶段。应对：tech-feasibility R-3 重估为 ops 类 medium-high 风险；硬性顺序约束 = D-009 旧命令实现存在期间 `PHASE_REQUIREMENTS` 不能删；阶段 7 清理前必须有迁移验证测试 [待补充] 覆盖 7 条规则的等价语义。

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
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1020

### D-005 sub_workflow 父子 cancel 信号传递（D-004 的实现机制细化）

- **Context**：D-004 锁定"父 cancel → 子写 `parent_cancelled`"语义，但 spec §11.2 没说清"谁写"。Claude Code 主对话默认派 subagent 后阻塞等子返回，主 Claude 没有"中止运行中 subagent"的 API；ToolSearch 验证 `TaskStop({task_id})` 工具存在但 graceful/forceful 语义无公开文档；跨 subagent 文件写权限边界不清。
- **Decision**：父子 cancel 改为"子自检父"模式：(1) 父 Claude 用 `Agent({run_in_background: true})` 派子，不阻塞主对话；(2) 用户 cancel → 父 jsonl 写 `cancel_requested`（事件枚举新增）；(3) 子 subagent 在每个节点边界 poll 父 jsonl，检测到 `cancel_requested` 即自写 `parent_cancelled` 到子 jsonl + graceful 退出；(4) 父等子 graceful 返回或 30s 超时后调 `TaskStop({task_id})` forceful 兜底。子 jsonl 永远由子自身写，没有跨 run 文件写。
- **Consequences**：好——绕开跨 subagent 文件写权限模糊 + TaskStop graceful 不明确两个不确定性；jsonl 追加写本身是 O_APPEND 原子的；spec §11.2 表的"父 run cancel"行得以严谨实现。差——cancel 时延上限 = 30s（poll 间隔）+ 子节点 graceful 退出耗时，非立即生效。
- **时间**：2026-05-08 14:50:00
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1020（v2.1 修订）；requirements/REQ-2026-009/artifacts/tech-feasibility.md:159
- **Plan 落地点**：Plan 2（事件枚举 + run_state.py 新增 `cancel_requested` 写入逻辑）/ Plan 4（smoke test 覆盖 graceful 路径）

### D-006 approval 节点人机鉴别 = hook 拦截 + ai-collaboration 软约束

- **Context**：spec §15 决策"放弃 tty 双校验"删除 `code_review_signoff.py:61` 的 `sys.stdin.isatty()` 校验；但 CLAUDE.md / context/team/ai-collaboration.md 规则三明文禁止 AI 调 sign-off，依赖此 tty 校验做技术拦截。直接删 tty 校验后，AI 在 prompt 注入下可绕过 sign-off。
- **Decision**：B + C 双层组合替代——B 层（技术拦截）：`.claude/hooks/pre-tool-use-guard.sh` Bash case 分支增加 `/workflow:approve` / `/workflow:reject` / `python3 scripts/lib/workflow_approve.py` 检测，命中且非 tty 进程时 `cat >&3` 拒绝消息后 `exit 2`，与原 `code_review_signoff.py:61` isatty 校验同构、只是搬到 hook 层；C 层（软约束）：ai-collaboration.md 规则三从"sign-off 是人类专属"扩展为"sign-off / approval / reject 都是人类专属"，列出新增入口 `/workflow:approve` / `/workflow:reject`。spec §15 反对的是"双重确认链路（cli + tty 两处）"，单一 hook 层校验不属于"双"。
- **Consequences**：好——技术拦截层不丢；spec §15 与 CLAUDE.md 规则三都满足；hook 层校验对 cli script 删除/重构都鲁棒。差——hook 复杂度 +1（约 10-15 行 shell + python helper）；新入口 `workflow_approve.py` / `workflow_reject.py` 仍需 isatty fail-closed 兜底，避免 hook 漏拦。
- **时间**：2026-05-08 14:50:00
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1163；scripts/lib/code_review_signoff.py:61；context/team/ai-collaboration.md:38；requirements/REQ-2026-009/artifacts/tech-feasibility.md:194
- **Plan 落地点**：Plan 2（hook 扩展 + workflow_approve.py / workflow_reject.py + ai-collaboration.md 规则三更新）/ Plan 7（清理 code_review_signoff.py 时确保 hook 已生效）

### D-007 双路径 loader = 内置识别两前缀，不引入 schema 字段

- **Context**：D-002 决策 MVP 期 `requirements/` 与 `runs/` 双轨共存，loader 需要同时识别两个路径前缀。具体实现可选：loader 内置默认识别 / yaml schema 加 `legacy_path: requirements/` 字段 / 集中配置文件 `loader-config.yaml`。
- **Decision**：loader 内置默认识别——`workflow_loader.py` 新增 `_resolve_run_dir(req_id) -> Path`：先 stat `requirements/<req_id>/`，不存在则 stat `runs/<req_id>/`；都不存在抛 `WorkflowError`。yaml schema **不**新增字段，配置文件层也**不**新增 `loader-config.yaml`。3 月兼容期结束后只需删 loader 中"探测 `requirements/`"的 1 行代码即可清理完毕。
- **Consequences**：好——作者写 yaml 时无需思考路径前缀；schema 不污染；3 月兼容期后清理成本最低（改 1 行代码 vs 找全部 yaml 删字段）。差——loader 解析时多一次 stat 调用（性能可忽略）。
- **时间**：2026-05-08 15:00:00
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1109（D-002）；requirements/REQ-2026-009/artifacts/tech-feasibility.md:113
- **Plan 落地点**：Plan 3（`workflow_loader.py` + `workflow-engine` Skill 调 `_resolve_run_dir` 构建 `$ARTIFACTS_DIR` / `$OUTPUT_DIR`；4 种场景单测覆盖）

### D-008 workflow-launcher 关键词冲突仲裁 = 最长匹配 + state tiebreaker

- **Context**：spec §4.2 列出 6 类关键词触发模式（"开个新需求 X" / "跑下代码评审" / "我要发版" / "继续之前的需求" / "approve" / "reject:"），多关键词命中时如何仲裁未明确。例：用户说"approve 这个需求并跑下代码评审"会命中 "approve" + "跑下代码评审"。
- **Decision**：launcher Skill 按 3 步仲裁：(1) state tiebreaker——若有 run 处于 `approval_pending` 状态，优先匹配 `approve` / `reject` 关键词，绕过最长匹配；(2) 最长匹配——所有命中关键词按字符长度倒序，取最长；(3) 兜底 ask——若 ≥2 个等长关键词命中（极小概率），主 Claude 必须 ask 用户消歧。多步连接词（"再" / "接下来" / "and then"）的串行执行能力**不在 MVP 范围**。
- **Consequences**：好——确定性规则；MVP 范围内可覆盖 ≥80% 场景；冗余的 ask 兜底处理边界。差——多意图组合需要分句（"开新需求 + 跑评审"要分两句说）；多步连接词留作 v2 演进。
- **时间**：2026-05-08 15:00:00
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:177；requirements/REQ-2026-009/artifacts/tech-feasibility.md:225
- **Plan 落地点**：Plan 5（`.claude/skills/workflow-launcher/SKILL.md` 写明 3 步仲裁；`reference/keyword-matching.md` 列关键词长度排序；3+ 冲突场景单测）

### D-009 自举失败回退 = 旧命令保留实际实现 + `/requirement:next` 延后删除

- **Context**：spec §4.3 / §15 锁定"`/requirement:next` 立即删除"，其余 8 个 `/requirement:*` 命令"3 月兼容期内别名转 `/workflow:*`"。但本需求 REQ-2026-009 自身在 Plan 6 自举验证（第 4 周起）才用新引擎，Plan 1 合并到第 4 周之间约 2-3 周本需求自身仍依赖 `/requirement:next` 推进；spec §13 风险表也未列自举失败的应对（OQ-C 来源：requirement.md:149）。
- **Decision**：(1) 3 月兼容期内**所有** `/requirement:*` 命令保留**实际实现**（而非仅别名），与新引擎并行运行——`managing-requirement-lifecycle` Skill / `PHASE_REQUIREMENTS` 字典等旧链路 Plan 7 才删；(2) `/requirement:next` 同样保留实际实现，**覆盖 spec §4.3 / §15 "立即删"决策**——延后到 Plan 6 自举验证通过后才进入 Plan 7 清理；(3) Plan 6 自举验证设硬阈值：本需求自身从 tech-research 推到 completed 全程必须用新引擎跑通，过程中任何阶段 fallback 到旧命令视为验证失败 → 阻塞 Plan 7。
- **Consequences**：好——3 月兼容期 = 天然 fallback，自举失败时用户手动切回旧命令推进当前 run；不需新增功能开关 / env var 切换机制；R-3 风险（`PHASE_REQUIREMENTS` 删除时机错位）的硬性顺序约束自然成立——旧命令实现存在期间 `PHASE_REQUIREMENTS` 必然不能删。差——两套代码并存 3 个月，维护成本+1；本需求 Plan 7 清理时间点比 spec 预期晚 ~1.5 周。
- **时间**：2026-05-08 15:00:00（覆盖 spec §4.3 / §15 决策）
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:204；requirements/REQ-2026-009/artifacts/requirement.md:149；requirements/REQ-2026-009/artifacts/tech-feasibility.md:243
- **Plan 落地点**：Plan 5（`/requirement:next` .md 保留 SOP；其他 8 个别名输出 deprecation warning + 3 月兼容期保留实现）/ Plan 6（自举验证 SOP 写"全程禁用旧命令"）/ Plan 7（删除顺序约束 = Plan 6 verification passed → 1 个迭代周期后真删除）

### D-011 F-008 touches 设计回填 = 扩 `tests/e2e/conftest.py` + 清空 historical violations

- **Context**：F-008 task.md / features.json 原 touches 含 `tests/e2e/fixtures/**` 但**未含** `tests/e2e/conftest.py`。subagent 实现时把 conftest.py 写在 `tests/e2e/` 顶层（pytest 标准约束：conftest.py 必须放测试同级或祖先目录才能被 pytest_collect 自动加载，放 `tests/e2e/fixtures/conftest.py` 不会自动激活）；touches_guard.py 把这 2 条写记成 `touches_violations[]`（实现正确，设计 glob 漏写）。
- **Decision**：(1) 设计回填——features.json F-008.touches 扩 `tests/e2e/conftest.py`（在 `tests/e2e/test_sub_workflow_lifecycle.py` 后插入）；tasks/F-008.md frontmatter touches 同步扩。(2) 清空 historical violations——`F-008.receipt.json` 的 `touches_violations[]` 清零（rationale：扩 touches 后这些路径不再越界；留着会让 phase-transition / submit 阶段 GATE-TOUCHES-VIOLATION 误挡，按 gate 语义"任何 violation 都 block"）。(3) 审计可追溯——本 ADR + commit message 详述根因；用户在交互式 Auto Mode 拒绝后批准走"清空 + 写 ADR"通道。
- **Consequences**：好——pytest 标准位置不再被误记越界；GATE-TOUCHES-VIOLATION 在 submit 阶段不会误挡；后续类似 features（含 e2e 测试）的 detailed-design 模板会带 `tests/e2e/conftest.py` glob，避免再犯。差——任何"事后扩 touches + 清 violations"动作都需要 ADR 留痕，流程上比一次设计到位多一步。
- **时间**：2026-05-09 23:10:00
- **来源**：requirements/REQ-2026-009/artifacts/tasks/F-008.md:7-12（原 touches）/ requirements/REQ-2026-009/artifacts/tasks/F-008.receipt.json（2 条 violations）/ pytest conftest.py 自动加载约束（https://docs.pytest.org/en/stable/reference/fixtures.html#conftest-py-sharing-fixtures-across-multiple-files）
- **Plan 落地点**：本轮 F-008 dispatch 闭环（features.json + task.md + receipt.json + plan.md ADR + bookkeeping commit）

### D-012 F-009 touches 设计回填 = 扩 `tests/lib/test_workflow_approve.py` + 清空 historical violations（同 D-011 模板）

- **Context**：F-009 task.md / features.json 原 touches 含 `tests/hooks/test_pre_tool_use_guard.py` / `tests/hooks/fixtures/workflow_approval_inputs.yaml` 但**未含** `tests/lib/test_workflow_approve.py`。F-009 acceptance TC-F9-5 明文要求 `pytest tests/lib/test_workflow_approve.py::test_isatty_fail_closed`（features.json:341），路径已固化在验收脚本里，subagent 实现时按 acceptance 字面量落 `tests/lib/`；touches_guard.py 把这条写记成 `touches_violations[]`（实现正确，设计 glob 漏写）。
- **Decision**：(1) 设计回填——features.json F-009.touches 扩 `tests/lib/test_workflow_approve.py`（在 `tests/hooks/fixtures/workflow_approval_inputs.yaml` 后插入）；tasks/F-009.md frontmatter touches 同步扩。(2) 清空 historical violations——`F-009.receipt.json` 的 `touches_violations[]` 清零（rationale 同 D-011：扩 touches 后路径不再越界；留着会让 phase-transition / submit 阶段 GATE-TOUCHES-VIOLATION 误挡）。(3) 审计可追溯——本 ADR + commit message 详述根因；与 D-011 走完全同构通道。
- **Consequences**：好——CLI isatty 测试用 `tests/lib/` 标准位置不再被误记越界；GATE-TOUCHES-VIOLATION 在 submit 阶段不会误挡；后续类似 feature（hook + CLI 双层）detailed-design 模板可借鉴本 ADR 在 features.json 模板里默认带 `tests/lib/test_<cli>.py` glob。差——同 D-011，事后扩 touches + 清 violations 流程上比一次设计到位多一步。
- **时间**：2026-05-10 10:58:00
- **来源**：requirements/REQ-2026-009/artifacts/tasks/F-009.md:7-15（原 touches）/ requirements/REQ-2026-009/artifacts/features.json#F-009.acceptance[5]（TC-F9-5 路径字面量 `pytest tests/lib/test_workflow_approve.py::test_isatty_fail_closed`）/ requirements/REQ-2026-009/artifacts/tasks/F-009.receipt.json（1 条 violation）/ requirements/REQ-2026-009/plan.md:137（D-011 同构 ADR 模板）
- **Plan 落地点**：本轮 F-009 dispatch 闭环（features.json + task.md + receipt.json + plan.md ADR + bookkeeping commit）

### D-010 rollback 归档语义 = mv 原路径删除 + 子 run 整目录 mv + 每次独立 timestamp 目录

- **Context**：spec §11.3 说"归档 X 及以后产物到 `runs/<id>/.archived/<timestamp>/`"，但未说明三件事：(1) 归档后**原路径**是否清理（保留 / 删除 / stub）；(2) 跨父子 rollback 时子 run 的整个目录 `runs/<child-id>/` 是否清空；(3) 多次 rollback 的归档目录策略（独立并存 vs 追加合并）。OQ-02 来源：requirement.md:134。
- **Decision**：(1) **R1 mv 语义**——`shutil.move(原路径 → .archived/<rollback-ts>/<原相对路径>)`，原路径删除；非 cp 也非 stub；jsonl 截断尾部 mv 为 `<archived>/run-state.jsonl.tail`。(2) **F1 子 run 目录整体 mv**——父 rollback 越过 sub_workflow 节点时，子 run 整目录 mv 到父 `.archived/<rollback-ts>/sub_runs/<child-id>/`；子 run id 释放，下次父 continue 启**新** child id。(3) **T1 每次独立 timestamp 目录并存**——`.archived/2026-05-08T15:00:00+0800/` 与 `.archived/2026-05-08T18:30:00+0800/` 互不覆盖；存储增长线性 N 次 rollback = N 个目录。(4) **`.in_progress` atomic 标记**——rollback 写产物前先创建 `.archived/<rollback-ts>/.in_progress`；mv 全部完成 + jsonl 截断后删该标记；续跑时检测残留标记 → 完成或回退操作，避免被中断造成 partial state。
- **Consequences**：好——X 重跑时 `artifacts/` 干净无文件碰撞；rollback 历史完整可审计；多次 rollback 间互不干扰；中断保护到位。差——归档目录数随 rollback 次数线性增长（v2 后续可加 `/workflow:archive --gc` 清理老归档）；子 run id 不复用增加 id 空间消耗（可忽略，id 内嵌时间戳/uuid）。
- **时间**：2026-05-08 15:10:00
- **来源**：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1032（v2.2 修订）；requirements/REQ-2026-009/artifacts/requirement.md:134；requirements/REQ-2026-009/artifacts/tech-feasibility.md:281
- **Plan 落地点**：Plan 5（`scripts/lib/workflow_rollback.py` 实现 `rollback_run(run_id, to_node, target_id=None)`：拓扑序找产物路径集合 + `shutil.move` mv + 父跨 sub_workflow 时递归 mv 子目录；4 场景单测：单层 R1 / 跨父子 F1 / 多次 T1 / rollback 到 root）
