# 阶段门禁检查清单

每次 `/requirement:next` 切阶段时，必须全部通过。失败则阻止切换并列出缺口。

## 通用前置（所有阶段切换都必跑）

- [ ] `bash scripts/check-meta.sh requirements/<REQ-ID>/meta.yaml` 退出码 = 0
  - 该脚本依据 `context/team/engineering-spec/meta-schema.yaml` 校验 schema / 枚举 / 格式 / 条件必填
  - 不同 phase 下校验项不同：bootstrap 阶段允许语义组为空；definition 起语义组必填；completed 阶段必填 outcome / completed_at
  - 任一 error 即视为"meta.yaml 不合法"，阻止阶段切换

## bootstrap → definition

- [ ] 通用前置通过（见上）
- [ ] 当前分支 = `meta.yaml.branch`
- [ ] `plan.md` 存在

## definition → tech-research

- [ ] `artifacts/requirement.md` 存在
- [ ] `bash scripts/check-sourcing.sh --requirement <REQ-ID>` 退出码 = 0
  - 依据 `context/team/ai-collaboration.md` §"刨根问底"三态规则把关
  - `[待补充]` 必须含假设四要素（内容/依据/风险/验证时机）≥3 个
  - `（来源：path:line）` 的路径与行号必须真实存在
  - error 阻止阶段切换；warning 仅提示（strict 由 CI 把关）
- [ ] 需求评审结论 ≠ `rejected`（由 `requirement-quality-reviewer` Agent 产生，Phase 2 可先跳过此校验，标记 "reviewer pending"）
- [ ] 所有"待用户确认"项已处理（无 `[待用户确认]` 遗留标记）

## tech-research → outline-design

- [ ] `artifacts/tech-feasibility.md` 存在
- [ ] 风险评估段落非空

## outline-design → detail-design

- [ ] `artifacts/outline-design.md` 存在
- [ ] 概要设计评审结论 ≠ `rejected`

## detail-design → task-planning

- [ ] `artifacts/detailed-design.md` 存在
- [ ] `artifacts/features.json` 合法 JSON + 每条 feature 有 `id`、`title`、`description`
- [ ] 详细设计评审结论 ≠ `rejected`

## task-planning → development

- [ ] 每个 `features.json` 里的 feature_id 在 `artifacts/tasks/` 下有对应 .md 文件
- [ ] 每个任务文件初始状态为 `status: pending`

## development → testing

- [ ] 每个 feature_id 状态为 `done`
- [ ] 每个 feature_id 有对应的代码审查报告（`artifacts/review-*.md` 提到）
- [ ] 所有代码已 commit（无 uncommitted changes）
- [ ] `traceability-gate-checker` Skill PASS（追溯链完整性校验，见设计规范 §4.2）

## testing → completed

- [ ] `artifacts/test-report.md` 存在

## /requirement:submit 前置门禁（不改变 phase，只记录 PR）

submit 不是阶段切换，而是在 `development` 或 `testing` 阶段内部的一次"推送 + 开 PR"动作。失败则阻止提交，不污染 meta.yaml。

- [ ] 当前分支 = `meta.yaml.branch`
- [ ] 当前 phase ∈ {`development`, `testing`}（禁止更早阶段提 PR）
- [ ] 工作区干净（`git status --porcelain` 为空）
- [ ] 本地有领先 origin 的 commit（`git log origin/<branch>..HEAD` 非空，或分支尚未推送过）
- [ ] `artifacts/code-review-reports/` 存在且至少一份报告，且报告无 `severity: blocker`
- [ ] `gh auth status` 成功（未登录无法开 PR）
- [ ] base 分支在远端可用（`git ls-remote --exit-code origin <base>`）
  - base 取值顺序：`--target` 参数 > `meta.yaml.base_branch` > `develop`（仓库已启用）> `main`
- [ ] 若存在已打开的同分支 PR，改为 `gh pr edit` 更新正文，不重复开新 PR
