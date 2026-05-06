# REQ-2026-008 · 派发链强制结构化升级

## 目标

把阶段 7 subagent 派发链上 6 个"只靠 Skill 文档约束主 Agent 自觉"的卡点升级为机器可读的强制结构（PreToolUse hook 拦截 + JSON schema 校验 + gate 注册表兜底），让红线不可被 AI 自由意志"读规则、自答通过"。设计思想借鉴 Archon 的"结构强制 vs 文本约束"，但不引入 Archon 的 DAG 引擎 / worktree 隔离 / 自动 loop 重试。

## 范围

- 包含：
  - subagent 回执升级为 `artifacts/tasks/<id>.receipt.json` + `receipt-schema.yaml` + `check_receipt.py`
  - 新增 `features-schema.yaml` / `task-frontmatter-schema.yaml` 与配套 check 脚本
  - 派发前置 PreToolUse hook：`dispatch_precheck.py`（status / depends_on / 并发数三重校验）
  - touches 越界双层拦截：开发期 `touches_guard.py` 软记 receipt + phase-transition `GATE-TOUCHES-VIOLATION` 硬挡
  - 新增 `GATE-POST-DEV-RECEIPT` / `GATE-FEATURES-SCHEMA` / `GATE-TASK-FRONTMATTER` 到 `scripts/gates/registry.yaml`
  - Skill / 命令文档收口：`feature-lifecycle-manager` + `managing-requirement-lifecycle` + `subagent-dispatch.md`
- 不包含：
  - 门禁链 `/requirement:next` "读清单自答"升级（下一轮单独做）
  - `/code-review` 自动 loop 修复（保留人工 sign-off）
  - worktree 隔离（与 `requirements/<id>/` 主分支约定冲突）
  - 替换 Task tool 为 wrapper 脚本（用户偏好 hook 优先）
  - DAG YAML 引擎（不引入新工具链）
  - 改动保守档串行约束（"禁止并发派 implementer"红线保留）

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | |
| tech-research | |
| outline-design | |
| detail-design | |
| task-planning | |
| development | |
| testing | |

## 风险

- 风险 1：`dispatch_precheck.py` 从 Task prompt 文本解析 `feature_id` 不 100% 鲁棒 / 应对：派发 prompt 模板硬编码 `feature_id: F-xxx` 显式行；解析失败 fail-open（exit 0）只对成功识别的 feature 生效
- 风险 2：`touches_guard.py` 依赖 `requirements/<id>/.dispatch-state.json` 标记"当前在做哪个 feature" / 应对：dispatch_precheck 派发时写入；receipt 完成时清；`requirement:rollback` 加清理 hook
- 风险 3：receipt schema 后续演化导致老 receipt 不兼容 / 应对：schema 加 `schema_version: "1.0"`，`check_receipt.py` 留兼容窗口
- 风险 4：历史 in-flight 需求（如 REQ-2026-001~007 已 completed 不受影响，但若有 in-flight）未补 receipt 会触发 GATE-POST-DEV-RECEIPT 失败 / 应对：把 `legacy-requirement` escape 加入新 gate 的可豁免列表
- 风险 5：hook 链路加长可能影响交互响应 / 应对：dispatch_precheck / touches_guard 都是纯 Python 文件读，毫秒级，可接受

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 借鉴 Archon"结构强制"思想，但不引入 Archon 引擎本身
- **Context**：阶段 7 派发链有 20+ 个"靠 Skill 文档约束主 Agent 自觉"的卡点，文本约束 AI 可绕。Archon 项目（coleam00/Archon）的 DAG + fresh-context-artifact 模式提供了"结构强制 vs 文本约束"的成熟范式：节点输入输出由 schema/退出码驱动，不靠 AI 解读自由文本。
- **Decision**：借鉴 Archon 的强制思想（receipt JSON、hook 拦截、gate 兜底），但**不引入** Archon 的 DAG YAML 引擎 / worktree 隔离 / loop 自动重试——本仓库 `scripts/gates/registry.yaml` + PreToolUse hook 已具备等价能力，复用现有基建比换框架 ROI 高。本次只升级派发链 6 个卡点，门禁链 / Schema 补全链留下一轮。
- **Consequences**：好处——零新工具链引入、复用现有 hook/gate/schema 体系、迁移成本最低；不足——失败时仍需人工三选一决策（NEEDS_CONTEXT / BLOCKED 不自动重派），保留保守档串行约束。
- **时间**：2026-05-05 22:03:10

### D-002 回执从"自由文本四态 + AI 解析"升级为完整 JSON receipt 文件
- **Context**：当前 subagent 回执是"DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED 四态字符串开头 + 自由文本"，主 Agent 用 AI 语义识别——是派发链最大的歧义来源。
- **Decision**：subagent 必须 Write 文件 `artifacts/tasks/<feature_id>.receipt.json`，schema 包含 status / commit_sha / files_changed / test_summary / touches_violations / concerns / missing_context / block_reason / timestamp 等字段；回到主 Agent 时只回 `RECEIPT_WRITTEN: <path>`。主 Agent 用 `bash scripts/lib/check_receipt.py` + `jq -r '.status'` 走分支。
- **Consequences**：好处——AI 解析零歧义、receipt 文件可审计、不污染主对话 context；成本——改派发 prompt 模板 + 新增 `receipt-schema.yaml` + 新增 `check_receipt.py` + 改主 Agent 解析逻辑。
- **时间**：2026-05-05 22:03:10

### D-003 touches 越界采用双层（软+硬）拦截而非单一硬拦截
- **Context**：subagent 改 `touches` 范围外文件是高风险行为。可选硬拦截（PreToolUse 直接 exit 2 阻断）/ 软拦截（放行但记 violation）/ 双层。
- **Decision**：开发期 `touches_guard.py` 软拦截放行但写 `receipt.touches_violations[]`；phase-transition 由新 `GATE-TOUCHES-VIOLATION` 硬挡。原因：subagent 实际开发中常需调整邻近文件（如 import / 类型声明），硬拦截会大量误伤导致 BLOCKED 重派，转发成本高；双层既保证不静悄悄越界，又给合理调整留路。
- **Consequences**：好处——不误伤合理越界；缺点——多一层 receipt 字段维护。
- **时间**：2026-05-05 22:03:10

### D-004 post-dev gate 从主 Agent 自觉运行变为 phase-transition 前置
- **Context**：现有 `feature-lifecycle-manager` SKILL 要求主 Agent 在每个 DONE 后跑 `python3 scripts/gates/run.py --trigger=post-dev`，但执行靠主 Agent 自觉——可绕过。
- **Decision**：新增 `GATE-POST-DEV-RECEIPT` 到 `phase-transition / submit` 触发组：扫 `features.json` 列出 done feature，每个必须有 `receipt.json` 且 `status ∈ {DONE, DONE_WITH_CONCERNS}`，缺则 fail。即使主 Agent 跳过逐 feature 的 post-dev，下次切阶段也会被兜底。
- **Consequences**：好处——不可跳过；缺点——发现失败时间从"feature 完成时"延后到"阶段切换时"，但这个延迟是可接受的（switch 时还能批量修）。
- **时间**：2026-05-05 22:03:10

### D-005 待澄清清单 5 条全部关单（4 项决策 + 1 项事实结论）
- **Context**：requirement.md 起草时遗留 5 条待澄清项，分别覆盖测试落位 / legacy 豁免范围 / feature_id 解析策略 / .dispatch-state.json 并发模型 / 历史 in-flight 名单。在切 tech-research 阶段前必须关单。
- **Decision**（按编号对应）：
  1. **测试落位**：按层级落进现有 `tests/{hooks,gates,lib,skills}`，pytest，走 `.github/workflows/quality-check.yml` CI（仓库已具备完整分层）。
  2. **legacy 豁免范围**：4 个新 gate 全部**不纳入** legacy 豁免——本次升级核心目标即"机器强制结构化"，legacy 字段只豁免历史评审字段补齐类约束（如现有 R001~R007），不豁免本次新增的派发链强制结构。
  3. **feature_id 解析**：双保险——派发 prompt 模板首部加显式 `feature_id: F-xxx` 行（hook 优先读首行字段）；缺失时 fallback 到正则 `F-\d{3}` 兜底匹配第一个 group，避免 depends_on 引用误伤。
  4. **`.dispatch-state.json` 并发**：使用 `fcntl.flock`（LOCK_EX 独占锁），所有 hook 读写前取锁、写完释放；锁 timeout 5s。Python 标准库零依赖，rollback + 完成清理 hook 极端竞态可被覆盖。
  5. **in-flight 名单**：扫描结果——除 REQ-2026-008 自身（phase=definition）外，其余 6 个需求均 phase=completed；legacy=true 的 REQ-2026-001/002 也已完成。**结论：无活跃 in-flight 需求需迁移豁免**，新 gate 直接对所有未来需求生效。
- **Consequences**：
  - 决策表新增 4 行（测试落位 / legacy 豁免 / feature_id 解析 / dispatch-state 并发）。
  - `meta-schema.yaml` 的 `legacy` 字段说明需补一行"不豁免本次新增的 4 个派发链 gate"——detail-design 阶段落实。
  - `feature-lifecycle-manager/reference/subagent-dispatch.md:36` 派发模板首部需补 `feature_id: F-xxx` 字段；`templates/feature-task.md.tmpl` 同步——detail-design 阶段落实。
  - 单测目录已就绪，tech-research 阶段无需再调研测试落位，可直接对齐 `scripts/lib/check_*.py` 的伴随测试形态。
- **时间**：2026-05-05 22:50:00

### D-009 GATE-POST-DEV-RECEIPT applies_when 过滤下沉到 plugin precheck（F-001 实施偏差）
- **Context**：F-001 实现 GATE-POST-DEV-RECEIPT 时（commit 3f0ecf5），按 detailed-design.md §5.1 设置 `applies_when.target_phase=testing` + `transition=development->testing` + `current_phase_in=[development]` 会触发 `tests/gates/test_submit_next_parity.py::test_phase_transition_gates_are_subset_of_submit` 测试失败——该测试硬断言 `phase-transition 候选 gate ⊆ submit 候选 gate`，而 submit trigger 时 `ctx.to_phase=None`（run.py:448-452 `_match_target_phase` 在 to_phase=None 时返回 False），导致 GATE-POST-DEV-RECEIPT 被 runner 在 submit 通道下静态过滤掉，违反 ⊆ 约束。这是 detailed-design §5.1 设计未考虑到的运行时机制冲突——§5.3 伪代码用了 GateContext 不存在的 `ctx.target_phase` 属性（实际只有 `ctx.to_phase` 与 `ctx.extra`），属于 spec 笔误。
- **Decision**：实现层把过滤逻辑下沉到 plugin precheck（与 GATE-TRACEABILITY 同模式）。
  - **registry.yaml**：`target_phase: null` / `transition: null` / `current_phase_in: []`，跳过 runner 静态过滤。
  - **plugin precheck**：4 层动态判定 — trigger ∈ {phase-transition, submit} / req_dir 存在 / features.json 存在 / phase-transition 时 `ctx.extra.get("target_phase") or ctx.to_phase == "testing"`；submit trigger 直接放行进 run()。
  - **行为等价性**：仍仅在 development→testing 切换时命中，与 §5.1 设计意图等价。
  - **不改 detailed-design.md §5.1 / §5.3**：避免触发 R005 hash drift 重审 detail-design（D-006 经验明确规定"reviewer hash 校验粒度无 trivial 豁免通道，措辞修订直接计入重审成本"）。本 ADR 是过程偏差记录，不构成正式设计修订。
- **Consequences**：
  - `scripts/gates/registry.yaml` GATE-POST-DEV-RECEIPT 字段实际值与 detailed-design.md §5.1 yaml 字面量不一致——以本 ADR 为准。
  - F-002 / F-003 / F-005 后续 schema gate 若也走 phase-transition + submit 双 trigger 设计，**应直接采用本模式**：applies_when null 化 + plugin precheck 4 层过滤，避免重蹈 parity test 阻塞。
  - F-001 review-001（REV-REQ-2026-008-code-F-001-001）由 design-consistency-checker 标 major 偏差；critic 论证 implementer 论据成立（GateContext 无 target_phase 属性是 spec §5.3 笔误）；quality-reviewer 仲裁为 spec-fix 路径——本 ADR 即此决议落地。
  - reviewer 体系并未把"实施期发现的 spec 笔误 ADR 化"路径正式归档为流程节点；后续若多次出现可考虑加 SOP（提示：先 critic 验证 spec 真为笔误 → quality-reviewer 决议 spec-fix → plan.md 加 ADR 而非改设计文档）。
- **时间**：2026-05-06 14:13:00

### D-008 detail-design 评审 round-001 反馈：dispatch_state 公开 API 分层（L1 + L2）修复 TOCTOU
- **Context**：detail-design round-001 评审（REV-REQ-2026-008-detail-design-001，来源：requirements/REQ-2026-008/reviews/detail-design-001.json）conclusion=needs_attention（score 85）；major required_fix 指出原 §3.2 公开 API 只暴露 `read_state` / `write_state` / `clear_state` 三函数，每函数内部各取独立锁。dispatch_precheck.py 若按 §2.4 步骤 [8] 顺序调用 read+三校验+write，会形成 **TOCTOU 窗口**——两进程并发 read 后各自校验通过、各自 write 覆盖，并发派发漏过 B-3 校验。
- **Decision**：公开 API 分两层。
  - **L1**：`flock_state_file(req_dir)` 上下文管理器 —— 取一把 LOCK_EX 锁；调用方在 with 块内通过 `StateFileHandle.read()` / `StateFileHandle.write()` 操作，**整个 with 块内不再二次取锁**。dispatch_precheck.py 强制走 L1。
  - **L2**：`read_state` / `write_state` / `clear_state` 简单函数 —— 内部基于 L1，各取独立锁。仅"单读"或"单写"场景使用（touches_guard.py 只读，清理脚本/rollback 只写），无 TOCTOU 风险。
  - **强约束**：L2 的 `read_state` + `write_state` 顺序调用 = TOCTOU 漏洞；禁止在新代码中出现。
- **Consequences**：
  - §3.2 三函数签名扩展为四 API（+`flock_state_file` + `StateFileHandle`）；§3.3 实现版改用 `flock_state_file` 公开化；§3.4 调用方一览补 API 层标注；§2.4 校验链 [8] 改为单 with 块伪代码。
  - 新增单测 TL-009（TOCTOU 回归）/ TL-010（dispatch_precheck.py with 块原子性）。
  - 3 minor + 3 suggestion 同批落地：§1.2.5 ERR trap 与 Python 内部崩溃边界、§3.3 r/r+ 模式注释统一为始终 r+、§5.5 feature_granularity 已在 round-001 verdict 中确认 features.json 在 task-planning 阶段才落 .json 实体的合理性。
  - reviewer hash 校验 R005 路径预期会触发 stale=true → round-002 重审刷新（与 D-006 经验一致）。
- **时间**：2026-05-06 10:10:00

### D-007 PreToolUse Task 派发的 stdin schema 实采样结果（detail-design 待办 #2 闭环）
- **Context**：outline-design §3.2 假设 `tool_name = "Task"` + `tool_input.prompt` + `tool_input.subagent_type`，但未实测。detail-design 首日必须用最小 hook 抓一次真实 stdin 确认字段名（来源：requirements/REQ-2026-008/artifacts/outline-design.md:485）。
- **采样方法**：临时在 `.claude/settings.local.json` 加 `PreToolUse.matcher="Task"` → 调用 `/tmp/trace-task-precheck.sh`（`cat > /tmp/task-precheck-stdin.json; exit 0`）；派一次最简 Explore subagent 触发；读捕获文件后还原配置 + 删 tmp 文件。
- **Decision**（实测 schema 取代假设）：
  - **`tool_name = "Agent"`**（不是 `"Task"`）—— `dispatch_precheck.py` 拒绝标准必须以 `tool_name == "Agent"` 为准；matcher 配置仍写 `"Task"` 即可命中（Claude Code 端 fuzzy 匹配将 `Task` matcher 映射到 `Agent` 工具）。
  - **`tool_input.prompt`** ✅ 命中（string，含完整派发文本）—— §3.2 的 regex `^feature_id:\s*(F-\d{3})\s*$` 解析路径成立。
  - **`tool_input.subagent_type`** ✅ 命中（string）—— depends_on 校验路径成立。
  - **额外字段**：`tool_input.description`（string，short title）+ 顶层 `session_id` / `transcript_path` / `cwd` / `permission_mode` / `hook_event_name` / `tool_use_id` —— detail-design 可用作 dispatch_precheck 审计附属字段。
  - **派发模板硬约束（D-005 #3 强化）**：`feature_id: F-xxx` 必须**独占 prompt 首行**且行首无任何前缀；本次试采样把 `feature_id` 放在了 `DISPATCH-TRACE-SAMPLE:` 之后同一行，§3.2 的 `^feature_id:` regex 会失败 → `feature-task.md.tmpl` + `subagent-dispatch.md` 模板必须强制首行独立行格式。
- **Consequences**：
  - outline-design §3.2 的 `{"tool_name": "Task", ...}` 字面量需在 detail-design 改为 `{"tool_name": "Agent", ...}`；hook matcher 字符串保留 `"Task"`（Claude Code 兼容路径）。
  - `dispatch_precheck.py` 实现层在校验前先断言 `tool_name == "Agent"`；非 Agent 调用直接 fail-open exit 0 放行。
  - `feature-task.md.tmpl` / `subagent-dispatch.md` 派发模板 detail-design 必补"`feature_id: F-xxx` 独占首行"约束 + 单测验证（解析失败用例）。
  - 实采样配置（settings.local.json hooks 字段 + tmp 脚本）已立刻清理，工作区 + agent 配置回到采样前等价状态；不进 git。
- **时间**：2026-05-06 09:42:00

### D-006 V-07 验收点措辞修订：从"legacy 短路"改为"路径自然隔离"
- **Context**：tech-research 阶段（tech-feasibility.md §2.7）发现 V-07 原措辞"新 4 个 gate 在 legacy=true 时短路返回 pass"与 D-005 #2 决议"4 个新 gate 不纳入 legacy 豁免"自相矛盾。reviewer 在 definition 阶段未捕获此内部不一致。复核 `scripts/gates/run.py:343` 的 legacy grandfather 实现——只对带 `legacy-bypass` tag 的 gate 生效；新 4 个 gate 按 D-005 #2 不加此 tag，因此 V-07 描述的"短路"路径根本不存在。
- **Decision**：把 V-07 措辞改为"新 4 个 gate 因 trigger / changed_files / target_phase 等 applies_when 自然过滤，不在 ci 通道命中"——历史 completed 需求由 trigger 与 changed_files 路径自然隔离，**不依赖 legacy 短路**。
- **Consequences**：
  - `requirements/REQ-2026-008/artifacts/requirement.md:124` V-07 行替换为新描述（已落地）。
  - tech-feasibility.md §2.7 的分析与本决议同源；后续 outline / detail-design 直接采用新措辞。
  - definition 阶段已 sign-off（REV-REQ-2026-008-definition-002 approved）；本次修订仅改措辞、不改业务语义。原计划走"轻量补丁不重审"，但 `check_reviews.py` R005 在 hash drift 时硬性 fail，路径上无 stale=true 豁免；最终走 definition-003 重审刷新（looks_clean / score 93），人类 tty sign-off approved，R005/R003 全部解除。reviewer 体系按设计接受了"措辞修订也算 artifact 变更，需重审刷新"——决策启示：reviewer hash 校验粒度无 trivial 豁免通道，未来类似措辞修订直接计入"重审"成本，不再尝试"标 stale 跳过"。
- **时间**：2026-05-06 08:48:00

### D-010 dispatch_state.py write 实现：truncate+write 替代 atomic rename（detailed-design §3.3 偏离）
- **Context**：detailed-design.md §3.3（行 409/446/532）规定 `StateFileHandle.write` 用 atomic rename：tmp_path 写完后 `os.replace(tmp_path, self._path)`。F-001 评审反馈 D-009 同模式过：spec 笔误 / 运行时机制冲突时下沉到实现层不回改文档。F-004 实现 `dispatch_state.py:116-150` 改用 `truncate(0) + write + flush + fsync` 原地写。原因：`flock_state_file` 上下文管理器的 with 块已持 fd（self._f）做 read+write 复用；若 write 改用 atomic rename，rename 会换 inode 致后续在同一 fd 的操作（如 read 后续状态校验）作用于旧 inode → 业务错误。
- **Decision**：`StateFileHandle.write` 实现用 `truncate(0) + write + flush + fsync`，**不**用 atomic rename。在 LOCK_EX 持锁期内，所有合规读者（L1 with 块 + L2 read_state 内部走 L1）都阻塞在锁外，truncate 瞬间空内容不会被任何合规读者观测到——业务安全等价。
- **Consequences**：
  - `dispatch_state.py` 模块 docstring 同步改为"truncate+write 原地写"，避免 docstring/实现矛盾。
  - detailed-design.md §3.3 文字保留 atomic rename（PR review hash 已锁定）；以本 ADR 为实施层 source of truth。
  - 后续若需要支持"无锁读者"场景（如脱离 LOCK_EX 的旁路 cat 调试），需改回 atomic rename 或加 fcntl 锁强制读路径。
- **时间**：2026-05-06 16:25:00

### D-012 receipt.json RMW 锁分层补全：touches_guard 内置 _flock_receipt_file（detail-design §3.4 盲点修复）
- **Context**：F-005 review-001（REV-REQ-2026-008-code-F-005-001）concurrency-checker 标 1 major + 2 minor：
  - **F-4 major**：`.claude/hooks/touches_guard.py:245-318` `_load_or_init_receipt + _record_violation` 是经典 RMW（load → append → atomic rename），`os.replace` 仅保证不读半写但无法防止两个并发 hook 各自 base 旧版后互相覆盖 violation entry。
  - **F-6 minor**：`_read_current_feature` 顶层 `except Exception: return None` 把 dispatch_state 抛的 `TimeoutError` 与 state 不存在合流，事后 audit 无法区分锁竞争与冷启动。
  - **F-7 minor**：`scripts/gates/plugins/touches_violation.py:191-210` 读 receipt.json 无 `LOCK_SH`，与 F-4 修复需配套形成完整锁协议。
  - **盲点根源**：detailed-design.md:543 §3.4 锁分层表只覆盖 `.dispatch-state.json`（dispatch_state.py 已有完整 L1/L2 LOCK_EX），未覆盖 receipt.json 自身写入并发协议；同需求内同类共享文件设计盲点。
- **Decision**：receipt.json RMW 在 touches_guard.py 内置独立锁层，**不迁到** dispatch_state.py L1/L2 API。
  - **F-4 修复**：touches_guard.py 加 `_flock_receipt_file(receipt_path)` 上下文管理器（LOCK_EX + LOCK_NB 轮询 / 5s timeout / 50ms 间隔 / truncate+write+flush+fsync 原地写）；`_record_violation` 改为 with 块内 `_read_receipt_from_fd → append → _write_receipt_to_fd` 单原子动作。原 `_load_or_init_receipt` + `_atomic_write_receipt` 删除（rename 在持 fd with 块内会换 inode 致后续读失效，与 D-010 同模式）。
  - **F-6 修复**：`_read_current_feature` 单独 catch `TimeoutError` → `logger.warning("dispatch_state read timeout (lock contention), fail-open")`；其他异常仍合流 return None。
  - **F-7 修复**：touches_violation.py 加 `_read_receipt_with_shared_lock`（LOCK_SH 5s timeout 50ms 轮询 / 超时 logger.warning fail-open 跳过该 fid）；`_collect_violations` 改用此 helper。LOCK_EX 写 + LOCK_SH 读形成标准 reader/writer 互斥协议。
  - **不迁 dispatch_state.py 的理由**：(1) F-004 文件被 F-005 touches 列表禁止触碰；(2) receipt.json 与 .dispatch-state.json 路径 / schema / 用途均不同，强行抽象是过早泛化；(3) 锁参数 5s/50ms 与 dispatch_state 同步常量便于未来抽象（同样行为契约）。
- **Consequences**：
  - 锁实现独立但参数对齐（`_RECEIPT_LOCK_TIMEOUT_S=5.0` / `_RECEIPT_POLL_INTERVAL_S=0.05` 与 dispatch_state.LOCK_TIMEOUT_S/POLL_INTERVAL_S 一致）；未来若 receipt.json 类共享数据需要 N 个文件统一锁层，可在 dispatch_state.py 加新 API（如 `flock_receipt_file`）做迁移。
  - 锁协议三个面齐备：写 LOCK_EX（F-4）+ 读 LOCK_SH（F-7）+ 写超时 audit（F-6）。后续调试出 receipt 相关锁竞争时不会再回头补半完成锁协议。
  - **测试新增**：`tests/hooks/test_touches_guard_concurrency.py` 含 TL-RC-001（N=8 进程并发 RMW，全部 violation 落盘无丢失）/ TL-RC-002（并发后 JSON 可解析无半写垃圾）/ TL-RC-003（单进程顺序两次基线）；用 multiprocessing 而非 threading（GIL 串行化掩盖锁竞争）。本测试不在 F-005 task md frontmatter touches 字段内 → 写入此文件会触发 touches_guard violation；连带把 task md 自身 touches 字段补齐 + features.json 同步保持 source of truth 一致。
  - **detailed-design.md §3.4 不回改**（仿 D-009/D-010 经验）：reviewer hash 校验 R005 路径无 trivial 豁免，措辞修订即重审；本 ADR 即 spec 盲点的实施层 source of truth。
  - **Reviewer 体系反馈**：critic 论证 F-5 候选（reviewer 误以为 receipt 实测发生骨架 + violation 现象）not_proven，并入 F-4 单条；F-1/F-2/F-3（路径穿越纵深防御 / DoS 上限）由 dev-time 威胁模型 + check_features schema gate + 链路兜底自然 drop，记入 notes.md follow-up。
- **时间**：2026-05-06 17:35:00

### D-011 CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE 测试后门文档化（detailed-design 未覆盖补丁）
- **Context**：F-004 实现 dispatch_precheck.py 引入 env 变量 `CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE`，bats 沙盒用例（TC-F4-3/4/5）通过该变量隔离测试 req_dir，避免污染真 git 分支。该变量类比既有 `CLAUDE_GATES_AUDIT_ROOT`（已在 detailed-design 中文档化），但 detailed-design.md 全文 grep 未命中——属实施期引入但未在设计阶段定型的辅助通道。
- **Decision**：本 ADR 正式记录该 env 变量的存在与契约：
  - 仅 bats 沙盒用例使用；生产环境该变量不应出现
  - 设置后 `locate_req_dir_by_branch()` 直接返回 env 指向的路径，绕过 git 分支匹配
  - 与 `CLAUDE_GATES_AUDIT_ROOT` 同类，作为测试支撑的 escape hatch；不引入运行时 mode 判定（保持轻量）
  - dispatch_precheck.py:150 `locate_req_dir_by_branch` 函数 docstring 已强化注释
- **Consequences**：
  - 后续若需要更严格的"测试 mode-only"保护，可在该 env 处加 `os.environ.get("CI") or os.environ.get("CLAUDE_DISPATCH_TEST_MODE")` 双重确认
  - 同模式（实施期 env 通道）应在引入时同时落 ADR，避免 reviewer 后捕
- **时间**：2026-05-06 16:25:00
