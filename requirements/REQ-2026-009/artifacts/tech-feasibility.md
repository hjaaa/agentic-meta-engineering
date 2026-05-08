---
id: REQ-2026-009
title: 自定义工作流改造 · 技术可行性评估
created_at: 2026-05-08T17:00:00+0800
phase: tech-research
refs-tech-feasibility: true
---

# REQ-2026-009 · 技术可行性评估

## 1. 引言与评估方法

### 1.1 评估定位

Plan 1（schema + loader）已合并到 develop（commit 6d55eaf）。本预研**不重做** Plan 1 范围内的可行性评估，而聚焦于三个后续问题：

1. Plan 1 交付的接口契约（`workflow_loader.py` / `workflow_schema.json` / `topological_sort.py` / `substitute_vars.py`）能否无缝支撑 Plan 2（引擎执行）、Plan 3（standard-8phase yaml 完整化）、Plan 4（code-review-embedded + sub_workflow 验证）？
2. 把硬编码 8 阶段全量迁移到 yaml-driven 时，哪些地方是真正的坑？
3. 双轨运行期（`requirements/` + `runs/` 共存）的工程量是否被高估或低估？

### 1.2 读取的文件与来源

| 文件 | 作用 |
|---|---|
| `requirements/REQ-2026-009/artifacts/requirement.md` | 需求文档与 AC（来源：requirements/REQ-2026-009/artifacts/requirement.md:1）|
| `context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md` | Spec v2 APPROVED（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:5）|
| `context/team/engineering-spec/plans/2026-05-08-workflow-engine-plan-1-schema-loader.md` | Plan 1 实现细节（来源：context/team/engineering-spec/plans/2026-05-08-workflow-engine-plan-1-schema-loader.md:1）|
| `scripts/lib/check_reviews.py:57-65` | `PHASE_REQUIREMENTS` 硬编码点（来源：scripts/lib/check_reviews.py:57）|
| `scripts/gates/registry.yaml` | trigger / applies_when 字段现状（来源：scripts/gates/registry.yaml:1）|
| `.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md` | 阶段规则文档硬编码点（来源：.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md:1）|
| `.claude/agents/*.md` | Agent description 文本中的阶段隐式绑定（来源：.claude/agents/requirement-bootstrapper.md:3）|
| `.claude/workflows/requirement/standard-8phase.yaml` | Plan 1 已产出的 38 节点 yaml 样例|
| `requirements/REQ-2026-008/artifacts/tech-feasibility.md` | 风格参照与工作量类比（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:1）|
| `requirements/REQ-2026-002/artifacts/tech-feasibility.md` | 门禁系统改造工作量类比（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:14）|

### 1.3 类比参照

- **REQ-2026-002**（统一门禁系统）：实际 27 人天，单人串行（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:14）。本次改造规模约 2.5 倍，性质相近（引擎抽象 + 迁移 + 文档 + 自举验证）。
- **REQ-2026-008**（派发链结构化）：约 10.7 人天（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:743）。功能点密度与 Plan 5（命令体系）类似。

---

## 2. 可行性结论

**feasibility: high**

无 blocker 级阻碍。Spec v2 所有关键设计决策已锁定（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:5），Plan 1 的 loader 接口（`LoadResult` / `workflow_schema.json` / `topological_sort.py`）已通过 TDD 模式落地，后续 Plan 2-4 可直接在此基础上叠加执行层。

主要风险集中在三处：

1. 执行引擎（Plan 2）中 `run-state.jsonl` 的 RunState 重建逻辑，涉及 13 种事件类型的幂等性处理，是整个改造中技术密度最高的环节。
2. sub_workflow 父子状态联动（Plan 4），特别是跨父子 rollback 规则，若 jsonl 损坏或并发写入，状态机会进入不一致。
3. `check_reviews.py` 的 `PHASE_REQUIREMENTS` 字典删除前，双轨共存期需要保证两套入口的行为等价（旧 check_reviews 逻辑 vs. yaml artifact 节点）。

---

## 3. 重点技术评估

### 3.1 Plan 1 接口契约对 Plan 2-4 的支撑能力

**结论：可以支撑，但有两处接口空白需要 Plan 2 补齐。**

Plan 1 交付的接口包括：
- `load_workflow(path) -> LoadResult`：含 workflow dict + Report，校验 14 类 yaml 错误
- `topological_layers(nodes) -> list[list[str]]`：Kahn 算法，输入已展开 depends_on 的节点列表
- `substitute_vars(template, context) -> str`：变量替换 + shellQuote 转义（来源：context/team/engineering-spec/plans/2026-05-08-workflow-engine-plan-1-schema-loader.md:1）

**已足够**：Plan 2 引擎主循环可直接调用 `load_workflow` 做启动校验，调用 `topological_layers` 做层序推进，调用 `substitute_vars` 做节点 prompt 注入。

**两处接口空白**：

（1）`run_state.py` 的 `RunState` 重建接口未在 Plan 1 范围内，Plan 2 必须新建此模块。按 spec §7.1，ReState 依赖"反扫 run-state.jsonl 所有事件"（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:824）——13 种事件类型中，`node_started` 未匹配 `node_completed` 的残缺对是最关键的幂等性判断点。Plan 2 启动前需约定 `RunState.node_outputs: dict[str, str]` 和 `RunState.current_layer_index: int` 的精确语义，否则续跑判断会出错。

（2）`run_artifact_checks.py` 的 artifact 节点 5 种校验接口，Plan 1 只定义了 schema 字段，未实现校验逻辑。Plan 3（standard-8phase yaml 完整化）依赖此接口（每阶段末的 `artifact:` 节点调 `scripts/lib/run_artifact_checks.py`）。Plan 3 必须先确认此模块的 CLI 签名和退出码约定。

**整体判断**：Plan 1 接口契约对 Plan 2-4 的支撑是充分的，两处空白均属已知（在 spec §19.2 中列明，来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1252），不构成阻塞。

### 3.2 执行节点抽象的落地评估（Plan 2 核心）

**结论：节点执行决策表清晰，最高风险点在 loop + fresh_context=true 的 subagent 启停控制。**

Spec §7.2 给出了 10 行决策表（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:796），每种节点形态对应明确的执行方式。在 Claude Code 主对话调度形态下，以下三种形态需要特别关注：

**`loop` 节点的 fresh_context=true**：每轮派一个新 subagent，主 Claude 没有"重置自己上下文"的能力（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:493）。这意味着 loop 节点在 fresh_context=true 时的语义是"每轮独立 subagent 执行 + 主 Claude 汇总输出"，而非主 Claude 自身上下文清空。**坑**：若 loop 内的 `$LOOP_PREV_OUTPUT` 变量引用跨轮数据，需要由引擎在 `gate_message` 构造时显式传入，而不是依赖 subagent 间的上下文继承——这要求 Plan 2 在 loop 节点状态机设计时明确约定 `LOOP_PREV_OUTPUT` 由 `run-state.jsonl` 中的 `loop_iteration_completed.output` 字段反查填充。

**同层并发（multi-Agent 调用）**：spec 约定同层 ≥2 个 agent 节点时，主 Claude 在同一响应里发出 N 个 Agent 工具调用（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:799）。Plan 2 的 SKILL.md 需要明确"当前层 needs_subagent 节点数量检测"的触发逻辑，以及并发返回后的 `layerResults` 混合处理规则（部分失败时的 trigger_rule 传播）。这不是技术不可行，而是实现细节必须在 Plan 2 设计阶段锁定，否则 code-review-embedded 的 8 critic 并发（Plan 4）会出现状态不一致。

**approval 节点的人机鉴别**：spec §15 决策"放弃 tty 双校验"（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1163）。删除 `code_review_signoff.py` 后，`/workflow:approve` 命令成为唯一 approve 入口。OQ-D 待澄清项（来源：requirements/REQ-2026-009/artifacts/requirement.md:155）指出这里存在安全替代缺失——Plan 2 必须在 approval 节点实现前明确 approve/reject 命令是否需要 hook 拦截 AI shell 调用，否则 CLAUDE.md 全局规范中"sign-off 是人类专属动作"的硬约束缺失深防御层。

### 3.3 sub_workflow 嵌套层级与拓扑环检测

**结论：嵌套深度 ≤ 2 的校验已在 Plan 1 的 loader 中实现（AC-07）；拓扑环检测覆盖单 workflow 内，跨 sub_workflow 的循环引用需 Plan 4 补充。**

Plan 1 loader 已校验 sub_workflow 字段的嵌套深度（来源：context/team/engineering-spec/plans/2026-05-08-workflow-engine-plan-1-schema-loader.md:48），对应 AC-07 验收点（来源：requirements/REQ-2026-009/artifacts/requirement.md:121）。

**跨 workflow 循环引用**：若 A.yaml 中有 `sub_workflow: B`，B.yaml 中有 `sub_workflow: A`，当前 loader 的 `topological_layers` 只在单 yaml 内做环检测，无法跨文件检测此类循环引用。这在 MVP 范围（只有 standard-8phase + code-review-embedded 两套模板）内不会触发，但 Plan 4 的三层模板发现机制（bundled → global → project，来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:75）上线后，用户自定义模板可能引入跨文件循环。**建议**：Plan 4 在加载 sub_workflow 时做 parent chain 递归校验（spec §6.4 已提及，来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:566），此校验需要在 loader 的 `load_workflow` 增加可选 `parent_chain` 参数。在 MVP 范围内，两套模板手工确认无循环引用即可，风险低。

### 3.4 迁移期双轨运行的工程量

**结论：工程量被 spec 略微低估，`PHASE_REQUIREMENTS` 的迁移是存量代码中改动量最大的单点。**

当前硬编码点量化（实际 grep 核实）：

| 硬编码点 | 位置 | 改造成本 |
|---|---|---|
| `PHASE_REQUIREMENTS` 字典（7 条规则） | `scripts/lib/check_reviews.py:57-65` | 高——需要 yaml-driven 替代逻辑 |
| 产物必存性检查（分散 8 个 artifact:must_exist 节点） | standard-8phase.yaml 中已翻译 | 低——yaml 已对应 |
| Agent description 文本中的阶段绑定 | `.claude/agents/*.md:3`（8 个 Agent 含"阶段 X"前缀）| 低——description 仅文档，不影响功能 |
| `phase-rules.md` 阶段枚举文档 | `.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md` | 中——需要在阶段 7 更新文档 |
| registry.yaml 中 applies_when 里的 phase 判断 | `scripts/gates/registry.yaml` | 低——gate 的 applies_when 与 yaml 阶段解耦，无需同步改 |

**`PHASE_REQUIREMENTS` 删除的具体坑**：check_reviews.py 的 R001/R002/R003/R004/R005 五个规则全部依赖此字典（字典定义来源：scripts/lib/check_reviews.py:57；R001 引用来源：scripts/lib/check_reviews.py:82）。删除前，双轨期内旧的 gate review_verdict plugin 仍调用 check_reviews.py（来源：scripts/gates/registry.yaml:137）。因此必须在 Plan 3/4 完成后、引擎接管 artifact 校验后，才能安全删除 `PHASE_REQUIREMENTS`——这是阶段 7 清理任务的一个硬前置条件，不能提前。Plan 3 的 `runs/<id>/meta.yaml.phase` 字段仍须兼容旧 check_reviews 校验（因为双轨期老需求还在 `requirements/` 目录）。

**双路径 loader 的实现复杂度**：D-002 决策（来源：requirements/REQ-2026-009/artifacts/requirement.md:105）要求 loader 同时识别 `requirements/REQ-*` 和 `runs/REQ-*` 两个路径前缀。OQ-A 待澄清点建议"loader 内置默认识别，不引入 schema 字段"（来源：requirements/REQ-2026-009/artifacts/requirement.md:141）。实现上，这意味着 `workflow-engine` Skill 在构建 `$ARTIFACTS_DIR` / `$OUTPUT_DIR` 变量时，需要读 `meta.yaml` 的目录位置而非硬编码前缀——约 20-30 行额外逻辑，不复杂，但需要在 Plan 3 的 SKILL.md 中明确。

### 3.5 `/workflow:*` 命名空间与 `/requirement:*` 兼容窗口

**结论：兼容期实现是直接的 slash command 转发，无技术难点；真正的风险是 `/requirement:next` 的立即删除对当前进行中需求的影响。**

8 个 `/requirement:*` 别名（除 `:next` 外）的兼容期实现模式：每个 command 文件保留，正文替换为"调用对应 `/workflow:*` 命令 + 输出 deprecation warning"（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:194）。这是最轻量的实现方式，slash command 文件改动不超过 8 个，每个约 5-10 行。

**`/requirement:next` 立即删除的影响**：当前所有处于活跃阶段的需求（包括 REQ-2026-009 自身）依赖 `/requirement:next` 切换阶段（来源：requirements/REQ-2026-009/artifacts/requirement.md:149）。立即删除后，现有需求必须改用 `/workflow:continue`——但 `/workflow:continue` 的实现属于 Plan 2 范围，必须在 Plan 2 上线后才能安全删除 `/requirement:next`。如果先删除 `:next` 再上线 `:continue`，会有一个短暂的命令空白期，直接影响正在进行的需求。**建议**：在 Plan 5（命令体系）上线并经过自举验证（Plan 6）后，再执行 `/requirement:next` 删除，而不是在 Plan 1 合并时立即删除。

### 3.6 自举验证（Plan 6）的失败回退策略

OQ-C（来源：requirements/REQ-2026-009/artifacts/requirement.md:149）指出 spec §13 风险表未列自举失败的应对。评估：

- 第 4 周开始用新引擎跑剩余阶段，若引擎出现严重 bug，没有明确 fallback 会阻塞整体上线（来源：requirements/REQ-2026-009/artifacts/requirement.md:153）。
- **建议方案**：保留旧 `/requirement:*` 命令的实际实现（而非仅别名），自举失败时可临时切回旧命令链。3 月兼容期内旧实现不删，这已经天然提供了 fallback 能力，只需在 OQ-C 确认时明确"自举失败 = 切回旧命令链，新引擎继续修复"即可。

---

## 4. 风险清单

### R-1：`run-state.jsonl` 损坏导致 RunState 重建失败

| 属性 | 值 |
|---|---|
| category | tech |
| likelihood | medium |
| impact | high |
| 来源 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1132 |

**背景**：spec §13 已识别此风险（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1132）。Plan 1 落地后，loader 已处理 yaml 损坏，但 `run-state.jsonl` 的读写属于 Plan 2 范围，尚未实现。13 种事件类型中，`node_started` 未匹配 `node_completed` 的残缺对（进行中节点中断）需要被正确识别为"重跑"而非"已完成"——若事件序列被截断在奇数行或 JSON 格式不完整，RunState 重建可能错判节点状态，导致跳过应重跑的节点。

**重估优先级（Plan 1 落地后）**：spec §13 描述的"坏行跳过并 warn；最坏退化到从头跑"是当前缓解策略，但"从头跑"对有 approval 节点的 workflow 意味着所有人工卡点都需要重新经过，实际代价较高。Plan 2 的 `run_state.py` 必须实现校验接口并在单测中覆盖"jsonl 最后一行损坏"和"node_started 无对应 completed"两种场景。

**缓解**：Plan 2 在 `run_state.py` 启动时校验 jsonl 可解析 + 修复不完整行；`/workflow:save` 命令在 approval 节点前后自动写检查点；worst-case 退化到最近的 approval 节点而非从头（需要 Plan 2 实现"从最近 approval 点恢复"的 RunState 重建策略，而非总是从头）。

### R-2：sub_workflow 父子状态联动的并发写入冲突

| 属性 | 值 |
|---|---|
| category | tech |
| likelihood | medium |
| impact | high |
| 来源 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:563 |

**背景**：父 run cancel 时，子 run 需要写 `parent_cancelled` 事件到自己的 `run-state.jsonl`（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1020）。若子 run 同时处于活跃执行状态（subagent 正在运行），父 cancel 信号到达时子 jsonl 可能正在被写入，产生并发冲突。Claude Code 主对话单线程特性在一定程度上缓解了这个问题（主 Claude 同时只能执行一个动作），但 multi-Agent 并发场景（8 critic 同层运行）下，多个 subagent 并行写各自的 run-state.jsonl，父 cancel 传播的时序无法保证。

**重估优先级（Plan 1 落地后）**：Plan 4 是第一个真正涉及 sub_workflow 联动的阶段。tech-research 阶段已完成对 Claude Code Task 工具能力的调研（详见 §8 D-T1），结论为：`Agent({run_in_background: true})` + `TaskStop({task_id})` 工具组合存在，但 `TaskStop` 是否 graceful 触发子 subagent 写 `parent_cancelled` 事件**无公开文档保证**。spec §11.2 表格中"子 run 写 `parent_cancelled`"的语义需要修订为：父 Claude **不直接**写子 jsonl，而是子 subagent 自身在节点边界 poll 父 jsonl 的 `cancel_requested` 事件，主动写 `parent_cancelled` + 自然退出（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1020）。

**缓解（决策 D-T1）**：父子状态联动改为"子自检父"模式——
- 父 Claude 用 `Agent({run_in_background: true})` 派子 sub_workflow runner，不阻塞主对话
- 用户 cancel → 父 jsonl 写 `cancel_requested`（事件枚举新增）
- 子 subagent 每个节点边界 poll 父 jsonl，检测到 `cancel_requested` 即写 `parent_cancelled` 到子 jsonl 并 graceful 退出
- 父 Claude 等子返回（graceful 路径）或 30s poll 超时后调 `TaskStop({task_id})` forceful 兜底
- 优势：子 jsonl 由子自己写，无跨 subagent 文件写权限风险；jsonl 追加写本身 O_APPEND 原子性，单行不会被截断

MVP 期（standard-8phase + code-review-embedded 两套模板）嵌套深度 ≤ 2，并发写入场景有限；Plan 4 上线时用 smoke test 验证 `cancel_requested` → 子 `parent_cancelled` 的端到端写入完整性。

### R-3：`PHASE_REQUIREMENTS` 删除时间点错位导致门禁空洞

| 属性 | 值 |
|---|---|
| category | ops |
| likelihood | medium |
| impact | high |
| 来源 | scripts/lib/check_reviews.py:57 |

**背景**：`PHASE_REQUIREMENTS` 被 check_reviews.py 的 R001/R002/R003/R004/R005 五个规则使用（字典定义来源：scripts/lib/check_reviews.py:57；首次引用来源：scripts/lib/check_reviews.py:82）。gate registry 的 `review_verdict` plugin 调用 check_reviews.py（来源：scripts/gates/registry.yaml:137），这意味着 `PHASE_REQUIREMENTS` 是现有门禁体系的核心依赖之一。若在引擎接管 artifact 校验之前删除此字典，phase-transition 门禁会失效，允许未经评审的需求切换阶段。

**重估优先级（Plan 1 落地后）**：这是一个全新识别的风险，spec §13 未列入（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1124）。阶段 7 清理任务（来源：requirements/REQ-2026-009/artifacts/requirement.md:89）将删除 `PHASE_REQUIREMENTS`，必须确保此时新引擎的 artifact 节点已经完整接管了所有原有的评审前置校验。

**缓解**：阶段 7 清理前，编写一个"迁移验证测试"——对照 `PHASE_REQUIREMENTS` 的 7 条规则，逐一确认 standard-8phase.yaml 中对应的 artifact 或 approval 节点已覆盖等价语义；测试通过后才执行删除。删除后立即跑 `scripts/gates/run.py --trigger=phase-transition` 全量回归验证。

### R-4：approval 节点的人机鉴别安全替代缺失

| 属性 | 值 |
|---|---|
| category | security |
| likelihood | low |
| impact | high |
| 来源 | requirements/REQ-2026-009/artifacts/requirement.md:155 |

**背景**：spec §15 决策删除 tty 双校验（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1163），OQ-D（来源：requirements/REQ-2026-009/artifacts/requirement.md:155）指出 CLAUDE.md 全局规范"sign-off 是人类专属动作"的硬约束依赖 tty 校验作为深防御层。删除后，AI 可能在 loop 节点的 prompt 内调用 `/workflow:approve` 绕过人工卡点。

**重估优先级（Plan 1 落地后）**：Plan 1 不涉及 approval 节点执行，此风险在 Plan 2 实现 approval 状态机时成为现实。Plan 2 的 SKILL.md 必须在 approval 节点的实现说明中明确：approve/reject 命令只能由人类 tty 终端触发（可通过 PreToolUse hook 拦截 AI shell 调用 `/workflow:approve`），或通过自然语言路由时有明确的人类意图信号。

**缓解（决策 D-T2）**：B + C 双层组合：
- **B 层（技术拦截）**：`.claude/hooks/pre-tool-use-guard.sh` 的 Bash case 分支增加 `/workflow:approve` + `python3 scripts/lib/workflow_approve.py` 检测 + 非 tty 进程拒绝（与现有 `code_review_signoff.py` 的 `sys.stdin.isatty()` 校验同构，只是把校验位置从 cli script 搬到 hook 层；spec §15"放弃双校验"指的是双重确认链路，单一 hook 层校验不属于"双"）
- **C 层（软约束）**：`context/team/ai-collaboration.md` 规则三从"sign-off 是人类专属动作"扩展为"sign-off / approval / reject 都是人类专属动作"，列出新增入口 `/workflow:approve` / `/workflow:reject`
- 实施时机：Plan 2 实现 approval 状态机时同步落地；Plan 7 清理 `code_review_signoff.py` 时确保 hook 层 B 已生效

### R-5：`/requirement:next` 删除时间点与自举切换的耦合

| 属性 | 值 |
|---|---|
| category | business |
| likelihood | medium |
| impact | medium |
| 来源 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:204 |

**背景**：spec 明确 `/requirement:next` 立即删除（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:204），但 REQ-2026-009 自身的自举验证从第 4 周开始（Plan 6），在此之前的 Plan 2-5 阶段仍需用命令推进本需求。若 Plan 1 合并时同步删除 `:next`，而 `:continue` 尚未实现，会导致本需求推进阶段的命令中断（OQ-C，来源：requirements/REQ-2026-009/artifacts/requirement.md:149）。

**缓解**：在 Plan 5（命令体系）上线并自举验证（Plan 6）通过后，再执行 `/requirement:next` 的实际删除；3 月兼容期内旧实现天然提供 fallback，不需要额外保护。

### R-6：workflow-launcher 关键词冲突仲裁策略未锁定

| 属性 | 值 |
|---|---|
| category | tech |
| likelihood | low |
| impact | low |
| 来源 | requirements/REQ-2026-009/artifacts/requirement.md:145 |

**背景**：OQ-B（来源：requirements/REQ-2026-009/artifacts/requirement.md:145）指出 spec §4.2 的自然语言触发关键词在多关键词同时命中时仲裁策略未明确。MVP 内，触发场景较少（`开个新需求 X` / `继续之前的需求` / `approve` 等），实际冲突概率低。

**缓解**：Plan 5 实现 workflow-launcher Skill 时，采用"最长匹配优先 + 当前 run 状态作为 tiebreaker（approval_pending 时优先匹配 approve）"的策略；detail-design 阶段确认并写入 Skill reference 文档。

---

## 5. 工作量估算

### 5.1 估算依据

- REQ-2026-002 门禁系统（27 人天，单人串行）：核心是"现有散落逻辑 → 统一引擎 + 迁移验证"，与本次性质一致（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:14）。
- REQ-2026-008 派发链（10.7 人天）：hook + schema + gate + 文档收口密度，与 Plan 5（命令体系）类似（来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:743）。
- spec §12 给出 7 周总工期预估（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1120），含 Plan 1 1.5 周。Plan 1 已合并，剩余 5.5 周 = 约 27-30 人天（单人，含休息因子）。
- Plan 1 实际 TDD 模式（task 级 step-by-step）显示单 Task 约 0.3-0.5 人天，7 个 Task 共约 3.5 人天，与 spec 1.5 周预估吻合。

### 5.2 分阶段估算

**Plan 2：workflow-engine Skill（引擎主循环）**

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| `run_state.py`（jsonl 读写 + RunState 重建，含 13 种事件）| 0.5 | 1.5 | 1 | 3 |
| `run_artifact_checks.py`（5 种 artifact 校验）| 0.3 | 0.7 | 0.5 | 1.5 |
| SKILL.md + 拓扑推进主循环（节点执行决策表）| 0.5 | 1.5 | 0.5 | 2.5 |
| approval 状态机 + on_reject 重做循环 | 0.3 | 1 | 0.7 | 2 |
| loop 节点完整执行（含 $LOOP_OUTPUT 变量）| 0.3 | 1 | 0.7 | 2 |
| sub_workflow 节点（父子状态联动 + 深度校验）| 0.5 | 1.5 | 1 | 3 |
| e2e smoke test（e2e-smoke.yaml + nested-smoke.yaml）| 0 | 0.5 | 0.5 | 1 |
| **Plan 2 小计** | **2.4** | **7.7** | **4.9** | **15** |

类比：REQ-2026-002 F-001 runner 骨架 9 人天（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:111）；Plan 2 比 F-001 多 sub_workflow 联动和 approval 状态机，估 15 人天合理。

**Plan 3：standard-8phase yaml 完整化**

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| 38 节点 yaml 审查 + prompt 文件抽取（现有 yaml 已有骨架）| 0.3 | 0.7 | 0.5 | 1.5 |
| 老需求 meta.yaml 的 phase 字段映射逻辑 | 0.2 | 0.5 | 0.3 | 1 |
| 双路径 loader 实现（requirements/ 与 runs/ 并识）| 0.2 | 0.3 | 0.2 | 0.7 |
| AC-E2E 验收（老需求续跑）| 0 | 0.3 | 0.5 | 0.8 |
| **Plan 3 小计** | **0.7** | **1.8** | **1.5** | **4** |

类比：spec 预估 0.5 周（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1074）；考虑双路径 loader 额外工作，估 4 人天合理。

**Plan 4：code-review-embedded yaml + sub_workflow 验证**

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| code-review-embedded.yaml（8 critic + synthesize）| 0.3 | 1 | 0.5 | 1.8 |
| standard-8phase 阶段 7 嵌套调用验证 | 0.2 | 0.5 | 0.5 | 1.2 |
| rollback 跨父子规则测试 | 0.2 | 0.5 | 0.5 | 1.2 |
| **Plan 4 小计** | **0.7** | **2** | **1.5** | **4.2** |

**Plan 5：/workflow:* 命令 + managing-workflow-runs Skill**

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| 11 个 /workflow:* 命令实现 | 0.3 | 1.5 | 0.7 | 2.5 |
| 8 个 /requirement:* 别名（3 月兼容期）| 0 | 0.5 | 0.3 | 0.8 |
| workflow-launcher 关键词触发 Skill | 0.2 | 0.5 | 0.3 | 1 |
| /workflow:status 父子树视图 | 0.1 | 0.5 | 0.3 | 0.9 |
| /workflow:rollback 跨父子规则 | 0.2 | 0.7 | 0.5 | 1.4 |
| **Plan 5 小计** | **0.8** | **3.7** | **2.1** | **6.6** |

类比：REQ-2026-008（10.7 人天，包含 2 hook + 3 schema + 4 gate + 文档收口，来源：requirements/REQ-2026-008/artifacts/tech-feasibility.md:743）；Plan 5 命令体系实现比 REQ-2026-008 轻（无 hook chain），估 6.6 人天合理。

**Plan 6：自举验证**

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| 新引擎承载本需求剩余阶段（第 4 周起）| 0 | 0.5 | 1 | 1.5 |
| **Plan 6 小计** | **0** | **0.5** | **1** | **1.5** |

**Plan 7：清理与文档**

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| 删 PHASE_REQUIREMENTS + phase_enum.py（含迁移验证测试）| 0.2 | 0.5 | 0.5 | 1.2 |
| 删 code_review_signoff.py + /requirement:next | 0 | 0.3 | 0.2 | 0.5 |
| 文档更新（CLAUDE.md / agentic-engineer-guide.md / SOP）| 0 | 1 | 0.3 | 1.3 |
| requirements/ → runs/ 批量 rename 工具 | 0.2 | 0.5 | 0.3 | 1 |
| pre-commit hook 拦截旧 /requirement: 引用 | 0.1 | 0.3 | 0.2 | 0.6 |
| **Plan 7 小计** | **0.5** | **2.6** | **1.5** | **4.6** |

### 5.3 总计

| Plan | design | dev | test | 合计 |
|---|---|---|---|---|
| Plan 1 | - | - | - | 已交付 |
| Plan 2 引擎主循环 | 2.4 | 7.7 | 4.9 | 15 |
| Plan 3 standard-8phase yaml | 0.7 | 1.8 | 1.5 | 4 |
| Plan 4 code-review-embedded | 0.7 | 2 | 1.5 | 4.2 |
| Plan 5 命令体系 | 0.8 | 3.7 | 2.1 | 6.6 |
| Plan 6 自举验证 | 0 | 0.5 | 1 | 1.5 |
| Plan 7 清理与文档 | 0.5 | 2.6 | 1.5 | 4.6 |
| **总计（Plan 2-7）** | **5.1** | **18.3** | **12.5** | **35.9** |

**挂钟工期**：约 5.5 周（单人，含 Plan 1 已交付的 1.5 周，与 spec §12 预估 7 周吻合，来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1120）。Plan 2 是关键路径，Plan 3-4 可在 Plan 2 完成后立即并行启动。

**估算与 spec 偏差说明**：Plan 2 引擎主循环估 15 人天（spec 预估 1.5 周约 7-8 人天，来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1061）。偏差来源：R-1（RunState 重建的幂等性处理）和 R-2（sub_workflow 父子状态联动）在 spec §13 风险表中已识别但未反映到工期，结合 REQ-2026-002 类比估算取更保守值。

---

## 6. 前置条件（上线前必须解决）

1. ~~**OQ-D：approval 节点的人机鉴别安全替代**~~（已锁定 D-T2，详见 §8）——Plan 2 落地时按 B + C 组合实施：hook 层 `/workflow:approve` 校验 + ai-collaboration 规则三扩展。

2. **Plan 2 的 `run_state.py` 接口契约**（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:824）——`RunState.node_outputs` 和 `RunState.current_layer_index` 的精确语义必须在 Plan 2 设计阶段锁定，形成 Plan 3 / Plan 4 可依赖的接口文档，否则续跑逻辑会出现静默错判。

3. **`PHASE_REQUIREMENTS` 迁移验证测试**（来源：scripts/lib/check_reviews.py:57）——阶段 7 清理前必须有一个自动化测试，逐一确认 standard-8phase.yaml 中对应节点已覆盖 `PHASE_REQUIREMENTS` 规则的等价语义。否则删除后门禁会出现空洞。

4. ~~**OQ-A：双路径 loader 的实现细节**~~（已锁定 D-T3，详见 §8）——Plan 3 按 loader 内置识别两前缀实施。

5. ~~**OQ-B：workflow-launcher 关键词冲突仲裁策略**~~（已锁定 D-T4，详见 §8）——Plan 5 按"最长匹配 + state tiebreaker"3 步规则实施。

6. ~~**OQ-C：自举失败回退策略**~~（已锁定 D-T5，详见 §8）——3 月兼容期旧命令保留实际实现作 fallback。

7. ~~**`/requirement:next` 删除时间点**~~（已锁定 D-T5，详见 §8）——延后到 Plan 6 自举验证通过后才进入 Plan 7 清理；spec "立即删"决策被覆盖。

8. ~~**OQ-02：`/workflow:rollback` 归档后原路径处理**~~（已锁定 D-T6，详见 §8）——Plan 5 按 R1 + F1 + T1 实施；spec §11.3 v2.2 修订同步落地。

---

## 7. Blockers

无 blocker 级阻碍。feasibility = high，所有上述前置条件均为"需要在对应 Plan 阶段确认"而非"现在无法推进"。

---

## 待澄清清单

> 以下条目为 tech-research 阶段新增发现，与 requirement.md 中的 OQ-A/B/C/D 对应并补充分析。

1. ~~**[待用户确认] `/requirement:next` 删除时间点**~~（已锁定 D-T5）。

2. ~~**[待用户确认] approval 节点人机鉴别替代方案（OQ-D）**~~（已锁定 D-T2，详见 §8）。

3. ~~**[待用户确认] sub_workflow 父 cancel 信号如何传递给活跃 subagent（R-2）**~~（已锁定 D-T1，详见 §8）。

4. **[待补充] `PHASE_REQUIREMENTS` 迁移验证测试的具体形态**：需要在 detail-design（Plan 7）阶段设计，明确是独立测试文件还是集成到 gate runner 的回归测试。
   - **内容**：独立 pytest 文件 `tests/lib/test_phase_requirements_migration.py`，逐一断言 standard-8phase.yaml 中的 artifact 节点覆盖了等价的评审前置约束（即旧 `PHASE_REQUIREMENTS[phase]` 列出的依赖阶段，在新 yaml 中存在对应 `artifact:must_exist` / `approval` 节点）。
   - **依据**：类比 REQ-2026-002 F-007 round-2 的 registry / audit / state_io 拆分采用了独立 pytest 文件做契约校验（来源：scripts/gates/run.py:78），与本场景的"删除前必须先证明等价"性质一致。
   - **风险**：若 yaml 与测试不同步更新，迁移验证失效；测试通过 ≠ 运行时正确（测试只校验存在性，不校验行为等价），需配合 `scripts/gates/run.py --trigger=phase-transition` 的全量回归。
   - **验证时机**：Plan 7 启动前（删除 `PHASE_REQUIREMENTS` 之前必须有 green 测试）。

---

## 8. tech-research 阶段决策记录

> 本节登记 tech-research 阶段与用户讨论后锁定的设计决策（ADR 风格）。每条决策必须在 plan.md 同步落地为执行项。

### D-T1：sub_workflow 父子 cancel 信号传递改为"子自检父"模式

| 字段 | 值 |
|---|---|
| 决策日期 | 2026-05-08 |
| 决策点 | R-2 风险 / spec §11.2 |
| 状态 | 已锁定 |
| 影响 Plan | Plan 2（jsonl 事件枚举）/ Plan 4（sub_workflow 节点实现） |

**决策内容**：父 Claude **不直接**写子 jsonl，而是把 cancel 信号通过父 jsonl 的 `cancel_requested` 事件外露；子 subagent 在每个节点边界 poll 父 jsonl，检测到该事件后自写 `parent_cancelled` 到子 jsonl 并 graceful 退出。父 Claude 等子返回（graceful）或 30s 超时后调 `TaskStop({task_id})` forceful 兜底。

**调研依据**：Claude Code v2.1.63+ 的 `Agent({run_in_background: true})` + `TaskStop({task_id})` + `TaskOutput({task_id})` 工具组合存在；`TaskStop` schema 可调用但 graceful/forceful 语义无公开文档。"子自检父"绕过：(1) 跨 subagent 文件写权限模糊；(2) `TaskStop` 是否给子 graceful 写入机会的不确定性。

**spec §11.2 修订项**：表格中"父 run cancel | 写 `workflow_cancelled` | 写 `parent_cancelled` 事件 → cancel"中"子 run 写 `parent_cancelled`"的写入主体明确为**子自身**而非父代写；jsonl 事件枚举新增 `cancel_requested`（父侧）。

**Plan 2 落地项**：
1. `run_state.py` 事件枚举新增 `cancel_requested`（父侧）+ `parent_cancelled`（子侧）的写入逻辑
2. `workflow-engine` Skill 的 sub_workflow 节点执行说明明确"用 `Agent({run_in_background: true})` 派子 + 等子返回 / 30s 超时调 `TaskStop`"
3. 子 subagent 在节点边界 poll 父 jsonl 的实现（每节点切换前读父 jsonl 最后 N 行，检测 `cancel_requested`）

**Plan 4 验证项**：smoke test 覆盖父用户 cancel → 子在下一节点边界 graceful 写 `parent_cancelled` 的端到端路径；jsonl 文件追加写 O_APPEND 原子性单测覆盖。

### D-T2：approval 节点人机鉴别 = hook 层技术拦截 + ai-collaboration 软约束

| 字段 | 值 |
|---|---|
| 决策日期 | 2026-05-08 |
| 决策点 | OQ-D / R-4 风险 |
| 状态 | 已锁定 |
| 影响 Plan | Plan 2（approval 状态机）/ Plan 7（清理 code_review_signoff.py） |

**决策内容**：B + C 双层组合替代 spec §15 删除的 tty 双校验。

**B 层（技术拦截）**：`.claude/hooks/pre-tool-use-guard.sh` 的 Bash case 分支增加对 `/workflow:approve` / `/workflow:reject` / `python3 scripts/lib/workflow_approve.py` 的检测，命令源自非 tty 进程时 `cat >&3` 拒绝消息后 `exit 2`。与现有 `code_review_signoff.py:61` 的 `sys.stdin.isatty()` 同构，只是把校验位置从 cli script 搬到 hook 层——spec §15"放弃双校验"指的是双重确认链路（cli + tty 两处），单一 hook 层校验不属于"双"。

**C 层（软约束）**：`context/team/ai-collaboration.md` 规则三从"sign-off 是人类专属动作"扩展为"sign-off / approval / reject 都是人类专属动作"，新增入口列表：`/workflow:approve`、`/workflow:reject`、`python3 scripts/lib/workflow_approve.py`、`python3 scripts/lib/workflow_reject.py`。

**Plan 2 落地项**：
1. `pre-tool-use-guard.sh` 的 Bash case 分支扩展（约 10-15 行 shell + python helper）
2. `workflow_approve.py` / `workflow_reject.py` 实现 `sys.stdin.isatty()` 双重校验（hook 漏拦时仍能 fail-closed）
3. ai-collaboration 规则三文档同步更新

**Plan 7 清理项**：删除 `code_review_signoff.py` 时确保 `pre-tool-use-guard.sh` 的 hook 校验已生效；CLAUDE.md / ai-collaboration 规则三落地的版本号 ≥ 删除提交。

### D-T3：双路径 loader = 内置识别两前缀，不引入 schema 字段

| 字段 | 值 |
|---|---|
| 决策日期 | 2026-05-08 |
| 决策点 | OQ-A / D-002 双轨共存 |
| 状态 | 已锁定 |
| 影响 Plan | Plan 3（standard-8phase yaml + loader 适配） |

**决策内容**：loader 解析 yaml 引用的 `<id>` 时，按 `requirements/<id>/` → `runs/<id>/` 顺序探测，命中即用。yaml schema **不**新增 `legacy_path` 字段，配置文件层也**不**新增 `loader-config.yaml`。3 月兼容期结束后只需删 loader 中"探测 `requirements/`"的 1 行代码，无 yaml 文件清理负担。

**理由**：MVP 范围仅 2 个路径前缀，loader 内置探测逻辑短（约 5 行），与 schema 配置/外部配置文件相比，作者负担最低 + 清理成本最低；spec D-002 决策"双轨共存"本身就要求 loader 是统一识别入口，schema 字段化反而把"双轨"语义泄漏到每一个 yaml 文件。

**Plan 3 落地项**：
1. `workflow_loader.py` 新增 `_resolve_run_dir(req_id) -> Path`：先 stat `requirements/<req_id>/`，不存在则 stat `runs/<req_id>/`；都不存在抛 `WorkflowError`
2. `workflow-engine` Skill 在构建 `$ARTIFACTS_DIR` / `$OUTPUT_DIR` 变量时调 `_resolve_run_dir` 而非硬编码前缀
3. 单测覆盖 4 种场景：仅 `requirements/` 存在 / 仅 `runs/` 存在 / 都存在（取 `requirements/` 优先）/ 都不存在

### D-T4：workflow-launcher 关键词冲突 = 最长匹配 + state tiebreaker

| 字段 | 值 |
|---|---|
| 决策日期 | 2026-05-08 |
| 决策点 | OQ-B / spec §4.2 |
| 状态 | 已锁定 |
| 影响 Plan | Plan 5（workflow-launcher Skill） |

**决策内容**：launcher Skill 的关键词仲裁规则按以下顺序判定：
1. **state tiebreaker**：检测当前是否有 run 处于 `approval_pending` 状态——是则优先匹配 `approve` / `reject` 关键词，绕过最长匹配
2. **最长匹配**：所有命中关键词按匹配字符长度倒序排序，取最长的关键词对应的 `/workflow:*` 命令
3. **兜底 ask**：若有 ≥2 个等长关键词命中（极小概率），主 Claude 必须 ask 用户消歧

多步连接词（"再" / "接下来" / "and then"）的串行执行能力**不在 MVP 范围**——属于 v2 演进项（如有需要再加）。

**Plan 5 落地项**：
1. `.claude/skills/workflow-launcher/SKILL.md` 写明上述 3 步仲裁规则（5-10 行 SOP）
2. `reference/keyword-matching.md` 列出 spec §4.2 全部关键词的字符长度排序（avoid 字符串解析时的 ambiguity）
3. 单测覆盖 ≥3 个冲突场景：("继续这个新需求"=继续优先) / ("approve 这个需求并跑代码评审"=approval_pending 时 approve 优先) / ("跑下代码评审"=单意图直通)

### D-T5：自举失败回退 = 旧命令保留实现，3 月兼容期 = 天然 fallback；`/requirement:next` 延后删除

| 字段 | 值 |
|---|---|
| 决策日期 | 2026-05-08 |
| 决策点 | OQ-C / R-3 / spec §4.3 |
| 状态 | 已锁定（**覆盖 spec "立即删 `/requirement:next`" 决策**） |
| 影响 Plan | Plan 5（命令体系）/ Plan 6（自举验证）/ Plan 7（清理） |

**决策内容**：
- 3 月兼容期内**所有** `/requirement:*` 命令保留**实际实现**（而非仅别名转发到 `/workflow:*`），与新引擎并行运行
- `/requirement:next` 不再"立即删"——延后到 Plan 6 自举验证通过后才进入 Plan 7 清理
- Plan 6 自举验证设硬阈值（详见 Plan 6 设计稿）：本需求自身从 `tech-research` 推到 `completed` 全程必须用新引擎跑通，过程中任何阶段 fallback 到旧命令视为验证失败 → 阻塞 Plan 7
- 自举失败时，用户手动调旧命令推进当前 run 即可，新引擎在 Plan 6 内迭代修复

**与 spec §4.3 / §15 关系**：spec 表"`/requirement:next` 处理 = 别名（3 月兼容期）"已**修订为"实现保留 + 别名（3 月兼容期）"**——别名仅用于 8 个非 `:next` 命令；`:next` 在 Plan 6 验证完成前保持原实现。

**Plan 5 落地项**：
1. 8 个 `/requirement:*` 命令（除 `:next`）的 .md 文件正文替换为"调用对应 `/workflow:*` 命令 + 输出 deprecation warning（3 月兼容期内保留）"
2. `/requirement:next` .md 保留原 SOP（继续走 `managing-requirement-lifecycle` Skill）
3. `managing-requirement-lifecycle` Skill 不动，与新 `managing-workflow-runs` Skill 并行存在

**Plan 6 落地项**：自举验证 SOP 显式写"全程禁用旧命令"，任何 fallback 命中即 verification failed。

**Plan 7 清理项**：删除 `/requirement:next` + `managing-requirement-lifecycle` Skill + `PHASE_REQUIREMENTS` 等旧实现的硬性顺序约束 = Plan 6 verification passed → 旧命令的 deprecation warning 升级为 hard error → 1 个迭代周期后真删除。

### D-T6：rollback 归档语义 = mv 原路径 + 子 run 目录整体 mv + 每次独立 timestamp 目录

| 字段 | 值 |
|---|---|
| 决策日期 | 2026-05-08 |
| 决策点 | OQ-02 / spec §11.3 |
| 状态 | 已锁定（**spec §11.3 同步 v2.2 修订**） |
| 影响 Plan | Plan 5（`/workflow:rollback` 命令实现） |

**决策内容**：

1. **R1 单层 run 归档语义**：`/workflow:rollback <run-id> --to-node=X` 执行时，X 节点及之后所有产物用 `mv` 移到 `.archived/<rollback-ts>/<原相对路径>`，**原路径删除**。jsonl 自身按 §11.3 step 1 截断到 X 之前后，被截断的事件流也归档到同一 `.archived/<rollback-ts>/run-state.jsonl.tail` 便于事后审计。
   - 优点：实现最简；X 重跑时 `artifacts/` 目录干净，无文件碰撞；多次 rollback 的历史完整保留
   - 用户 mental model：`.archived/` 是"rollback 时间机器"，每个时间戳目录是一个完整快照

2. **F1 跨父子 rollback 时子 run 目录处理**：父 rollback 越过 sub_workflow 节点时，子 run 的整个目录 `runs/<child-id>/` **完整 mv** 到父的 `.archived/<rollback-ts>/sub_runs/<child-id>/`。子 run id 释放，下次父 continue 重启 sub_workflow 节点时**生成新的 child run id**（不复用旧 id）。
   - 子 run id 的内嵌时间戳/uuid 保证跨 rollback 不混淆历史
   - 子 run 自己的 jsonl 也整体进父归档，避免子 run 留半残目录

3. **T1 多次 rollback 归档策略**：`.archived/` 下每次 rollback 独立 timestamp 子目录并存，**互不覆盖**：
   ```
   runs/<id>/.archived/
     ├── 2026-05-08T15:00:00+0800/
     │   ├── artifacts/...（第一次 rollback 时归档）
     │   ├── run-state.jsonl.tail
     │   └── sub_runs/<child-id-1>/...
     ├── 2026-05-08T18:30:00+0800/
     │   ├── artifacts/...（第二次 rollback 时归档）
     │   └── run-state.jsonl.tail
     └── ...
   ```
   - 存储增长：N 次 rollback = N 个目录（线性，可接受）
   - 配合 `/workflow:archive --gc` 命令（v2 后续可加）做老归档清理

**spec §11.3 同步修订**：
- 把 step 2 "归档 X 及以后产物到 `runs/<id>/.archived/<timestamp>/`" 明确为 mv 语义（非 cp / 非 stub）
- 跨父子第 4 条 "子 run 的产物归档到父 run 的 `.archived/` 目录" 升级为子 run 整目录 mv + 子 run id 不复用
- 新增 step 0 说明 timestamp 目录每次独立、并存策略

**Plan 5 落地项**：
1. `scripts/lib/workflow_rollback.py` 实现 `rollback_run(run_id, to_node, target_id=None)`：
   - 按拓扑序找 X 之后的所有节点 ID 列表
   - 计算这些节点写出的产物路径集合（参考 yaml 节点的 `artifact:` 字段 + `output_capture:` 字段）
   - 创建 `.archived/<rollback-ts>/`，用 `shutil.move` 整体 mv
   - 截断 jsonl，被截断尾部 mv 为 `<archived>/run-state.jsonl.tail`
   - 父 run 跨 sub_workflow 时递归处理子 run 目录
2. 单测覆盖 4 场景：单层 R1 / 跨父子 F1 / 多次 T1 / rollback 到 root（全归档）
3. `/workflow:rollback` slash command 文件 + reference/rollback-semantics.md 文档同步

**风险**：rollback 进行中如果用户中断（Ctrl-C），原路径文件可能已 mv 一半。Plan 5 实现 atomic rollback：先把所有目标产物收集 → 写 `.archived/<ts>/.in_progress` 标记 → 全部 mv 完成后删 `.in_progress` → 截断 jsonl。续跑时检测残留 `.in_progress` 标记 → 完成或回退操作。

