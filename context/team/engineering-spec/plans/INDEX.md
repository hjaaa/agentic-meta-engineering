# 实施计划目录索引

本目录存放**正在进行**的 Plan。完成后 `git mv` 到 `history/` 并更新 [`history/INDEX.md`](history/INDEX.md)。

## 入口

- [`README.md`](README.md) — 目录说明 + 执行原则

## 进行中的 Plan

| 日期 | 主题 | Plan 文档 | 对应分支 | 状态 |
|---|---|---|---|---|
| 2026-04-24 | 溢出区三文件重定义（process.txt / notes.md / plan.md 职责收敛 + 删两个 Hook） | [2026-04-24-spillover-redefine](2026-04-24-spillover-redefine.md) | `feature/spillover-redefine` | 🔄 执行中 |
| 2026-05-03 | 门禁系统 A+B 重构（热路径脱离 god-object + CLAUDE_GATES_GLOBAL_BYPASS + 异步 audit + run.py 最外层兜底） | [2026-05-03-gate-system-A+B-refactor](2026-05-03-gate-system-A+B-refactor.md) | `feat/gate-pr1-guard` 等 4 分支 | 🟡 待开工 |
| 2026-05-08 | 工作流引擎 Plan 1：Schema + Loader（变量替换 / 拓扑排序 / 三层模板发现） | [2026-05-08-workflow-engine-plan-1-schema-loader](2026-05-08-workflow-engine-plan-1-schema-loader.md) | `feat/req-2026-009` | ✅ 已合并到 develop |

## 历史

已完成并合入 main 的 plan 移入 [`history/INDEX.md`](history/INDEX.md)。
