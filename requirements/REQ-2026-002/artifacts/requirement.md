---
id: REQ-2026-002
title: 统一门禁系统
created_at: "2026-04-27 19:58:00"
refs-requirement: true
---

# REQ-2026-002 · 统一门禁系统

## 背景

本仓库的门禁体系已演化出 9 层各自独立的执行通道：

1. **PreToolUse Hook**：`protect-branch.sh` 拦受保护分支直写 + 拦 `reviews/*.json` 直写（来源：.claude/hooks/protect-branch.sh:1）。
2. **本地 pre-commit**：跑 check-meta / check-index + meta.yaml.reviews ↔ reviews/*.json 同步性（来源：scripts/git-hooks/pre-commit:1）。
3. **阶段切换门禁清单**：手写 Markdown 由 Skill 逐条解释执行（来源：.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md:1）。
4. **/requirement:submit 前置门禁**：另一份手写清单（来源：.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md:88）。
5. **CI 兜底**：串跑 4 个 check 脚本（来源：.github/workflows/quality-check.yml:1）。
6. **verdict 写时一致性**：CR-1~CR-6（来源：context/team/engineering-spec/review-schema.yaml:68）。
7. **verdict 读时门禁**：R001~R007（来源：scripts/lib/check_reviews.py:33）。
8. **追溯链**：traceability-gate-checker Skill（来源：.claude/skills/traceability-gate-checker/SKILL.md:1）。
9. **post-dev-verify 总闸**（来源：scripts/post-dev-verify.sh:1）。

每层独立维护"哪些规则、何时跑、怎么报错、怎么处理副作用"，由此暴露的具体腐化点：

- **半成品状态**：R005 在切阶段中途把 `stale=true` 写回 meta.yaml，后续 R 失败时 phase 没切但 meta 已部分修改（来源：scripts/lib/check_reviews.py:152）。
- **绕过点**：`protect-branch.sh` 仅拦 Edit/Write 工具，Bash 直接 `cat > requirements/.../reviews/x.json` 完全绕过（来源：.claude/hooks/protect-branch.sh:30）。
- **submit 与 next 校验割裂**：submit 只查 review-*.md 文本无 blocker（来源：.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md:113），next development→testing 用 R007 + review-*.md 双轨（来源：.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md:71）。
- **PR 状态无回环**：submit 写 `pr_url` / `pr_number` 后不再回访（来源：.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md:75）。

新增一条门禁的当前成本是"改 4 个文件 + 跑通 3 套清单 + 祈祷不漏"，这是反复发生的腐化点。

## 目标

- **主目标**：把 9 层门禁的"知识（哪些规则、何时生效、怎么失败）"沉淀到单一 registry，"流程（怎么执行、怎么回滚、怎么审计）"收敛到单一 runner；现有规则全部 adapter 接入，行为等价。
- **次要目标**：
  - 关闭 4 个高优先级缺口：H1（R005 写回事务化，对应 scripts/lib/check_reviews.py:152 的副作用）、H3（submit 与 next 同源，对应上文 submit-rules.md:113 vs gate-checklist.md:71 的割裂——具体形态是 R007 验证 vs review-*.md 文本检查的双轨）、H4（PR 合并状态闭环，对应 submit-rules.md:75 缺反向校验）、H5（Bash 写 reviews/*.json 拦截，对应 protect-branch.sh:30 的绕过点）
  - **新增门禁的成本降到"填 9 字段 + 写 1 个类 + 写 3 个测试"**——基线锚点（粗估）：当前新增一条门禁需改 4 个文件（CI yml + pre-commit + skill 清单 + check 脚本）+ 跑通 3 套清单约 1-2 人天；改造后目标 ≤ 0.5 人天 [待用户确认]
  - 门禁执行有结构化 audit log，可被未来的 governance 类工具消费

## 用户场景

### 场景 1：开发者新增一条门禁

- **角色**：仓库内 Skill / 工具开发者
- **前置**：识别出某个新的"要在某事件下校验某状态"的需求（如 PR 合并状态校验）
- **主流程**：
  1. 跑脚手架 `python scripts/gates/scaffold.py new-gate` 交互式问 9 字段（候选集合：`id` / `triggers` / `applies_when` / `severity` / `dependencies` / `side_effects` / `failure_message` / `escape_hatch` / `tests`，由 detail-design 定稿）[待补充]
     - 内容：9 字段为 registry 条目的契约；当前列表为初稿
     - 依据：基于本对话上一轮设计讨论沉淀，最终字段集以 detail-design.md 为准
     - 风险：detail-design 阶段可能调整字段名/拆并；不影响主流程结构
     - 验证时机：detail-design 评审时锁定 9 字段集
  2. 跑 `python scripts/gates/scaffold.py new-plugin --id <GATE-ID>` 生成 plugin + test 骨架
  3. 实现 plugin 的 `precheck` / `run` / 必要时 `rollback`
  4. 写覆盖 pass / fail / skip 三种用例的测试
  5. 跑 `make gates-validate`：registry schema + plugin 加载 + 测试一次过
- **期望结果**：单一 PR 即合入；不需要改 CI yml / pre-commit / Hook / Skill 任何文件
- **允许的有意例外**：新增门禁需要的"新触发器类型"（当前 6 类之外，如 `governance`）属于框架级扩展，可在该 PR 内同时改 `triggers/` 目录；这是显式例外，不计入"零改动"约束

### 场景 2：/requirement:next 触发阶段切换门禁

- **角色**：主对话 Agent（执行 `managing-requirement-lifecycle` 的 next 流程）
- **前置**：用户已运行 `/requirement:next`，当前 phase = X，目标 phase = Y
- **主流程**：
  1. Agent 调 `python scripts/gates/run.py --trigger=phase-transition --req <ID> --from X --to Y`
  2. runner 按 registry 过滤出适用 gate，按 dependencies 拓扑排序
  3. 在事务包裹内逐个执行，任一 error 触发已运行 gate 的 rollback
  4. rollback 自身失败时降级：写 `[blocker] gate-rollback-failed` 到 process.txt + audit log 标记 `rollback_failed=true`，让用户介入手工恢复 meta.yaml（plan.md R-2 的兜底路径）
  5. 输出 JSON Report：`{passed, failed, skipped}`
  6. Agent 读 Report 决定是否更新 meta.yaml.phase
- **期望结果**：Agent 不再"读 Markdown 清单逐条解释"，gate 失败有统一格式 + fix hint

### 场景 5：4 PR 增量切换的灰度路径

- **角色**：Maintainer / CI
- **前置**：F-001 已合入（runner 骨架就位），F-002~F-004 尚未合入
- **主流程**（每个 PR 共用）：
  1. PR 内**实施**采用"旧入口包薄壳"策略：旧脚本（如 `scripts/check-meta.sh`）改写为薄壳，内部直接 `exec python scripts/gates/run.py --trigger=adapter --legacy-name=check-meta`
  2. PR 内**验收**采用"snapshot 行为契约测试"：合入前在迁移前 commit 抓基线（`scripts/gates/migration/capture-baseline.sh`），抓取相同输入下旧脚本的 exit code + 归一化 stderr；合入后在迁移后 commit 跑 runner 路径，比对 snapshot
  3. 所有 trigger（pre-commit / phase-transition / submit / CI / PreToolUse）按 PR 顺序逐个切到 runner，不并行切换
  4. 最后一个 PR（F-004）合入后才删除旧入口薄壳
- **期望结果**：任意 PR 出问题可独立 revert；revert 后旧入口薄壳仍能工作（薄壳路径就是 runner 路径，等价回滚成本 = 0）

### 场景 6：主对话 Bash 写 reviews/*.json 被拦截（H5）

- **角色**：主对话 Agent / 人类用户
- **前置**：当前分支不限；试图通过 Bash 命令直接写 `requirements/*/reviews/*.json`（如 `cat > foo.json`、`tee`、`echo > foo.json`）
- **主流程**：
  1. PreToolUse Hook 解析 Bash command 字段，正则匹配 `requirements/.+/reviews/.*\.json` 的写操作
  2. 命中且**调用方不在白名单**（白名单：`save-review.sh` 启动的子进程、显式带 `CLAUDE_GATES_BYPASS=1` 的环境变量）→ 拒绝，stderr 提示"reviews/*.json 是 save-review.sh 唯一通道，请让 reviewer Agent 重新评审"
  3. 拒绝事件写 audit log，标记 `escape_used=false / blocked=true / reason=bash-write`
  4. 命中且**调用方在白名单** → 放行，但 audit log 标记 `whitelisted=<调用方>`
- **期望结果**：覆盖 `protect-branch.sh` 现状只拦 Edit/Write 工具的盲区（来源：.claude/hooks/protect-branch.sh:30）；用户/Agent 看到清晰拒绝原因和替代路径

### 场景 3：CI 跑全量门禁

- **角色**：GitHub Actions runner
- **前置**：PR 提交 / push 到 main/develop
- **主流程**：
  1. 单一 step：`python scripts/gates/run.py --trigger=ci --strict`
  2. runner 自行扫描所有 `requirements/*/meta.yaml` 并按各自 `phase` 跑相应 gate 集合
  3. 单需求失败**不中断**全量扫描：每个需求独立累积 Report，最终汇总；任一需求有 error → runner 退出码非零
  4. 默认串行执行（保持当前 CI 时序行为，避免引入并发死锁）；并发度由 detail-design 决定是否引入
  5. audit log 写入 `scripts/gates/audit/<date>/<event>.json`，可被 PR comment / dashboard 消费
- **期望结果**：CI 配置从当前 5 个 step 收敛到 1 个

### 场景 4：开发者跑 `/requirement:submit`

- **角色**：用户 / 主 Agent
- **前置**：phase ∈ {development, testing}，本地有领先 origin 的 commit
- **主流程**：
  1. submit 流程调 `run.py --trigger=submit --req <ID>`
  2. runner 复用 next 的 gate 集合（含 R007 / 工作区 / sourcing）+ submit 特有 gate（gh auth / base 可达 / **PR 合并状态**）
  3. PR 合并状态 gate 命中时阻断并提示走 `/requirement:next`
- **期望结果**：submit 与 next 共享同一套 review / sourcing 校验；"结果一致"判据 = 同一输入下两入口的 Report.passed / Report.failed gate id 集合相同 + 退出码相同

## 非功能需求

- **性能**：runner 单次端到端执行不应显著高于现状（现状是 quality-check.yml 串跑 4 个 step，参见 .github/workflows/quality-check.yml:28）。SLA 硬指标在 tech-research 阶段抓现状基线后决定，不在 definition 阶段锁死 [待用户确认]
- **兼容性**：旧入口（scripts/check-*.sh、post-dev-verify.sh）保留兼容期至 F-004；具体窗口 = 前 3 个 PR（F-001 ~ F-003）旧入口存在但实现为薄壳，F-004 删除（与 plan.md D-001 口径一致）。meta.yaml / review-schema.yaml / 既有 reviews/*.json 全部不变。
- **行为契约等价（替换原"CI 双跑等价"）**：每个 PR 合入前必须通过 snapshot 行为契约测试。判据：
  1. 退出码完全一致
  2. stderr 用 `scripts/gates/migration/normalize-stderr.sh` 归一化（去时间戳、去绝对路径前缀、去 ANSI color），归一化后**前缀为 `ERROR`/`WARNING`/`✗`/`❌`/`E\d+`/`W\d+`/`R\d+`/`CR-\d+` 的行做完全逐行 diff，必须为空**
  3. 退出码或归一化 stderr diff 任一不空 → PR 不可合入
- **可观测性**：每次 runner 执行写一份结构化 audit JSON（trigger / passed / failed / skipped / escape_used / actor），路径 `scripts/gates/audit/<YYYY-MM-DD>/<event>-<timestamp>.json`。escape_hatch 每次使用必须带 `reason` 字段，写入 audit + process.txt。
- **安全/合规**：registry.yaml 的 `escape_hatches` 段是 PR review 焦点，新增一条须通过评审（参考既有 `legacy: true` 的治理思路，来源：context/team/engineering-spec/meta-schema.yaml:131）。Bash 写保护正则需有白名单机制以避免误伤合法路径（如 save-review.sh 子进程的写入）。

## 范围

`feature_area: gate-system` 跨 hooks / ci / scripts / skills / lifecycle 五类触面（来源：context/project/agentic-meta-engineering/areas.yaml:18），下方"包含"必须显式覆盖这五类。

- **包含**（详见 plan.md，与本节一致）：
  - `scripts/gates/` 新目录及其全部子模块
  - 现有 7 个 check（check-meta / index / sourcing / reviews / plan / post-dev-verify / traceability）改造为 plugin
  - pre-commit / phase-transition / submit / CI / PreToolUse 切到 runner（覆盖 hooks / ci / scripts / skills / lifecycle 五类触面）
  - `gate-checklist.md` 改为渲染产物
  - 关闭 H1 / H3 / H4 / H5
  - escape hatch 收敛 + audit log 落盘
- **不包含**：
  - H2 rollback 门禁（中优先级，下一轮迭代）
  - testing → completed 弱门禁加固（中优先级）
  - 新增门禁规则——本次纯收敛
  - governance 类跨需求门禁（如 legacy 数量阈值告警）

### 4 PR 各自合入价值

| PR | 合入后状态 | 独立可上线 |
|---|---|---|
| F-001 | runner 骨架 + 2 个 adapter（meta/index）+ make gates-validate；旧入口未变 | 是（中间态，但旧入口仍工作） |
| F-002 | 全量 7 个 check adapter + pre-commit/post-dev/CI 切到 runner | 是（旧入口为薄壳） |
| F-003 | 关闭 H1/H3/H4/H5；submit 与 next 同源 | 是（缺口闭合） |
| F-004 | gate-checklist.md 渲染产物化 + 删除旧入口 | 是（终态） |

每个 PR 都可独立 revert（plan.md D-001 已立此判据）。

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 改造节奏 | 一次性大爆炸 / 多 PR 增量 | 多 PR 增量（4 个 PR） | 触面广，回滚成本控制（plan.md D-001） |
| Registry 表达力 | 纯配置驱动 / 仅元数据 + 代码 | 仅元数据 + 代码 | 避免 YAML 编程，复杂逻辑回 Python（plan.md D-002） |
| 旧入口处理 | 立刻删 / 兼容期保留 | 兼容期保留至 F-004 | 双跑等价性需要旧脚本作为 baseline |
| Plugin 语言 | Bash / Python | Python | scripts/lib 已是 Python（来源：scripts/lib/check_reviews.py:1），生态一致 |
| 测试为强制项 | 可选 / 强制 | 强制 | registry 加载期校验 fixtures 与测试同名，缺测试拒收 |

## 待澄清清单

1. runner 性能 SLA 是否要立硬指标——当前文档写"≤ 现状"，是否需要"95p ≤ 1s"或类似可断言的指标？倾向：不立硬指标，CI 时间作为隐式上限。
2. audit log 保留期——每次 trigger 都写一份 JSON，长期会膨胀。是否需要按月归档 / 限定保留 90 天？
3. escape_hatch 是否要做 RBAC——`--force-with-blockers` 当前只要 reason，不要求"谁有权限"。是否需要审批人字段？
4. Bash 写保护白名单粒度——按"调用方进程名（save-review.sh）"还是"环境变量（CLAUDE_GATES_BYPASS=...）"？两种各有取舍。
5. gate-checklist.md 渲染产物的强约束——`<!-- generated -->` 标记 + CI 校验是否还要加"任何人改 registry.yaml 必须 PR 同时附渲染产物 diff"？
