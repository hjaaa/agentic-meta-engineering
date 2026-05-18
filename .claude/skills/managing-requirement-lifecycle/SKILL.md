---
name: managing-requirement-lifecycle
description: 需求全生命周期管理伞形 Skill，被 8 个 /requirement:* 命令共用。负责状态持久化、PR 提交、归档；阶段切换在 F-012 落地前仍由本 Skill 承载，落地后将统一到 /workflow:next
---

## 什么时候用

用户通过 `/requirement:*` 命令，或口头说"新建需求 / 继续需求 / 保存进度 / 查看状态 / 回退 / 列出需求 / 提交 PR / 归档"时。

> **F-012 现状（hotfix 后修订）**：`/workflow:next` 命令尚未落地（workflow main loop 仍是 stub）。
> 在 F-012 落地之前，阶段切换 + PHASE_REQUIREMENTS 校验链仍由本 Skill 承担（用户在主对话中
> 说明意图 → 本 Skill 写 `meta.yaml.phase` + 跑 `scripts/gates/run.py --trigger=phase-transition`）。
> F-012 落地后将统一到 standard-8phase yaml workflow 的 phase-transition 节点；下文凡出现
> `/workflow:next [F-012 待落地]` 的描述均按此规则解读。

## 核心流程

1. **识别意图**：映射到 8 个子动作之一
   - 新建 → bootstrap（创建分支+目录+meta.yaml，委托 `requirement-bootstrapper`）
   - 继续 → 委托 `requirement-session-restorer`
   - 保存 → 委托 `requirement-progress-logger`
   - 查看状态 → 读 meta.yaml 输出阶段+最近动作
   - 回退 → 归档当前 artifacts + 改 phase + 写 notes.md
   - 列出 → 扫 `requirements/*/meta.yaml`，输出需求索引
   - **提交 PR** → 按 `reference/submit-rules.md` 做前置门禁、推分支、开 PR、回写 `pr_url` / `pr_number`
   - 归档 → archive（phase=testing|completed → completed + archived_at；委托 `archive_runner.archive_requirement`）

2. **状态持久化**：每次状态变更必须更新 `meta.yaml` 字段；submit 动作只回写 PR 字段，不改 phase

3. **门禁校验**：submit 走 `reference/gate-checklist.md` 中的"submit 前置门禁"小节。**逐条执行**：
   `bash scripts/...` 形式的命令型检查项必须用 Bash 工具真跑（看退出码），文件/字段/标记类
   检查项必须 Read/Grep 真验证——禁止"读清单自答通过"

## 门禁校验补充：派发链强制结构 4 gate

REQ-2026-008 新增以下 4 个 gate，已注册在 `scripts/gates/registry.yaml`，在对应触发点自动运行：

| Gate | 触发点 | 核心校验 | severity |
|---|---|---|---|
| `GATE-POST-DEV-RECEIPT` | phase-transition（development→testing）/ submit | features.json 中每个 done feature 必须有 `artifacts/tasks/<fid>.receipt.json`，且 `status ∈ {DONE, DONE_WITH_CONCERNS}` | error |
| `GATE-TOUCHES-VIOLATION` | phase-transition / submit | 所有 `artifacts/tasks/<fid>.receipt.json` 的 `touches_violations[]` 必须为空 | error |
| `GATE-FEATURES-SCHEMA` | pre-commit / phase-transition / submit / ci（changed_files: `requirements/*/artifacts/features.json`） | features.json 结构符合 `features-schema.yaml` | error |
| `GATE-TASK-FRONTMATTER` | pre-commit / phase-transition / submit / ci（changed_files: `requirements/*/artifacts/tasks/*.md`） | task.md frontmatter 符合 `task-frontmatter-schema.yaml`（含 `touches` 字段必填） | error |

**豁免约束**：4 个 gate 均**不**带 `legacy-bypass` tag，meta.yaml `legacy: true` 无法豁免它们。
历史 completed REQ 通过 trigger / changed_files 路径自然隔离，不依赖 legacy 短路（D-005 #2 / D-006 V-07 修订）。

## 阶段切换：F-012 待落地阶段的过渡处理

设计目标：阶段切换（如 definition → tech-research）统一走 standard-8phase yaml workflow
的 phase-transition 节点；用户入口 `/workflow:next [F-012 待落地]`。

**现状（F-012 落地前）**：`/workflow:next` 命令尚不可用；用户在主对话中说明"切到下一阶段"
后，本 Skill 直接：
1. 跑 `python3 scripts/gates/run.py --trigger=phase-transition --req=<REQ-ID> --from=<X> --to=<Y>`
2. error 全过后写 `meta.yaml.gates_passed` + 切 `meta.yaml.phase`
3. 调 `requirement-progress-logger` 写 `[phase-transition]` 事件

如需手动跑某 trigger 的全套门禁（落地前/后通用），仍可用 CLI 直入：

```bash
python3 scripts/gates/run.py \
  --trigger=phase-transition \
  --req=<REQ-ID> \
  --from=<from-phase> \
  --to=<to-phase>
```

退出码 0 = 全门禁过；非 0 = 有 error；详见 `scripts/gates/registry.yaml`。

## 硬约束

- ❌ 禁止跳过门禁（例：从 `definition` 直接跳 `detail-design`，相邻校验由 runner `_validate_phase_args` 拦下）
- ❌ 禁止在非功能分支上 bootstrap（会被 Hook 拦截）
- ❌ 禁止 submit 推进 phase（PR 合并不代表测试完成，不能跳过 testing 阶段）
- ❌ 禁止"读清单自答通过"——`bash scripts/...` 形式的门禁项必须用 Bash 工具真跑；缺退出码或缺 stderr 关键行 = 没跑
- ✅ `meta.yaml` 更新必须原子：先写临时文件再 mv（避免中间状态）
- ✅ 未知意图必须向用户澄清，不得"猜测"后擅自推进

## 参考资源

- [`reference/gate-checklist.md`](reference/gate-checklist.md) — 各阶段门禁具体检查项 + submit 前置门禁
- [`reference/submit-rules.md`](reference/submit-rules.md) — `/requirement:submit` 的执行细节
- [`reference/archive-rules.md`](reference/archive-rules.md) — `/requirement:archive` 的执行细则
- [`archive.md`](../../commands/requirement/archive.md) — worktree cleanup 三重保护语义（D-008 / D-009）
- [`templates/meta.yaml.tmpl`](templates/meta.yaml.tmpl) — 新建需求的 meta.yaml 模板
- [`templates/plan.md.tmpl`](templates/plan.md.tmpl) — 新建需求的 plan.md 模板
- [`templates/pr-body.md.tmpl`](templates/pr-body.md.tmpl) — `/requirement:submit` 的 PR 正文模板
- [`reference/blocker-conventions.md`](reference/blocker-conventions.md) — 主 Agent 识别与记录 blocker / blocker-resolved 事件的行为约定

> phase-rules.md（8 阶段定义 + 切换规则）已移除——canonical phase 枚举单一事实源在
> `context/team/engineering-spec/meta-schema.yaml` `enums.phase`；切换规则由 runner
> `_validate_phase_args` + canonical_phases.load_adjacent_phases() 强制实施。
