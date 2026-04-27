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
  - 关闭 4 个高优先级缺口：H1（R005 写回事务化，对应 scripts/lib/check_reviews.py:152 的副作用）、H3（submit 与 next 同源，对应上文 submit-rules.md:113 vs gate-checklist.md:71 的割裂）、H4（PR 合并状态闭环，对应 submit-rules.md:75 缺反向校验）、H5（Bash 写 reviews/*.json 拦截，对应 protect-branch.sh:30 的绕过点）
  - 新增门禁的成本降到"填 9 字段 + 写 1 个类 + 写 3 个测试"
  - 门禁执行有结构化 audit log，可被未来的 governance 类工具消费

## 用户场景

### 场景 1：开发者新增一条门禁

- **角色**：仓库内 Skill / 工具开发者
- **前置**：识别出某个新的"要在某事件下校验某状态"的需求（如 PR 合并状态校验）
- **主流程**：
  1. 跑脚手架 `python scripts/gates/scaffold.py new-gate` 交互式问 9 字段，生成 registry 条目骨架
  2. 跑 `python scripts/gates/scaffold.py new-plugin --id <GATE-ID>` 生成 plugin + test 骨架
  3. 实现 plugin 的 `precheck` / `run` / 必要时 `rollback`
  4. 写覆盖 pass / fail / skip 三种用例的测试
  5. 跑 `make gates-validate`：registry schema + plugin 加载 + 测试一次过
- **期望结果**：单一 PR 即合入；不需要改 CI yml / pre-commit / Hook / Skill 任何文件

### 场景 2：/requirement:next 触发阶段切换门禁

- **角色**：主对话 Agent（执行 `managing-requirement-lifecycle` 的 next 流程）
- **前置**：用户已运行 `/requirement:next`，当前 phase = X，目标 phase = Y
- **主流程**：
  1. Agent 调 `python scripts/gates/run.py --trigger=phase-transition --req <ID> --from X --to Y`
  2. runner 按 registry 过滤出适用 gate，按 dependencies 拓扑排序
  3. 在事务包裹内逐个执行，任一 error 触发已运行 gate 的 rollback
  4. 输出 JSON Report：`{passed, failed, skipped}`
  5. Agent 读 Report 决定是否更新 meta.yaml.phase
- **期望结果**：Agent 不再"读 Markdown 清单逐条解释"，gate 失败有统一格式 + fix hint

### 场景 3：CI 跑全量门禁

- **角色**：GitHub Actions runner
- **前置**：PR 提交 / push 到 main/develop
- **主流程**：
  1. 单一 step：`python scripts/gates/run.py --trigger=ci --strict`
  2. runner 自行扫描所有 requirements/* 并按各自 phase 跑相应 gate 集合
  3. audit log 写入 `scripts/gates/audit/<date>/<event>.json`，可被 PR comment / dashboard 消费
- **期望结果**：CI 配置从当前 5 个 step 收敛到 1 个

### 场景 4：开发者跑 `/requirement:submit`

- **角色**：用户 / 主 Agent
- **前置**：phase ∈ {development, testing}，本地有领先 origin 的 commit
- **主流程**：
  1. submit 流程调 `run.py --trigger=submit --req <ID>`
  2. runner 复用 next 的 gate 集合（含 R007 / 工作区 / sourcing）+ submit 特有 gate（gh auth / base 可达 / **PR 合并状态**）
  3. PR 合并状态 gate 命中时阻断并提示走 `/requirement:next`
- **期望结果**：submit 与 next 共享同一套 review / sourcing 校验，结果一致

## 非功能需求

- **性能**：runner 单次端到端执行不应显著高于现状（现状是 quality-check.yml 串跑 4 个 step，参见 .github/workflows/quality-check.yml:28）。是否需要立硬性 SLA 指标，待用户确认 [待用户确认]
- **兼容性**：旧入口（scripts/check-*.sh、post-dev-verify.sh）保留兼容期，至少跨两个 PR 周期；F-004 才删除。meta.yaml / review-schema.yaml / 既有 reviews/*.json 全部不变。
- **CI 双跑等价**：每个 PR 内旧脚本与 runner 对相同输入产生相同退出码 + 相同 stderr 关键行；diff 必须为空才合入。
- **可观测性**：每次 runner 执行写一份结构化 audit JSON（trigger / passed / failed / skipped / escape_used / actor），路径 `scripts/gates/audit/<YYYY-MM-DD>/<event>-<timestamp>.json`。escape_hatch 每次使用必须带 `reason` 字段，写入 audit + process.txt。
- **安全/合规**：registry.yaml 的 `escape_hatches` 段是 PR review 焦点，新增一条须通过评审（参考既有 `legacy: true` 的治理思路，来源：context/team/engineering-spec/meta-schema.yaml:131）。Bash 写保护正则需有白名单机制以避免误伤合法路径（如 save-review.sh 子进程的写入）。

## 范围

- **包含**（详见 plan.md，与本节一致）：
  - `scripts/gates/` 新目录及其全部子模块
  - 现有 7 个 check（check-meta / index / sourcing / reviews / plan / post-dev-verify / traceability）改造为 plugin
  - pre-commit / phase-transition / submit / CI / PreToolUse 切到 runner
  - `gate-checklist.md` 改为渲染产物
  - 关闭 H1 / H3 / H4 / H5
  - escape hatch 收敛 + audit log 落盘
- **不包含**：
  - H2 rollback 门禁（中优先级，下一轮迭代）
  - testing → completed 弱门禁加固（中优先级）
  - 新增门禁规则——本次纯收敛
  - governance 类跨需求门禁（如 legacy 数量阈值告警）

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
