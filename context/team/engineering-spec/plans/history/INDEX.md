# 历史 Plan 归档

已完成并合入 main 的 Phase 计划文档。保留用于追溯"骨架为什么长成这样"。

新项目使用本骨架时，本目录可整体删除或忽略——内容对日常开发无关。

## 骨架建设期（Phase 1–4）

| Phase | 范围 | Plan 文档 | 分支 | 状态 |
|---|---|---|---|---|
| 1 | 基础设施 + 上下文文档（root configs / hooks / statusline / 完整 context/ 树） | [phase-1-foundation](./2026-04-20-phase-1-foundation.md) | `setup/phase-1-foundation` | ✅ 已完成（20 Tasks） |
| 2a | 10 Skill（伞形 + 专项） | [phase-2a-skills](./2026-04-20-phase-2a-skills.md) | `setup/phase-2a-skills` | ✅ 已完成（11 Tasks） |
| 2b | 16 Command + 集成验证 | [phase-2b-commands](./2026-04-20-phase-2b-commands.md) | `setup/phase-2b-commands` | ✅ 已完成（6 Tasks） |
| 3 | 20 Agent | [phase-3-agents](./2026-04-20-phase-3-agents.md) | `setup/phase-3-agents` | ✅ 已完成（6 Tasks） |
| 4 | 集成验收 + 示例需求跑通 | [phase-4-integration](./2026-04-20-phase-4-integration.md) | `setup/phase-4-integration` | ✅ 已完成（REQ-2026-001 端到端通过） |

## 门禁体系演进 · Reviewer Verdict 结构化（roadmap G3）

| PR | 范围 | Plan 文档 | 分支 | 状态 |
|---|---|---|---|---|
| PR1 | 基础设施（review-schema.yaml / save-review.sh / check-reviews.sh / meta-schema reviews 字段 / CI non-strict 接入） | [reviewer-verdict-pr1-infra](./2026-04-27-reviewer-verdict-pr1-infra.md) | `feat/reviewer-verdict-pr1-infra` | ✅ 已合入（PR #36） |
| PR2 | 试点：requirement-quality-reviewer 切到 save-review.sh + gate-checklist `definition→tech-research` 切到 check-reviews.sh + next 执行体改造 + REQ-2099-001 sandbox 试点 5/5 通过 | [reviewer-verdict-pr2-pilot](./2026-04-27-reviewer-verdict-pr2-pilot.md) | `feat/reviewer-verdict-pr2-pilot` | ✅ 已合入（PR #38） |
| PR3 | 全量切换：剩余 3 reviewer（outline / detail / code-quality 双输出）+ gate-checklist 余 4 段切到 check-reviews.sh + D7 写保护双层（protect-branch reviews/*.json 拦截 + pre-commit reviews 段 diff 双向校验）+ REQ-2099-200 sandbox 端到端 6/6 通过 | [reviewer-verdict-pr3-rollout](./2026-04-27-reviewer-verdict-pr3-rollout.md) | `feat/reviewer-verdict-pr3-rollout` | ✅ 已合入（PR #40） |
