---
id: REQ-2026-009
title: 自定义工作流改造
created_at: 2026-05-08T11:55:53+0800
refs-requirement: true
---

# REQ-2026-009 · 自定义工作流改造

## 背景

当前体系把 8 阶段需求生命周期硬编码在多处（`meta-schema.yaml:38-47` 单一事实源已配置化，但 `check_reviews.py:57-65` 的 `PHASE_REQUIREMENTS` 仍硬编码、产物必存性散落 8 个 checker、Agent ↔ 阶段绑定靠 description 文本隐式绑定）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:31）。这导致三类痛点：(1) 不能支持轻量需求（lite-3phase）/ 紧急修复（hotfix）等流程；(2) "阶段→产物→门禁→Agent" 绑定散落 5+ 文件、易漂移；(3) `/requirement:*` 命名空间绑死，非需求 workflow（codex review-loop / release / extract-experience）无处挂载（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:38）。

参考 Archon（OpenAI/Anthropic 双 provider DAG workflow 引擎），把硬编码体系改造为 **DAG yaml-driven + 统一 `/workflow:*` 入口 + 多模板共存** 的可配置引擎，但保留 Claude Code 主对话调度形态、不引入独立 daemon / Postgres / HTTP server / Web Dashboard（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:17）。

设计稿当前状态 `APPROVED — schema 决策全锁定，进入 writing-plans`（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:5）。Plan 1 (schema + loader) 已合并到 develop（git 提交 6d55eaf）。

## 目标

- 主目标：把 17 Skill / 25 Agent / 8 阶段硬编码 / 8 个 `/requirement:*` 命令统一到一个 yaml-driven 的 workflow 引擎；改阶段顺序只改 1 个 yaml，零代码改动（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:11）。
- 次要目标：
  - 至少 `standard-8phase` + `code-review-embedded` 两套模板共存，验证 `sub_workflow` 嵌套字段（v2 锁定 MVP 范围；来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1212）。lite-3phase / hotfix 列为 Post-MVP 第一批（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1112）。
  - 11 个 `/workflow:*` 命令覆盖 run / list / status / continue / save / approve / reject / cancel / rollback / submit / archive（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:159）。
  - 跨会话恢复确定性：任意中断点 `/workflow:continue` 自动续跑，无需用户告诉"刚才到哪"（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:51）。
  - 验证机制可组合：`output_format / when / approval / bash / critic` 五种 lego 自由组合（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:52）。
  - 节点级 `model / effort / thinking / maxBudgetUsd` 可覆盖 workflow 顶层默认（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:53）。
  - 改造路径 b 自举：第 4 周开始用新引擎承载本次改造的剩余阶段（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1098）。

## 用户场景

### 场景 1：旧命令兼容（`/requirement:*` 别名）
- 角色：历史 `/requirement:*` 用户（兼容期受益方）
- 前置：兼容期 3 个月内（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:194）
- 主流程：用户调用 `/requirement:new|continue|status|list|save|rollback|submit|archive` 任一命令 → 命令以别名形式转发到对应 `/workflow:*` 命令 → 输出 deprecation warning 提示迁移
- 期望结果：业务行为与旧命令完全等价，仅多一行迁移提示
- `/requirement:next`：3 月兼容期内**保留实际实现**，行为等价于推动需求到下一阶段（语义被 `/workflow:continue` 吸收）；Plan 6 自举验证通过后 Plan 7 才真正删除（D-009 修订，覆盖 spec §4.3 立即删决策；来源：plan.md D-009；context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:204）

### 场景 2：新命令直接触发（`/workflow:run`）
- 角色：需求工程师 / 工作流模板作者
- 前置：`.claude/workflows/<category>/<name>.yaml` 已存在（三层发现：bundled → global → project；来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:75）
- 主流程：用户调用 `/workflow:run standard-8phase "支付重构"` 或自然语言"开个新需求 X" → workflow-launcher Skill 关键词匹配 → 引擎加载 yaml → 生成 run_id（`REQ-{year}-{seq}`）→ 创建 `runs/<run-id>/{meta.yaml, run-state.jsonl}` → 按 DAG 拓扑序逐层执行节点 → 遇 approval 节点暂停输出 `gate_message`（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:159）
- 期望结果：用户可在自然语言通道（workflow-launcher）和 slash 通道（`/workflow:run`）任意切换，最终汇到同一底层函数（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:188）

### 场景 3：跨会话恢复（`/workflow:continue`）
- 角色：需求工程师
- 前置：用户之前启动的 run 因会话终止/手动 save 而中断（最后状态 ∈ `{approval_pending, paused_in_loop, node_started 未完成, layer 全完成}`）
- 主流程：用户重启 Claude Code 后调用 `/workflow:continue [<run-id>]`（缺省时按 git 分支推断 run-id）→ 引擎读 `meta.yaml` 拿 run_id / workflow_name / status → 反扫 `run-state.jsonl` 重建 RunState → 决策位置自动续跑（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:824）
- 期望结果：续跑过程对用户透明，主 Claude 不需要用户额外说明上下文
- 幂等性约束：节点跑两遍同 input 同 output；bash 节点的副作用由开发者负责（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:840）

### 场景 4：嵌套子工作流（`sub_workflow` 节点）
- 角色：需求工程师 / Code Reviewer
- 前置：父 workflow 阶段 7 触发 `code-review-embedded`；嵌套深度 ≤ 2（loader 启动校验，违反则拒启）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:763）
- 主流程：父节点声明 `sub_workflow:` 字段（含 args / output_capture / on_subworkflow_failure）或在 loop prompt 内动态调 `/workflow:run code-review-embedded --parent=$RUN_ID --feature=<id>` → 引擎创建子 run（parent_run_id 指向父）→ 父子状态联动按表执行（cancel/paused/failed/output 回流；来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:563）
- 期望结果：`/workflow:status` 显示父子树；子 run approval 暂停时父 run 显示 `paused_in_subworkflow`；子 run 失败时按 `on_subworkflow_failure` (`fail/continue/skip`) 处理
- 设计取舍：父 run 用户主动 paused 时，子 run **不联动**，独立运行（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1024）。本需求在此基础上增加底线约束：子 run 收到父 cancel 信号时立即终止（已写入 §11.2 cancel 行；来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1020）。

### 场景 5：跨节点回滚（`/workflow:rollback`）
- 角色：需求工程师
- 前置：用户在某个节点 X 之后发现需要重做 X，调用 `/workflow:rollback <run-id> --to-node=X`
- 主流程（纯单层 run）：截断 jsonl 到 X **之前**（不含 X）→ 归档 X 及以后产物到 `runs/<id>/.archived/<ts>/` → `current_node` 重置到 X 最近上游节点 → 下次 `/workflow:continue` 自动重跑 X（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1030）
- 主流程（rollback 父 run 跨过 sub_workflow）：父 jsonl 截断 → 检测 X 之后的 sub_workflow 节点对应子 run → 子 run 联动 cancel（写 `parent_rolled_back` 事件）→ 子 run 产物归档到父 `.archived/` → 下次 continue 时 sub_workflow 节点重新启动新子 run（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1036）
- 期望结果：rollback 之后产物完全可重跑；归档目录可作为审计与人工恢复入口

## 非功能需求

- **性能 / 上下文压力**：单需求 30 节点 standard-8phase 主对话上下文 50-100K token；同时 active 3 需求 150-300K token，Opus 4.7 1M 充裕；Sonnet 200K 用户可用 `/workflow:save` 做检查点续接（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:849）。
- **节点输出阈值**：output ≤ 16KB 直接写 `run-state.jsonl` 的 `output` 字段；> 16KB 写 `runs/<id>/.run-logs/<node-id>.txt`，jsonl 仅存 `{"output_file": "..."}`，变量替换时透明读文件；`.run-logs/` 加 `.gitignore`（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:720）。
- **节点超时**：仅支持 `idle_timeout`，不支持 `timeout`（总时长）—— LLM 思考时间难精确估算。默认值 prompt/agent/skill = 300_000ms；bash = 60_000ms；loop 单轮按上同；整体由 `max_iterations` 兜底（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:711）。
- **重试**：默认 `{max_attempts:2, delay_ms:3000, on_error:transient}`；`transient` 含网络超时 / rate limit / 5xx；`fatal`（auth/quota/invalid_request）不重试（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:702）。
- **变量替换 / 注入防御**：string/num/bool → shellQuote；array/object → JSON 序列化 + shellQuote；null → `''`；节点 ID 内引号沿用 Archon `'\''` 转义（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1242）。
- **when 表达式限制**：不支持数组操作（`contains` / `in` / `length()` 等）；绕路写法用 boolean 字段或 length 比较；第 5-6 月评估扩 `contains`（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:643）。
- **fresh_context 使用准则**：能用 false 就用 false；仅评审 / critic 类必要场景用 true（避免 subagent 启动开销）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1129）。
- **bash 节点副作用约束**：节点幂等或自带防重复（在 SKILL.md 强约束）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1130）。
- **状态文件健壮性**：启动时校验 `run-state.jsonl` 可解析；坏行跳过并 warn；最坏退化到从头跑（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1132）。
- **目录过渡**：MVP 期 `requirements/` 与 `runs/` 双轨共存；loader 同时识别两个路径；阶段 7 再用批量 rename 工具统一迁移（确认决策 D-002）。
- **safety nets**：loader 加载完写 `runs/<id>/.workflow-resolved.yaml`（隐式依赖实例化为显式列表，方便调试）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:737）。

## 范围

- 包含：
  - workflow yaml schema v2 定义（含 `sub_workflow` 节点类型，8 种节点）+ JSON Schema 校验 + DAG 校验（Plan 1 已合并到 develop）
  - workflow-engine Skill：拓扑排序 / 节点执行决策表 / `run-state.jsonl` 读写 + RunState 重建 / approval 状态机 + on_reject 重做 / loop 节点完整执行（含 `$LOOP_OUTPUT` 变量）/ sub_workflow 节点（创建子 run、父子状态联动、嵌套深度 ≤ 2 校验、`/workflow:status` 父子树视图）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1061）
  - `standard-8phase.yaml` 完整化（38 节点 + 8 阶段 Skill prompt 抽到 `.claude/workflows/prompts/`）+ 老需求 `meta.yaml` 的 phase 字段映射逻辑（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1074）
  - `code-review-embedded.yaml`（8 critic 同层并发 + review-critic 对抗 + code-quality-reviewer 综合 + code-review-report 生成报告）+ 验证 `sub_workflow` 真复用（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1080）
  - 11 个 `/workflow:*` 命令实现 + `managing-workflow-runs` 伞形 Skill + workflow-launcher 关键词触发 Skill + `/workflow:status` 父子树 + `/workflow:rollback` 跨父子规则（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1090）
  - 9 个 `/requirement:*` 命令（3 月兼容期保留实际实现 + 输出 deprecation warning；`/requirement:next` 由 D-009 修订为延后至 Plan 6 自举验证后 Plan 7 才删，覆盖 spec §4.3 立即删决策）+ pre-commit hook 拦截旧 `/requirement:` 引用（来源：plan.md D-009；context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1093)
  - 自举验证（第 4 周起用新引擎承载本次改造剩余阶段）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1098）
  - 阶段 7 清理：删 `PHASE_REQUIREMENTS` / `phase_enum.py` / `code_review_signoff.py` / `/requirement:next`；CLAUDE.md / agentic-engineer-guide.md / 全部 SOP 文档更新；老 `requirements/` → `runs/` 批量 rename 工具（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1103）
- 不包含（参考 spec §1.3 + §14 未来扩展，明确 Post-MVP）：
  - 多 provider 共存（MVP 仅 claude；codex/openai-direct 后续 1 周 + 0.5 周）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:57）
  - git worktree 强制隔离（用 git 分支即可；后续 1 周）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:58）
  - 独立 daemon / HTTP API server（archon serve 类似）/ Web Dashboard（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:59）
  - PostgreSQL 持久化（文件 + jsonl 即可）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:62）
  - `lite-3phase` / `hotfix` / `release-cut` / `codex-review-loop` / `pr-feedback-handle` / `extract-experience` / `generate-sop` / `general-assist` 模板（Post-MVP 第一批）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1112）
  - `maxBudgetUsd` 节点级硬熔断（cost 监控痛点驱动；后续 0.5 周）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1146）
  - `--no-start` 旗（创建不启动；批量预创建需求；后续 0.5 天）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1149）
  - 兼容期到期后旧别名的**自动清理 CI 门禁**（决策 D-003：3 个月后由人工在阶段 7 任务清单中手动清理，依赖 spec §12 阶段 7 的"pre-commit hook 拦截旧引用"兜底）

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| D-001 MVP 模板范围 | (a) 仅 standard-8phase / (b) standard + code-review-embedded / (c) 三套（含 lite-3phase） | **(b)** 二套 | spec §1.2 顶部"至少三套"为远景目标；§16 / §17 / §15 决策矩阵全锁 (b) 为 MVP；lite/hotfix 移到 Post-MVP（用户对齐 Q1） |
| D-002 旧 `requirements/` 目录过渡时机 | (a) 立即批量 rename 到 `runs/` / (b) MVP 期双轨共存 + 阶段 7 统一迁移 | **(b)** 双轨 | 自举 REQ-2026-009 自身仍在 `requirements/REQ-2026-009/`，立即 rename 风险高；阶段 7 已规划批量 rename 工具（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1109）。loader 同时识别两个路径（用户对齐 Q2） |
| D-003 兼容期 3 个月到期后旧别名清理 | (a) CI 时间型门禁自动 fail / (b) 阶段 7 任务清单人工清理（依赖 pre-commit hook 拦截旧引用兜底） | **(b)** 人工 | 用户选择 B：避免引入额外的"时间型自动门禁"机制；spec §12 阶段 7 已有 pre-commit hook 拦截旧 `/requirement:` 引用作为底线（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1110）（用户对齐 Q3） |
| D-004 父 run paused 时子 sub_workflow run 联动 | (a) 子 run 联动 paused / (b) 子 run 不联动独立运行 / (c) (b) + 父 cancel 时子立即终止的底线 | **(c)** 独立 + cancel 联动底线 | spec §11.2 锁定 (b) 独立运行（设计取舍）；为避免父 cancel 时子继续跑产生孤儿产物，本需求在 §11.2 cancel 行的基础上明示底线："父 run cancel → 子 run 写 `parent_cancelled` 事件 → cancel"（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1020）（用户对齐 Q4） |

## 验收标准

> AC-* 编号沿用 input-normalizer 草料；MVP 验收以 D-001/D-002 锁定的 (b) 范围为准。

| ID | 描述 | 测试方式 | 来源 |
|---|---|---|---|
| AC-01 | 改阶段顺序只改 1 个 yaml 文件，零代码改动 | 修改 `standard-8phase.yaml` 节点顺序，不改任何 .py / .md，引擎能正确按新顺序执行 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:48 |
| AC-02 | MVP 模板共存：`standard-8phase` + `code-review-embedded` 两套均可被 loader 加载无报错 | `python3 scripts/lib/workflow_loader.py --strict <yaml>` 退出码 0 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1212 |
| AC-03 | 11 个 `/workflow:*` 命令全部可调用 | 枚举 run/list/status/continue/save/approve/reject/cancel/rollback/submit/archive，逐一 smoke 调用无报错 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:159 |
| AC-04 | `/workflow:continue` 在任意中断点能自动续跑，无需用户告知位置 | 在 `node_started` 未完成、`approval_pending`、`paused_in_loop` 三种状态下 continue，均自动恢复 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:824 |
| AC-05 | 5 种验证 lego（output_format/when/approval/bash/critic）可组合 | `code-review-embedded.yaml` 中能跑通 8 critic 并发 + synthesize 综合裁决 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:855 |
| AC-06 | 节点级 model/effort/thinking 可覆盖 workflow 默认 | yaml 中 `model: opus[1m]` 的节点使用 Opus，其余节点使用顶层默认 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:53 |
| AC-07 | 8 种节点类型互斥 + sub_workflow 嵌套深度 ≤ 2 | loader 拒绝 `invalid-mutex.yaml` 和 `invalid-deep-nest.yaml` 并输出具体错误 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:763;context/team/engineering-spec/plans/2026-05-08-workflow-engine-plan-1-schema-loader.md:2148 |
| AC-08 | 14 类 yaml 错误 loader 可识别并输出行号 | 跑 `tests/lib/fixtures/workflows/invalid-*.yaml` 全部返非零退出码，错误信息含行号 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:753;context/team/engineering-spec/plans/2026-05-08-workflow-engine-plan-1-schema-loader.md:2129 |
| AC-09 | 9 个旧 `/requirement:*` 命令 3 月兼容期内**保留实际实现** + 输出 deprecation warning（含 `:next`，D-009 覆盖 spec §4.3 立即删决策；语义被 `/workflow:continue` 吸收但实现保留） | 9 个命令各自调一次，主流程结果与历史一致；deprecation warning 内容含"请改用 /workflow:..."；Plan 6 自举验证通过后再于 Plan 7 真正删除 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:194；plan.md D-009 |
| AC-10 | 跨父子 rollback 规则正确 | rollback 父 run 跨过 sub_workflow 节点时，子 run 写 `parent_rolled_back` 事件 + 联动 cancel + 产物归档到父 `.archived/` | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1036 |
| AC-11 | 父 run cancel 时子 run 立即终止 | 在子 run 处于 `paused_at_subworkflow` 时父 cancel，子 jsonl 末尾应写 `parent_cancelled` + 状态 `cancelled` | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1020（D-004 决策） |
| AC-E2E | 现有 1 个老需求能用新引擎续跑 | 选取已有 `requirements/*` 中一个 paused 需求，用 `/workflow:continue` 续跑至下一 approval 节点，状态一致 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1078 |
| AC-SELF | 自举验证：本 spec 第 4 周起后续阶段（清理 / 文档更新）通过新引擎执行 | 第 4 周起 REQ-2026-009 后续阶段用新引擎推进，无降级回退 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1098 |
| AC-CLEAN | 阶段 7 清理验收 | 全仓 grep 无残留 `PHASE_REQUIREMENTS` / `phase_enum.py` 引用；旧文档无残留 `/requirement:` 引用，pre-commit hook 拦截 | context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1103 |

## 待澄清清单

> 来自 input-normalizer 输出 + 起草过程发现，三态规则下统一标 `[待用户确认]`。

1. **OQ-02：`/workflow:rollback` 归档后是否清理原路径？** [待用户确认]
   - 内容：spec §11.3 说"归档 X 及以后产物到 `.archived/<ts>/`"，但未说明归档后**原路径**是否 clean（保留 / 删除 / 仅 stub）（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1032）
   - 建议倾向：归档后**原路径删除**（rollback 语义就是"重跑"，残留旧产物会让用户混淆）
   - 验证时机：detail-design 阶段确认；进入 development 前必须锁定

2. **OQ-A：MVP 期间 loader 是否需要"双路径识别"的具体实现细节** [待用户确认]
   - 内容：D-002 决策 MVP 期 `requirements/` 与 `runs/` 双轨共存，loader 同时识别两个路径——但是否需要在 yaml schema 里新增字段（如 `legacy_path: requirements/`）/ 还是 loader 内置默认识别两种前缀？
   - 建议倾向：loader 内置默认识别（`requirements/REQ-*` 与 `runs/REQ-*` 都能命中），不引入 schema 字段
   - 验证时机：outline-design 阶段确认

3. **OQ-B：`workflow-launcher` Skill 的关键词冲突仲裁策略** [待用户确认]
   - 内容：spec §4.2 提到自然语言触发关键词（"开个新需求 X" / "跑下代码评审" / "我要发版" / "继续之前的需求" / "approve" / "reject:"），多关键词命中时如何仲裁未明确（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:177）
   - 建议倾向：最长匹配优先 + 上下文 hint（当前是否处于 approval_pending 等）作为 tiebreaker
   - 验证时机：detail-design 阶段确认

4. **OQ-C：阶段 7 自举切换的失败回退策略** [待补充]
   - 内容：spec 第 4 周开始用新引擎自举跑剩余阶段，若新引擎在自举期间出现严重 bug 是否需要回滚到旧引擎/旧命令？
   - 依据：spec §13 风险表只列了 jsonl 损坏、上下文压力等技术风险，没列自举失败的应对（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1124）
   - 风险：若自举期遭遇阻塞，无明确 fallback 会延迟整体上线
   - 验证时机：tech-research 阶段评估；倾向方案 = "保留旧 `/requirement:*` 命令的实现而非仅别名，自举失败可临时切回"，需用户确认

5. **OQ-D：`code_review_signoff.py` tty 双校验删除的安全替代** [待用户确认]
   - 内容：spec §15 / §17 锁定"放弃 2"决策——删除 tty 双校验（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md:1163）；当前 CLAUDE.md 全局规范明文禁止 AI 调用 sign-off 入口，删除后是否需要替代防御层？
   - 依据：CLAUDE.md "sign-off 是人类专属动作"硬约束依赖 tty 校验作为深防御
   - 风险：完全删除可能让 AI 有机会绕过 sign-off
   - 验证时机：detail-design 阶段（与 `/workflow:approve` 命令的人机鉴别逻辑一并设计）；倾向方案 = "保留 approve/reject 命令必须由人类终端触发的硬约束（hook 拦截 AI shell）"，需用户确认
