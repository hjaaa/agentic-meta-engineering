---
name: managing-requirement-lifecycle
description: 需求全生命周期管理伞形 Skill，被 8 个 /requirement:* 命令共用。负责阶段切换、门禁校验、状态持久化、PR 提交。
---

## 什么时候用

用户通过 `/requirement:*` 命令，或口头说"新建需求 / 继续需求 / 下一阶段 / 保存进度 / 查看状态 / 回退 / 列出需求 / 提交 PR"时。

## 核心流程

1. **识别意图**：映射到 8 个子动作之一
   - 新建 → bootstrap（创建分支+目录+meta.yaml，委托 `requirement-bootstrapper`）
   - 继续 → 委托 `requirement-session-restorer`
   - 下一阶段 → 门禁校验（见 `reference/gate-checklist.md`，含 plan.md 软校验；**清单中 `bash scripts/...` 形式的检查项必须用 Bash 工具真实执行，以退出码判定，不允许读清单自答**）→ 若 `python3 scripts/gates/run.py --trigger=adapter --legacy=check-plan --req=<REQ-ID>` 出 warning 主动提示刷新 plan.md → 更新 phase
   - 保存 → 委托 `requirement-progress-logger`
   - 查看状态 → 读 meta.yaml 输出阶段+最近动作
   - 回退 → 归档当前 artifacts + 改 phase + 写 notes.md
   - 列出 → 扫 `requirements/*/meta.yaml`，输出需求索引
   - **提交 PR** → 按 `reference/submit-rules.md` 做前置门禁、推分支、开 PR、回写 `pr_url` / `pr_number`
   - 归档 → archive（phase=testing|completed → completed + archived_at；委托 `archive_runner.archive_requirement`）

2. **状态持久化**：每次阶段变更必须更新 `meta.yaml` 的 `phase` + 追加 `gates_passed`；submit 动作只回写 PR 字段，不改 phase

3. **门禁校验**：阶段切换前必走 `reference/gate-checklist.md`；submit 走同文件的"submit 前置门禁"小节。**逐条执行**：`bash scripts/...` 形式的命令型检查项必须用 Bash 工具真跑（看退出码），文件/字段/标记类检查项必须 Read/Grep 真验证——禁止"读清单自答通过"

## 门禁校验补充：派发链强制结构 4 gate

REQ-2026-008 新增以下 4 个 gate，已注册在 `scripts/gates/registry.yaml`，在对应触发点自动运行：

| Gate | 触发点 | 核心校验 | severity |
|---|---|---|---|
| `GATE-POST-DEV-RECEIPT` | phase-transition（development→testing）/ submit | features.json 中每个 done feature 必须有 `artifacts/tasks/<fid>.receipt.json`，且 `status ∈ {DONE, DONE_WITH_CONCERNS}` | error |
| `GATE-TOUCHES-VIOLATION` | phase-transition / submit | 所有 `artifacts/tasks/<fid>.receipt.json` 的 `touches_violations[]` 必须为空（开发期 touches_guard.py 软记的越界写入在此硬挡） | error |
| `GATE-FEATURES-SCHEMA` | pre-commit / phase-transition / submit / ci（changed_files: `requirements/*/artifacts/features.json`） | features.json 结构符合 `features-schema.yaml` | error |
| `GATE-TASK-FRONTMATTER` | pre-commit / phase-transition / submit / ci（changed_files: `requirements/*/artifacts/tasks/*.md`） | task.md frontmatter 符合 `task-frontmatter-schema.yaml`（含 `touches` 字段必填） | error |

**豁免约束**：4 个 gate 均**不**带 `legacy-bypass` tag，meta.yaml `legacy: true` 无法豁免它们。历史 completed REQ 通过 trigger / changed_files 路径自然隔离，不依赖 legacy 短路（D-005 #2 / D-006 V-07 修订）。

## D-009 例外保留说明（next / submit / archive 不转发）

以下 3 个命令是 D-009 的例外项，**不转发到 /workflow:***，保留实际旧实现：

| 命令 | 处理方式 | 原因 |
|---|---|---|
| `/requirement:next` | 调用本 Skill 的 **phase-transition** 子动作 + PHASE_REQUIREMENTS 校验 | D-009 例外：保留至 Plan 6 自举验证通过；新链路为 `/workflow:next` |
| `/requirement:submit` | 保留旧实现 + flag 直传到旧 submit Skill | 新引擎语义由 standard-8phase yaml 末端 **pr-submit** 节点承载（F-003） |
| `/requirement:archive` | 保留旧实现 | 新引擎语义由 **archive-finalize** 节点承载 |

兼容期截至 2026-08-08，届时随 Plan 6 自举验证同步评估物理删除时机。

## 硬约束

- ❌ 禁止跳过门禁（例：从 `definition` 直接跳 `detail-design`）
- ❌ 禁止在非功能分支上 bootstrap（会被 Hook 拦截）
- ❌ 禁止 submit 推进 phase（PR 合并不代表测试完成，不能跳过 testing 阶段）
- ❌ 禁止"读清单自答通过"——`bash scripts/...` 形式的门禁项必须用 Bash 工具真跑；缺退出码或缺 stderr 关键行 = 没跑
- ✅ `meta.yaml` 更新必须原子：先写临时文件再 mv（避免中间状态）
- ✅ 未知意图必须向用户澄清，不得"猜测"后擅自推进

## 参考资源

- [`reference/phase-rules.md`](reference/phase-rules.md) — 8 阶段定义 + 切换规则
- [`reference/gate-checklist.md`](reference/gate-checklist.md) — 各阶段门禁具体检查项 + submit 前置门禁
- [`reference/submit-rules.md`](reference/submit-rules.md) — `/requirement:submit` 的执行细节
- [`reference/archive-rules.md`](reference/archive-rules.md) — `/requirement:archive` 的执行细则
- [`templates/meta.yaml.tmpl`](templates/meta.yaml.tmpl) — 新建需求的 meta.yaml 模板
- [`templates/plan.md.tmpl`](templates/plan.md.tmpl) — 新建需求的 plan.md 模板
- [`templates/pr-body.md.tmpl`](templates/pr-body.md.tmpl) — `/requirement:submit` 的 PR 正文模板
- [`reference/blocker-conventions.md`](reference/blocker-conventions.md) — 主 Agent 识别与记录 blocker / blocker-resolved 事件的行为约定
