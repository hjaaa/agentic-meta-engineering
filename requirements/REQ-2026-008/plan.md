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
