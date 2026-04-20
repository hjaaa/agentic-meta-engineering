# 阶段门禁检查清单

每次 `/requirement:next` 切阶段时，必须全部通过。失败则阻止切换并列出缺口。

## bootstrap → definition

- [ ] `meta.yaml` 存在且合法
- [ ] 当前分支 = `meta.yaml.branch`
- [ ] `plan.md` 存在

## definition → tech-research

- [ ] `artifacts/requirement.md` 存在
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
