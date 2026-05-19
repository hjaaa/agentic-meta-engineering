---
id: 20260519-remove-human-signoff
title: 移除 human sign-off，改为软性人工确认
created_at: 2026-05-19T03:25:00Z
refs-requirement: true
---

# 20260519-remove-human-signoff · 移除 human sign-off 并改为软性人工确认

> 设计权威单源：`docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md`（2026-05-19 起草，状态待审阅）。
> 本文档为该 spec 在 requirement 层的语义化引用与验收落地；如发现偏差，按 `plan.md` D-000 决策反修 spec，并在本文件 supersedes 标记。

## 背景

当前项目把代码审查和阶段推进拆成两类人工动作（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:9）：

1. **workflow `approval` 节点**：用户在流程中执行 approve / reject / cancel。
2. **review verdict `human_signoff`**：用户通过 `/code-review:signoff` 把签字字段写入 `requirements/<REQ>/reviews/*.json`。

第二类动作已经形成一套硬门禁：`human_signoff` schema + `save_review.py signoff` + `scripts/check-signoff.sh` + `check_reviews.R003/R007` + `feature-lifecycle-manager` + review 报告模板 + 命令/技能文档 + 测试（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:13）。结果是：AI review 即使结论可接受，仍需用户再写一次签字字段才能让 feature 转 done 或通过阶段 gate（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:14）。

本需求要完整下线 `human_signoff` 数据模型与硬门禁，同时保留"人类可以确认或驳回"的交互体验——确认是流程上的软确认，不再写入 review JSON，不再作为 gate 的硬条件（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:16）。

## 目标

- **主目标**：删除 `human_signoff` 字段、枚举、判定 helper、CLI、wrapper、技能、命令和专属测试，所有 review gate 不再因缺少签字字段失败（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:20）。
- **次要目标**：
  - 代码审查完成后仍向用户展示结论并等待 approve/reject，但该确认只影响当前流程动作，不写入 verdict（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:22）。
  - workflow 阶段级 `approval` 机制保留；命名和文案从 `signoff` 调整为 `confirm`，表达为人工确认而非签字（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:23）。
  - 清理围绕 human sign-off 生成的文档、模板、agent 指令、历史设计说明，以及当前需求 artifacts 中的显性 sign-off 文案（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:24）。

## 非目标

- **不**移除 workflow 引擎的 `approval` 节点类型（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:27）。
- **不**让 AI review 自动合并或自动转 done；仍需要用户对当前流程给出确认（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:28）。
- **不**改变 review verdict 的核心结论枚举：`looks_clean` / `needs_attention` / `blocked`（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:30）。
- **不**改变 artifact hash drift、schema 合法性、supersedes 链、done feature review 覆盖等质量 gate（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:31）。
- **不**改 GitHub PR review 或 CI 规则，除非现有文档把它们误描述为 human sign-off（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:32）。

## 用户场景

### 场景 1：开发者代码审查后软确认

- **角色**：feature 开发者
- **前置**：单个 feature 实现完成，触发 `/code-review` 生成 review JSON + Markdown 报告
- **主流程**（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:46）：
  1. `/code-review` 生成 review JSON 与 Markdown 报告
  2. 报告展示机器结论、required fixes、suggestions、follow-up notes
  3. 主流程在主对话中提示用户：`approve`（接受本轮 review 结论，允许 feature lifecycle 继续）或 `reject`（说明反馈，回到修复循环）
  4. 用户 `approve` 后，feature lifecycle 根据 review conclusion 推进：
     - `looks_clean` 且无 required fixes → 允许转 `done`
     - `needs_attention` → 默认要求修复或用户明确接受风险后继续
     - `blocked` → 不可继续，必须修复并重审
- **期望结果**：
  - feature lifecycle 不再调 `check-signoff.sh`，不再读 `human_signoff` 字段
  - review JSON 不含 `human_signoff` 字段
  - 用户软确认不持久化为 verdict 字段（仅在当前会话/流程推进中体现）

### 场景 2：阶段推进时不再校验签字字段

- **角色**：requirement 开发者
- **前置**：需求阶段切换前跑 `GATE-REVIEW-VERDICT`
- **主流程**（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:58）：
  - `GATE-REVIEW-VERDICT` 不再要求 latest verdict 带签字字段
  - R001：目标阶段需要的 review 存在
  - R002：review JSON schema 合法
  - R003：latest conclusion 不能是 `blocked` 或旧值 `rejected`
  - R004：`needs_attention` 仍作为 warning 或 strict error
  - R005：reviewed artifact hash 未漂移
  - R006：supersedes 链合法
  - R007：切到 testing 时，done feature 都有 latest code review 且 conclusion 非 blocked/rejected
- **期望结果**：缺 `human_signoff` 的 latest review 不阻断阶段切换；blocked / rejected 仍失败

### 场景 3：workflow approval 节点改名为 confirm

- **角色**：standard-8phase workflow 推进者
- **前置**：标准 8 阶段 yaml 中存在 6 个 `*-signoff` approval 节点
- **主流程**（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:70）：
  - `req-signoff` → `req-confirm`
  - `tech-research-signoff` → `tech-research-confirm`
  - `outline-design-signoff` → `outline-design-confirm`
  - `detail-design-signoff` → `detail-design-confirm`
  - `task-signoff` → `task-confirm`
  - `test-final-signoff` → `test-final-confirm`
  - `pr-merged-gate` 保持为合并确认，不属于 human sign-off（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:79）
- **期望结果**：节点 ID、文案、依赖链中的引用全部对齐；`/workflow:approve` / `/workflow:reject` 仍可对新 confirm 节点正常工作

### 场景 4：仓库历史 review JSON 字段清理

- **角色**：本需求开发者（执行迁移步骤）
- **前置**：仓库内 `requirements/*/reviews/*.json` 部分仍含 `human_signoff` 字段
- **主流程**（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:100）：
  1. 机械迁移：只删 `human_signoff` 字段，不动 `review_id` / `conclusion` / `score` / `reviewed_artifacts`
  2. `process.txt` 中已有 `[signoff]` 时间线作为历史事件保留
  3. 当前活跃或测试中的需求 artifacts 中"待 sign-off"提示改为"待人工确认"或删除
- **期望结果**：迁移后 `rg human_signoff requirements/` 命中数收敛到允许的历史保留范围（开放问题 §2 确认后定数）[待用户确认]

## 非功能需求

- **历史兼容性**：spec §设计原则 明确"历史兼容以迁移为主：仓库内已提交的当前 artifacts 需要清理；老 completed 需求可通过一次性迁移删除字段或在 schema 里忽略未知字段，具体实施时优先选择最小可验证路径"（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:39）。
- **保留收紧的 review schema 规则**（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:94）：
  - `required_fixes` 非空时 conclusion 必须是 `needs_attention` 或 `blocked`
  - score 低于阈值时 conclusion 不能是 `looks_clean`
  - blocker issue 仍要求 conclusion 为 `blocked`
- **命名语义对齐**：保留的人工动作统一叫 `confirm` / `approve` / `reject`，`signoff` 表示签字应删除或改名（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:40）。

## 验收标准

直接对应 spec §成功标准（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:209）+ §验证命令（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:180）。

| ID | 验收点 | 验证方式 |
|---|---|---|
| AC-1 | 仓库内不存在可执行的 human sign-off 入口 | `ls scripts/lib/signoff.py scripts/check-signoff.sh .claude/commands/code-review/signoff.md .claude/skills/code-review-signoff/` 全部 ENOENT |
| AC-2 | review schema 不再定义 `human_signoff` | `rg "human_signoff\|signoff_decision\|signoff_source" context/team/engineering-spec/review-schema.yaml` 返回 0 行 |
| AC-3 | gate 不再因缺签字字段失败 | `python3 scripts/gates/run.py --trigger=ci --strict` 退出码 0；且不输出 R003/R007 签字相关 error |
| AC-4 | code review 报告和 feature lifecycle 使用"人工确认"文案 | `rg "sign-off\|待 sign-off\|signoff" .claude/skills/feature-lifecycle-manager/ .claude/skills/code-review-report/` 0 命中（或仅命中历史经验文档） |
| AC-5 | 用户仍可 approve / reject 当前流程，但不写 verdict 签字字段 | `/workflow:approve` 仍可工作；review JSON 中无 `human_signoff` 字段（人工/单元/集成测试三重覆盖） |
| AC-6 | 单元测试 `tests/lib/test_check_reviews.py` 与 save_review CR 规则全过；删除 signoff CLI / tty / trivial / 循环导入测试 | `pytest tests/lib/test_check_reviews.py tests/gates/ tests/integration/ -q` 全绿；且原 signoff 专属测试文件已删 |
| AC-7 | workflow standard-8phase yaml 中 6 个 `*-signoff` 节点改名为 `*-confirm`，依赖链同步 | `rg "signoff" .claude/workflows/requirement/standard-8phase.yaml` 0 命中 |
| AC-8 | 全量 strict gate 通过 | `python3 scripts/gates/run.py --trigger=ci --strict` 退出码 0 |
| AC-9 | `rg "human_signoff\|code-review:signoff\|check-signoff\|sign-off\|signoff" scripts .claude context tests requirements` 不命中当前流程、命令、schema、gate 或模板中的有效指令（允许命中历史说明）（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:185） | 人工抽检 + 残留扫描分类报告 |

## 待澄清清单

来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:203（开放问题三项）。

- **C-1（开放问题 §1）**：`needs_attention` 是否允许用户软确认后继续转 done，还是必须修复到 `looks_clean`？
  - 假设：默认要求修复或显式接受风险（与 spec §目标行为 §代码审查后 第 4 步对齐），即"用户显式接受风险"路径允许转 done，命令层需要把这个分支明文写清楚（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:54）
  - 验证时机：detail-design 阶段决定 feature-lifecycle-manager 的实现分支
  - **[待用户确认]**
- **C-2（开放问题 §2）**：历史 completed 需求中的 `human_signoff` 字段是否全部删除，还是只清理当前活跃需求与模板？
  - 假设：本需求范围内仅清理当前活跃（含 testing / archived 但未冻结的）需求；已 archived completed 需求保留 schema 字段做历史读取兼容（review schema 删字段后改为忽略未知字段）
  - 风险：若 schema 严格校验未知字段会导致历史 review JSON 加载失败；需在 detail-design 选定"删字段 + 忽略未知"还是"全量批量迁移"
  - **[待用户确认]**
- **C-3（开放问题 §3）**：workflow 节点 ID 改名是否需要兼容旧 `run-state.jsonl`，还是允许只影响新 workflow？
  - 假设：本期允许只对新 workflow 生效；当前活跃 run 仅本 REQ（bootstrap 阶段，jsonl 不含 `*-signoff` 节点事件），不存在 break 历史 run 风险
  - 风险：若未来 standard-8phase 出现一致性扫描会卡掉旧 jsonl；本期不引入此扫描即可
  - **[待用户确认]**
- **C-4（spec §验证命令 第 3 条尺度）**：`rg "human_signoff|code-review:signoff|check-signoff|sign-off|signoff" scripts .claude context tests requirements` 允许命中的"历史说明"具体白名单是哪些？
  - 假设：白名单为 `context/team/experience/`（历史经验沉淀）+ `context/team/engineering-spec/specs/2026-04-30-code-review-human-checkpoints.md`（历史 spec 自身需保留并加废弃声明）+ `requirements/*/notes.md`（完成需求过程记录）
  - 验证时机：testing 阶段执行残留扫描时与用户对齐白名单
  - **[待用户确认]**
