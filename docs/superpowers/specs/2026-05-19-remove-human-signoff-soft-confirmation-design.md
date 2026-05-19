# 移除 human sign-off 并改为软性人工确认设计

日期：2026-05-19
状态：待审阅
范围：agentic-meta-engineering 仓库内 review verdict、feature lifecycle、workflow approval、文档与测试

## 背景

当前项目把代码审查和阶段推进拆成两类人工动作：

- workflow `approval` 节点：用户在流程中执行 approve/reject/cancel。
- review verdict `human_signoff`：用户通过 `/code-review:signoff` 把签字字段写入 `requirements/<REQ>/reviews/*.json`。

第二类动作已经形成一套硬门禁：`human_signoff` schema、`save_review.py signoff`、`scripts/check-signoff.sh`、`check_reviews.R003/R007`、`feature-lifecycle-manager`、review 报告模板、命令/技能文档和测试。它的结果是 AI review 即使结论可接受，也必须再写一个签字字段才能让 feature 转 done 或通过阶段 gate。

目标是完整去掉 `human_signoff` 这套数据模型与硬门禁，同时保留“人类可以确认或驳回”的交互体验。确认是流程上的软确认，不再写入 review JSON，不再作为 gate 的硬条件。

## 目标

1. 删除 `human_signoff` 字段、枚举、判定 helper、CLI、wrapper、技能、命令和专属测试。
2. 所有 review gate 不再因缺少签字字段失败。
3. 代码审查完成后仍向用户展示结论并等待 approve/reject，但这个确认只影响当前流程动作，不写入 verdict。
4. workflow 阶段级 `approval` 机制保留；命名和文案从 `signoff` 调整为 `confirm`，表达为人工确认而非签字。
5. 清理围绕 human sign-off 生成的文档、模板、agent 指令、历史设计说明和当前需求 artifacts 中的显性 sign-off 文案。

## 非目标

1. 不移除 workflow 引擎的 `approval` 节点类型。
2. 不让 AI review 自动合并或自动转 done；仍需要用户对当前流程给出确认。
3. 不改变 review verdict 的核心结论枚举：`looks_clean` / `needs_attention` / `blocked`。
4. 不改变 artifact hash drift、schema 合法性、supersedes 链、done feature review 覆盖等质量 gate。
5. 不改 GitHub PR review 或 CI 规则，除非现有文档把它们误描述为 human sign-off。

## 设计原则

- 签字字段归零：不再生成、读取或要求 `human_signoff`。
- 软确认不落 verdict：用户确认只体现在当前会话/流程推进，不污染 review JSON。
- gate 只校验机器可验证事实：review 存在、schema 合法、结论未阻断、artifact 未漂移、code review 覆盖 done features。
- 历史兼容以迁移为主：仓库内已提交的当前 artifacts 需要清理；老 completed 需求可通过一次性迁移删除字段或在 schema 里忽略未知字段，具体实施时优先选择最小可验证路径。
- 命名对齐语义：`signoff` 表示签字，应删除或改名；保留的人工动作统一叫 `confirm` / `approve` / `reject`。

## 目标行为

### 代码审查后

1. `/code-review` 生成 review JSON 和 Markdown 报告。
2. 报告展示机器结论、required fixes、suggestions、follow-up notes。
3. 主流程提示用户：
   - `approve`：接受本轮 review 结论，允许 feature lifecycle 继续。
   - `reject`：说明反馈，回到修复循环。
4. 用户 approve 后，feature lifecycle 根据 review 结论推进：
   - `looks_clean` 且无 required fixes：允许转 `done`。
   - `needs_attention`：默认要求修复或用户明确接受风险后继续；实现计划需在命令/技能层把这个分支写清楚。
   - `blocked`：不可继续，必须修复并重审。

### 阶段推进时

`GATE-REVIEW-VERDICT` 不再要求 latest verdict 带签字。它仍执行：

- R001：目标阶段需要的 review 存在。
- R002：review JSON schema 合法。
- R003：latest conclusion 不能是 `blocked` 或旧值 `rejected`。
- R004：`needs_attention` 仍作为 warning 或 strict error。
- R005：reviewed artifact hash 未漂移。
- R006：supersedes 链合法。
- R007：切到 testing 时，done feature 都有 latest code review，且 conclusion 非 blocked/rejected。

### workflow approval 节点

标准 8 阶段中的这些节点保留人工交互，但改名和文案：

- `req-signoff` → `req-confirm`
- `tech-research-signoff` → `tech-research-confirm`
- `outline-design-signoff` → `outline-design-confirm`
- `detail-design-signoff` → `detail-design-confirm`
- `task-signoff` → `task-confirm`
- `test-final-signoff` → `test-final-confirm`

`pr-merged-gate` 保持为合并确认，不属于 human sign-off。

## 数据模型变更

### review schema

从 `context/team/engineering-spec/review-schema.yaml` 删除：

- `enums.signoff_decision`
- `enums.signoff_source`
- `fields.human_signoff`
- CR-1 中的 `is_signed_off(verdict)` 条件
- CR-4 中的 `is_signed_off(verdict) == False` 条件
- CR-8

保留并收紧的规则：

- `required_fixes` 非空时 conclusion 必须是 `needs_attention` 或 `blocked`。
- score 低于阈值时 conclusion 不能是 `looks_clean`。
- blocker issue 仍要求 conclusion 为 `blocked`。

### review JSON 历史内容

仓库内当前存在的 `human_signoff` 字段应删除。迁移脚本或机械修改需要满足：

- 只删除 `human_signoff` 字段，不改 `review_id`、`conclusion`、`score`、`reviewed_artifacts` 等审查事实。
- `process.txt` 中已有 `[signoff]` 时间线可以保留为历史事件，除非该需求明确纳入 artifact 清理范围。
- 当前活跃或测试中的需求 artifacts 里面向未来流程的 “待 sign-off” 提示要改为“待人工确认”或删除。

## 实现边界

### 删除或退役

- `.claude/commands/code-review/signoff.md`
- `.claude/skills/code-review-signoff/`
- `scripts/lib/signoff.py`
- `scripts/check-signoff.sh`
- `tests/commands/test_signoff_command.py`
- `tests/integration/test_feature_lifecycle_signoff_gate.py`
- `tests/lib/test_signoff_no_circular_import.py`

如果 `save_review.py` 仍有 `signoff` 子命令注册，需要删除 parser 分支和 re-export。`save_review.py` 保留 `save` verdict 的职责。

### 修改

- `scripts/lib/check_reviews.py`：删除 `SIGNOFF_PASS`、`is_signed_off` 和 R003/R007 的签字检查。
- `scripts/lib/save_review.py`：删除 CR-1/CR-4 对 `is_signed_off` 的依赖，删除 CR-8。
- `scripts/gates/plugins/review_verdict.py` 与 `review_verdict_ci.py`：沿用 `check_reviews` 新规则，不再暴露签字错误。
- `.claude/skills/feature-lifecycle-manager/SKILL.md`：把 “check-signoff wrapper 判定” 改为 “等待用户软确认 + review conclusion 判定”。
- `.claude/skills/code-review-report/SKILL.md` 和模板：把 “待 sign-off 提示” 改为 “人工确认提示”。
- `.claude/agents/code-quality-reviewer.md`：删除 “human_signoff 是卡点 B 专属字段” 的禁写说明，改为 “reviewer 只输出机器结论，不输出人工确认状态”。
- `.claude/workflows/requirement/standard-8phase.yaml`：节点 ID 和依赖从 `*-signoff` 改为 `*-confirm`；文案从签字改为确认。
- `.claude/commands/workflow/approve.md` / `reject.md`：如果仍写“人类专属签字”，改为“人工确认动作”。

### 文档清理

至少更新：

- `context/team/engineering-spec/specs/2026-04-30-code-review-human-checkpoints.md`
- `context/team/engineering-spec/design-guidance/gate-system-architecture.md`
- `context/team/ai-collaboration.md`
- onboarding / learning path 中关于 sign-off 的说明
- experience 文档中把历史事故保留为“历史机制”，避免误导当前流程
- 当前需求 task 文件中 `/code-review 通过且 sign-off=approved` 的验收项

## 测试策略

### 单元测试

- `check_reviews`：
  - latest review 无 `human_signoff` 时通过 R003。
  - blocked/rejected 仍失败。
  - done feature 有 latest code review 且 looks_clean 时 R007 通过。
  - done feature latest code review blocked 时 R007 失败。
- `save_review` CR 规则：
  - required_fixes 非空 + looks_clean 失败。
  - score < 70 + looks_clean 失败。
  - 不再测试 CR-8。

### 集成测试

- feature lifecycle：review looks_clean 后，用户软确认路径可以转 done，不调用 `check-signoff.sh`。
- phase-transition：缺 `human_signoff` 的 latest review 不阻断。
- CI gate：全仓 review verdict 校验不再报告未签字错误。

### 删除测试

删除 signoff CLI、tty 校验、trivial signoff 路径、重复签字、wrapper 判定和循环导入相关测试。若测试覆盖了仍然有价值的逻辑，例如 review schema 校验，应迁移到非 signoff 测试中。

## 迁移步骤

1. 先改 schema 和核心判定：`review-schema.yaml`、`check_reviews.py`、`save_review.py`。
2. 删除 signoff CLI 与 wrapper，并修正 import。
3. 改 feature lifecycle 与 review report 文案。
4. 改 workflow 节点命名和依赖。
5. 机械清理仓库内 `human_signoff` 字段和 sign-off 文案。
6. 更新测试与 fixtures。
7. 跑最小验证集，再跑全量 gate。

## 验证命令

实施完成后至少运行：

```bash
python3 -m pytest tests/lib/test_check_reviews.py tests/gates/ tests/integration/ -q
python3 scripts/gates/run.py --trigger=ci --strict
rg -n "human_signoff|code-review:signoff|check-signoff|sign-off|signoff" scripts .claude context tests requirements
```

第三条搜索允许命中历史说明，但不应命中当前流程、命令、schema、gate 或模板中的有效指令。

## 风险与缓解

- 风险：删除 `signoff.py` 后 `save_review.py` 仍引用旧 re-export。
  缓解：先删 parser 分支，再跑 import smoke test。
- 风险：历史 review JSON 删除字段导致 hash 或 fixture 漂移。
  缓解：迁移只改 review JSON，不改 reviewed artifacts；fixtures 与期望同步更新。
- 风险：`*-signoff` workflow 节点改名破坏既有 run-state。
  缓解：旧 run 保留兼容或只对新 workflow 生效；如果当前活跃 run 仍依赖旧 ID，实施计划需明确迁移策略。
- 风险：软确认语义不清导致 `needs_attention` 被误当作通过。
  缓解：feature lifecycle 明确 `needs_attention` 默认不自动 done，除非用户显式接受风险。
- 风险：文档中残留“AI 禁止签字”等旧机制，误导后续开发。
  缓解：实施末尾用 `rg` 做残留扫描，并逐项分类处理。

## 开放问题

1. `needs_attention` 是否允许用户软确认后继续转 done，还是必须修复到 `looks_clean`？
2. 历史 completed 需求中的 `human_signoff` 字段是否全部删除，还是只清理当前活跃需求与模板？
3. workflow 节点 ID 改名是否需要兼容旧 `run-state.jsonl`，还是允许只影响新 workflow？

## 成功标准

- 仓库内不存在可执行的 human sign-off 入口。
- review schema 不再定义 `human_signoff`。
- gate 不再因缺签字字段失败。
- code review 报告和 feature lifecycle 使用“人工确认”文案。
- 用户仍可以 approve/reject 当前流程，但该动作不写 verdict 签字字段。
- 全量测试和 `scripts/gates/run.py --trigger=ci --strict` 通过。
