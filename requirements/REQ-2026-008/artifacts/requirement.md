---
id: REQ-2026-008
title: 派发链强制结构化升级
created_at: 2026-05-05T22:18:00+08:00
refs-requirement: true   # 供 traceability-gate-checker 识别
---

# REQ-2026-008 · 派发链强制结构化升级

## 背景

当前阶段 7（开发实施）的 subagent 派发链有 20+ 条"靠 Skill / 派发指引文档约束主 Agent 自觉"的红线，主 Agent 是自由 agent，文本约束可被"读规则、自答通过"绕过。本次工程升级聚焦其中 6 项**绕过容易度高、绕过后果严重**的卡点，把它们升级成机器可读的强制结构。

**现状盘点**（前期 brainstorming Explore agent 出三份盘点）的关键事实：

1. `feature-lifecycle-manager` 的"硬约束"段已显式写出多条主 Agent 红线，例如"禁止主 Agent 代替 subagent 直接写实现代码""禁止并发派多个 implementer subagent（保守档约束）""禁止跳过 post-dev-verify"等——但这些都是文本约束（来源：.claude/skills/feature-lifecycle-manager/SKILL.md:55）。
2. `subagent-dispatch.md` 的"派发前置校验"要求"读 task 文件 status / 校验 depends_on 每条都 done / 任一前置未 done 停止派发"——执行靠主 Agent 自觉（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:18）。
3. `subagent-dispatch.md` 的"回执状态契约"规定四态字符串开头（DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED）+ 自由文本，主 Agent 用 AI 语义识别；没有 schema、没有结构化文件（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:80）。
4. `subagent-dispatch.md` 的"红线"段写"禁止改动触及范围之外的文件（包括 docs、配置、其他 feature 的代码）"——这是写在派发 prompt 里的纯文本约束，subagent 仍可调 Edit/Write 任意路径（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:65）。
5. `managing-requirement-lifecycle` 的"硬约束"段反复警告"禁止"读清单自答通过"——bash scripts/... 形式的门禁项必须用 Bash 工具真跑"——反复强调本身就暴露了真问题：规则只能提示、不能 enforce（来源：.claude/skills/managing-requirement-lifecycle/SKILL.md:25）。
6. `scripts/gates/registry.yaml` 已有 13 个声明式 gate（trigger=pre-commit/phase-transition/submit/ci/post-dev），统一执行入口是 `scripts/gates/run.py`，机器强制基建已具备但派发链没接入（来源：scripts/gates/registry.yaml:1）。

**借鉴的设计范式**：Archon 项目（coleam00/Archon）的 DAG + fresh-context-artifact 模式提供了"结构强制 vs 文本约束"的成熟范式——节点输入输出由 schema/退出码驱动，不靠 AI 解读自由文本。本次升级**借鉴思想，不引入引擎本身**（来源：requirements/REQ-2026-008/plan.md:55）。详见下文决策 D-001。

## 目标

- **主目标**：把派发链 6 个高风险卡点（receipt 自由文本 / touches 越界 / 派发前置校验 / 并发限制 / post-dev gate / Skill 文档与机器拦截一致性）从"主 Agent 自觉"升级为"机器拦截 + schema 校验 + gate 兜底"，让红线在主 Agent 自由意志面前不可绕过（来源：requirements/REQ-2026-008/plan.md:7）。
- **次要目标**：通过新增 receipt schema / features.json schema / task.md frontmatter schema 三份 schema 文件，把派发链所有结构化数据纳入与 `meta-schema.yaml` / `review-schema.yaml` 一致的"schema → check 脚本 → gate 注册表"标准三层模式（来源：context/team/engineering-spec/meta-schema.yaml:1）（来源：context/team/engineering-spec/review-schema.yaml:1）。

## 用户场景

### 场景 1：subagent 派发前置校验

- **角色**：主对话 Agent（用户操控）
- **前置**：当前在 `feat/req-XXX` 分支、phase = `development`、用户说 "F-xxx 开始做 / F-xxx 实现"
- **主流程**：
  1. 主 Agent 调 Task tool 派 implementer subagent
  2. PreToolUse hook 链触发 `dispatch_precheck.py`：从 Task prompt 解析 `feature_id`（约定派发模板硬编码 `feature_id: F-xxx` 行）
  3. 校验 `tasks/<F-xxx>.md` frontmatter `status == pending`（否则 exit 2 阻断 + stderr 列原因）
  4. 校验 `depends_on` 每条对应 task 文件 `status == done`（否则 exit 2）
  5. 校验当前 `tasks/*.md` 中无其他 `status == in-progress`（保守档串行约束，否则 exit 2）
  6. 任一失败 → Task 工具调用被拦，主 Agent 收到 stderr 列出原因 → 修复后重派
  7. 全过 → 写 `requirements/<id>/.dispatch-state.json` 标记当前 in-progress feature → 放行 Task tool
- **期望结果**：派发前置校验从"主 Agent 自觉"升级为"hook exit 2 阻断"；保守档串行约束机器化执行（来源：requirements/REQ-2026-008/plan.md:13）。

### 场景 2：subagent 写完代码回执

- **角色**：implementer subagent（主对话 Agent 派出）
- **前置**：subagent 已完成 F-xxx 的代码实现 + 测试 + commit
- **主流程**：
  1. subagent 用 Write 工具写 `requirements/<id>/artifacts/tasks/F-xxx.receipt.json`，符合 `context/team/engineering-spec/receipt-schema.yaml` 定义的 schema
  2. 关键字段：status / feature_id / commit_sha / files_changed / test_summary / touches_violations / concerns / missing_context / block_reason / timestamp
  3. 回到主 Agent 时只回一行：`RECEIPT_WRITTEN: requirements/<id>/artifacts/tasks/F-xxx.receipt.json`
  4. 主 Agent 跑 `bash scripts/lib/check_receipt.py <path>` → 退出码 0 = schema 合法
  5. 主 Agent 跑 `jq -r '.status' <path>` 取 status 字段值，按四态走分支
- **期望结果**：消除"AI 语义解析自由文本"的歧义来源；receipt 文件可审计、可重放、不污染主对话上下文（来源：requirements/REQ-2026-008/plan.md:61）。详见决策 D-002。

### 场景 3：subagent 修触及范围外文件

- **角色**：implementer subagent
- **前置**：subagent 当前在做 F-xxx，task.md 的 `touches` 字段限定为 `["src/auth/*"]`，但发现需要在 `src/billing/api.ts` 加个 import 才能跑通
- **主流程**：
  1. subagent 调 Edit 改 `src/billing/api.ts`
  2. PreToolUse hook 触发 `touches_guard.py`：读 `.dispatch-state.json` 拿到当前 feature_id，读 `tasks/F-xxx.md` 的 `touches`
  3. `src/billing/api.ts` 不在 `touches` 范围 → **不阻断 Edit**（exit 0，避免误伤合理调整）
  4. **但**追加一条到 `tasks/F-xxx.receipt.json` 的 `touches_violations[]`（如 receipt 不存在则创建空骨架）
  5. subagent 完成后正常写 receipt
  6. 后续 `/requirement:next` 切到下一阶段时，`GATE-TOUCHES-VIOLATION` 扫所有 receipt → 任一 `touches_violations[]` 非空 → fail，列出违规文件 + feature_id
  7. 用户决策：要么改回不动该文件 + 重派；要么扩 `touches` 字段后重跑 phase-transition
- **期望结果**：开发期不误伤合理越界、阶段切换硬挡（双层防护）；越界 100% 留痕（来源：requirements/REQ-2026-008/plan.md:67）。详见决策 D-003。

### 场景 4：phase-transition 时 post-dev gate 兜底

- **角色**：主对话 Agent
- **前置**：phase = `development`，用户跑 `/requirement:next` 想切 testing；features.json 列了 5 个 feature，但 F-003 只标了 `status: done`，没写 receipt.json（主 Agent 跳过了 post-dev-verify）
- **主流程**：
  1. `managing-requirement-lifecycle` 跑 `scripts/gates/run.py --trigger=phase-transition --req=<id> --from=development --to=testing`
  2. 现有 7 个 phase-transition gate 跑过
  3. 新增 `GATE-POST-DEV-RECEIPT` 跑：扫 features.json → 对每个 feature 要求 `tasks/<id>.receipt.json` 存在 + `status ∈ {DONE, DONE_WITH_CONCERNS}`
  4. F-003 缺 receipt → fail，列出 "F-003: missing receipt.json"
  5. 主 Agent 回头补 receipt（或重派 F-003）→ 重跑 phase-transition
- **期望结果**：即使主 Agent 跳过逐 feature 的 post-dev-verify，下次切阶段也会被兜底（来源：requirements/REQ-2026-008/plan.md:73）。详见决策 D-004。

### 场景 5：历史需求向后兼容

- **角色**：主对话 Agent / CI workflow
- **前置**：本次升级合并后，历史 REQ-2026-001~007 已全部 phase=completed，理论不受新 gate 影响；但若 CI 重跑历史需求的检查链或某历史 feature 分支被意外重新激活，新增的 4 个 gate 可能拦下未补 receipt / schema 的旧产物
- **主流程**：
  1. 历史需求或者 in-flight 但 bootstrap 早于本次升级的需求，meta.yaml 加 `legacy: true` 字段
  2. `GATE-POST-DEV-RECEIPT` / `GATE-FEATURES-SCHEMA` / `GATE-TASK-FRONTMATTER` / `GATE-TOUCHES-VIOLATION` 实现时检查 meta.legacy → 短路返回 pass
  3. 文档化：升级合并后第一周内对所有 in-flight 需求做扫描，明确每个需求是"补 receipt 后正常走"还是"标 legacy 豁免"
- **期望结果**：升级零破坏历史需求；豁免路径明确、不被误用为"长期省事手段"；新 REQ 必须走结构化通道（来源：context/team/engineering-spec/meta-schema.yaml:118）（来源：scripts/gates/registry.yaml:1）。

## 非功能需求

- **性能**：
  - 派发 PreToolUse hook（dispatch_precheck.py + touches_guard.py）必须在毫秒级完成（纯 Python 文件读 / YAML 解析 / 路径匹配）；不引入网络 I/O
  - 4 个新 gate 在 phase-transition / submit 触发组中的总耗时不超过现有 7 个 gate 的同量级
- **兼容性**：
  - 现有 13 个 gate 行为不变（来源：scripts/gates/registry.yaml:1）
  - 现有 `meta-schema.yaml` / `review-schema.yaml` 不动
  - 现有 8 个 `/requirement:*` 命令外观不变
  - 8 阶段 phase-rules、保守档串行约束、sign-off tty 强校验不变
  - 历史 REQ 默认通过 legacy escape 豁免新 gate
- **安全/合规**：
  - touches_guard 软拦截不允许"被绕"——subagent 即使尝试用 MultiEdit / 间接路径也必须捕获，违规必入 receipt
  - dispatch_precheck 解析 prompt 时禁止把用户敏感信息（如 git secrets / token）写入日志或 .dispatch-state.json
  - receipt JSON 不应包含敏感信息字段；commit_sha 是公开 git 元数据可写
- **可观测性**：
  - 所有新 hook 走现有 `audit/.queue/<date>.log` 通道，与现有 PreToolUse / SessionEnd 一致
  - 4 个新 gate 走现有 audit JSON 输出（`audit/<YYYY-MM>/<trigger>-<timestamp>.json`），与现有 13 个 gate 一致

## 验收标准

| ID | 验收点 | 来源 |
|---|---|---|
| V-01 | 沙盒 e2e：在测试需求 `REQ-2099-008` 下创建 task `F-002.md`，故意把 `depends_on: [F-001]` 但 `F-001.status` 还是 pending；主 Agent 派 F-002 → PreToolUse hook 拦截 Task 工具调用，stderr 输出 `dispatch_precheck.py: F-002 depends_on F-001 not done`；exit 2；改 F-001=done 后重派 → 通过 | requirements/REQ-2026-008/plan.md:7-22 |
| V-02 | 沙盒 e2e：故意写一个缺 commit_sha 的 receipt.json；`bash scripts/lib/check_receipt.py <path>` exit 1 + 列字段；补齐字段后 exit 0；主 Agent `jq -r '.status'` 拿到字符串值 | requirements/REQ-2026-008/plan.md:13 |
| V-03 | 沙盒 e2e：subagent 派发到 F-001（touches=`["src/auth/*"]`），故意写 `src/billing/api.ts`；PreToolUse `touches_guard.py` 不阻断（exit 0）；`tasks/F-001.receipt.json.touches_violations[]` 含 `src/billing/api.ts`；推 phase-transition → `GATE-TOUCHES-VIOLATION` exit 1，列出违规；改回后重跑 → exit 0 | requirements/REQ-2026-008/plan.md:67 |
| V-04 | 沙盒 e2e：在 `REQ-2099-008` 中标 `F-001.status = done` 但**不写** `F-001.receipt.json`；跑 `bash scripts/gates/run.py --trigger=phase-transition --req=REQ-2099-008` → `GATE-POST-DEV-RECEIPT` exit 1，列 F-001 缺 receipt；补 receipt → 重跑 → exit 0 | requirements/REQ-2026-008/plan.md:73 |
| V-05 | 沙盒 e2e：把测试 features.json 的某 feature `complexity` 改成 `"giant"`（非法值）；跑 `bash scripts/gates/run.py --trigger=pre-commit --req=REQ-2099-008` → `GATE-FEATURES-SCHEMA` exit 1 列非法值；同样测 task.md frontmatter `status: invalid_value` 触发 `GATE-TASK-FRONTMATTER` | requirements/REQ-2026-008/plan.md:13 |
| V-06 | 沙盒 e2e：派发 F-001 → status 变 in-progress；不等完成立刻派 F-003（无依赖）→ dispatch_precheck.py exit 2，stderr 含 `concurrent dispatch denied: F-001 still in-progress`；保守档串行机器化兑现 | requirements/REQ-2026-008/plan.md:13，.claude/skills/feature-lifecycle-manager/SKILL.md:60 |
| V-07 | 回归：跑 `bash scripts/gates/run.py --trigger=ci --req=REQ-2026-001` 等历史已 completed 需求；exit code 不变；新 4 个 gate 在 legacy=true 时短路返回 pass | requirements/REQ-2026-008/plan.md:41，scripts/gates/registry.yaml:1 |
| V-08 | 回归：跑 `bash scripts/gates/run.py --trigger=phase-transition --req=REQ-2026-008 --from=development --to=testing` 走自身的开发 → 测试切换；新 gate 在本需求的 develop/test 阶段也通过（自举） | requirements/REQ-2026-008/plan.md:13 |
| V-09 | 文档一致性：`feature-lifecycle-manager/SKILL.md` 的"硬约束"段把"由 hook/gate 拦截"标注落地；`managing-requirement-lifecycle/SKILL.md` 补一条新 gate 说明；`subagent-dispatch.md` 的"派发前置校验 / 红线"段精简为引导用户看 stderr，不再口述 AI 自觉规则；`gate-checklist.md` 由 `render-docs.py` 重生成包含 4 个新 gate | requirements/REQ-2026-008/plan.md:7-22 |

## 范围

- **包含**：
  - 新增 `context/team/engineering-spec/receipt-schema.yaml` + `features-schema.yaml` + `task-frontmatter-schema.yaml`（来源：requirements/REQ-2026-008/plan.md:9）
  - 新增 `scripts/lib/check_receipt.py` + `check_features.py` + `check_task_frontmatter.py`（来源：requirements/REQ-2026-008/plan.md:11）；参照 `scripts/lib/check_meta.py` / `check_reviews.py` 形态
  - 新增 `.claude/hooks/dispatch_precheck.py` + `.claude/hooks/touches_guard.py`（来源：requirements/REQ-2026-008/plan.md:13）
  - 新增 4 个 gate plugin：`scripts/gates/plugins/post_dev_receipt.py` / `touches_violation.py` / `features_schema.py` / `task_frontmatter.py`（来源：requirements/REQ-2026-008/plan.md:15）
  - 修改 `scripts/gates/registry.yaml`：注册 4 个新 gate 到 phase-transition / submit / pre-commit / ci 触发组（来源：requirements/REQ-2026-008/plan.md:15）
  - 修改 `.claude/settings.json`：PreToolUse matcher 加上 `Task` + `Edit|Write|MultiEdit` 链入新 hook（来源：requirements/REQ-2026-008/plan.md:13）
  - 修改 `.claude/hooks/pre-tool-use-guard.sh`：调度新 hook 脚本（来源：requirements/REQ-2026-008/plan.md:13）
  - 修改 `.claude/skills/feature-lifecycle-manager/SKILL.md` + `reference/subagent-dispatch.md` + `templates/feature-task.md.tmpl`（补 `touches` 字段透传）（来源：requirements/REQ-2026-008/plan.md:7）
  - 修改 `.claude/skills/managing-requirement-lifecycle/SKILL.md` + 重新渲染 `reference/gate-checklist.md`（来源：requirements/REQ-2026-008/plan.md:7）
  - 单测套件覆盖 V-01 ~ V-08 的所有用例；测试目录约定见下文待澄清清单第 1 条
- **不包含**：
  - 门禁链 `/requirement:next` "读清单自答"升级（属于"门禁链优先"分支，下一轮做）（来源：requirements/REQ-2026-008/plan.md:23）
  - `/code-review` 自动 loop 修复（保留人工 sign-off）（来源：requirements/REQ-2026-008/plan.md:23）
  - worktree 隔离（与 `requirements/<id>/` 主分支约定冲突，迁移成本不值）（来源：requirements/REQ-2026-008/plan.md:23）
  - 替换 Task tool 为 wrapper 脚本（用户偏好 hook 优先）（来源：requirements/REQ-2026-008/plan.md:23）
  - 引入 DAG YAML 引擎（不引入新工具链）（来源：requirements/REQ-2026-008/plan.md:23）
  - 改动保守档串行约束（"禁止并发派 implementer"红线保留）（来源：requirements/REQ-2026-008/plan.md:23）

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 整体范式 | A. 借鉴 Archon 思想但不引入引擎 / B. 整体迁移到 Archon DAG / C. 不动 | A | 现有 hook + gate registry 已具备等价能力，复用比换框架 ROI 高（D-001，来源：requirements/REQ-2026-008/plan.md:55） |
| 回执形态 | A. 完整 JSON receipt 文件 / B. 文本 + 末尾 fenced JSON / C. 仅补关键字段 | A | AI 解析零歧义、receipt 文件可审计、不污染主对话上下文（D-002，来源：requirements/REQ-2026-008/plan.md:61） |
| touches 越界拦截 | A. 双层（软+硬）/ B. 硬拦截 / C. 软拦截 + 实时提醒 | A | subagent 实际开发常需调整邻近文件；硬拦截误伤多导致 BLOCKED 重派转发成本高；双层兼顾（D-003，来源：requirements/REQ-2026-008/plan.md:67） |
| post-dev 触发 | A. Gate 注册表 phase-transition 前置 / B. PostToolUse hook 自动 / C. 双管齐下 | A | 复用现有 gate 体系一致性；发现失败延迟到阶段切换可接受（D-004，来源：requirements/REQ-2026-008/plan.md:73） |
| 失败重试策略 | A. 保留现有红线 / B. 受控自动重派 1 次 / C. 完整 Archon 式 loop | A | 保留"禁止原模型原上下文重试 BLOCKED"等审慎红线；本次只解决"机器化结构"，不引入自动收口（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:104） |
| 强制载体偏好 | A. PreToolUse hook 优先 / B. Wrapper 脚本封装 / C. Gate 注册表新增 / D. Schema | A + 配套 wrapper/gate/schema | 用户偏好 hook 优先；wrapper/gate/schema 作为补强（来源：requirements/REQ-2026-008/plan.md:7） |
| 迭代节奏 | A. 一刀切（6 改动一次完成）/ B. 分两批 PR | A | 6 个改动是耦合改造（receipt 不到位 hook 拦不住，hook 不到位 gate 兜底空挡），分批留中间不一致状态（用户确认） |

## 待澄清清单

1. **单测目录约定**：本仓库 `tests/` 目录布局尚不明确（V-01~V-08 沙盒 e2e 测试代码应该放哪里？是否使用 pytest？是否走 GitHub Actions CI？）[待补充]
   - 内容：测试代码物理位置 + 框架选型
   - 依据：参考其他需求测试落地位置
   - 风险：放错位置导致 CI 不跑测试、回归失效
   - 验证时机：tech-research 阶段调研既有 `scripts/lib/check_*.py` 是否已有伴随测试，对齐落位

2. **legacy 字段对新 gate 的豁免范围**：现有 `meta.yaml` 的 `legacy: true` 字段当前只影响 `check_reviews.py` 的 R001~R007 跳过（来源：context/team/engineering-spec/meta-schema.yaml:118）。本次新增的 4 个 gate（POST-DEV-RECEIPT / TOUCHES-VIOLATION / FEATURES-SCHEMA / TASK-FRONTMATTER）是否全部纳入 legacy 豁免？还是仅部分？[待用户确认]

3. **dispatch_precheck.py 从 Task prompt 解析 feature_id 的精确策略**：目前设想"派发 prompt 模板硬编码 `feature_id: F-xxx` 显式行"。但既有派发 prompt 模板（来源：.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:36）目前是自然语言开头"你是 feat/req-... 分支上的 feature 实现者。当前任务 F-xxx · <title>"——是改模板加 `feature_id:` 显式行，还是 hook 直接正则匹配 `F-\d{3}`？[待用户确认]

4. **`.dispatch-state.json` 的并发安全**：保守档串行约束下应该不存在并发写，但若同时多个 hook（dispatch_precheck / touches_guard / 完成清理）触及该文件，是否需要 flock？[待补充]
   - 内容：状态文件读写并发模型
   - 依据：保守档约束 + 单一主 Agent + 单一 subagent
   - 风险：rollback 命令同时跑可能竞态
   - 验证时机：detail-design 阶段画时序图确认所有写入路径

5. **历史 in-flight 需求识别清单**：本次升级合并时是否存在 phase ≠ completed 的 in-flight 需求？需要一份扫描结果决定 legacy 豁免名单 [待用户确认]
