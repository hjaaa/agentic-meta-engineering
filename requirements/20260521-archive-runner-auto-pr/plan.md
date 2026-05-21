# 20260521-archive-runner-auto-pr · archive_runner 自动开归档 PR + 单需求单分支闭环

## 目标

让 archive_runner 自动接管「写元信息 → 切回 feat 分支 → commit → push → 开归档 PR → finalize 时清理分支」全链路，实现单需求 = 单 feat 分支闭环，消除当前"需要额外切 chore 分支才能完成归档收尾"的流程断点。

## 背景

本需求来自 20260519-context-usage-report 归档闭环的回顾。当前归档流程需要手工切 chore 分支写元信息、开 PR，存在明显的流程断点。本期目标是让 archive_runner 自动完成全链路。

## 核心需求（5 句已确认）

1. archive_runner 写完归档元信息后自动切回 feat 分支 + commit + push + 开 PR（base=develop，head=feat 复用）
2. 远程 feat 分支删除推迟到归档 PR merged 后由  清理
3. 归档 PR 跳过 codex（）+ 跳过 rebase（）
4. meta-schema 加新字段 ， 读它检测 merged 状态
5. 老 archive 已删远程 feat 的兼容：加  flag

## 锁定设计点（4 项）

| 设计点 | 决策 |
|---|---|
| 远程 feat 删时机 | archive PR merged 后才删（ 第二阶段） |
| archive PR codex | 跳过（纯 metadata 变更） |
| rebase 策略 | （squash-merged 经验明示） |
| finalize 状态源 | （meta-schema 同步加新字段） |

## 范围

- 包含：archive_runner 改造、meta-schema 新字段、--finalize 二阶段、--legacy-resurrect-remote、单元测试 + e2e、文档同步
- 不包含：其他 runner（submit、continue 等）的改造；CI 流水线变更

## Features 预估（7 项，正式拆分在阶段 5 detail-design）

| Feature | 描述 |
|---|---|
| F-001 | archive_runner 第一阶段重构（写元信息 → 切 feat → commit） |
| F-002 | archive PR 自动创建（gh pr create + body 模板） |
| F-003 | archive_runner --finalize 二阶段（读 archive_pr_number → 检 merged → 删本地+远程 feat + cleanup 本地 owned worktree，内部 chdir 主仓根） |
| F-004 | meta-schema 加  字段 |
| F-005 | 单元测试 + e2e fake-repo 流程 |
| F-006 | skill / command 文档同步（archive-rules.md + archive.md） |
| F-007 | 兼容老 archive 已删远程的兜底（） |

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | |
| tech-research | |
| outline-design | |
| detail-design | |
| task-planning | |
| development | |
| testing | |

## 风险

- **R-1**：archive_runner 自动开 PR 时 base=develop 需要 gh 权限 → 加单测覆盖 + 手动验证
- **R-2**：归档 PR 跳 codex 可能让人手工加代码不被审 → mitigation：PR body 顶部明示「仅 metadata，含代码改动请关 PR」+ 文档约定
- **R-3**：兼容老 archive 已删的远程 feat： 可能撞 protected branch 规则 → 加单测 + 文档

---

## 决策记录

### D-001 归档 PR 跳过 codex + rebase
- **Context**：归档 PR 仅含 metadata 变更（meta.yaml phase/completed_at/outcome），无业务代码改动，codex review 无实质价值；历史 squash-merge 经验表明 rebase 容易冲突
- **Decision**：archive_runner 开 PR 时固定传 
- **Consequences**：归档流程更顺滑；若归档 PR 混入代码改动则跳过 codex，需文档约定约束
- **时间**：2026-05-21 11:37:32

### D-002 远程 feat 分支删除时机推迟到 archive PR merged
- **Context**：若归档前就删远程，finalize 无法推断 PR 是否 merged；且留着 feat 分支给 PR 做 head 是必须的
- **Decision**： 第二阶段：检测 archive_pr_number 对应 PR 状态为 merged 后才删本地+远程 feat
- **Consequences**：feat 分支生命周期延长到归档 PR merged；需 meta-schema 新增 archive_pr_number 字段
- **时间**：2026-05-21 11:37:32

### D-003 worktree cleanup 时机推迟到 --finalize（合并进 F-003）
- **Context**：现有 `_cleanup_worktree_before_archive`（archive_runner.py:683）在 pre-archive 即清理 worktree，与本期"在 feat 分支自动 commit/push + 开归档 PR + 等待 reviewer 迭代"的新流程冲突——若提前删 worktree，归档 PR 期间 reviewer 想在 worktree 内改文档/补 commit 会失败
- **Decision**：worktree cleanup 从 pre-archive 移到 `--finalize` 子命令内部，与本地+远程 feat 分支删除同步；保留三重保护中的 owner=workflow + `.worktrees/` 前缀两条；第 3 条「cwd ≡ 主仓根」改为「finalize 内部先 `os.chdir(主仓根)`（复用 worktree_manager.resolve_main_repo_root，archive_runner.py:695-696 已具备此能力）再 cleanup」
- **Consequences**：worktree 生命周期延长到归档 PR merged + finalize；用户在 worktree 内跑 finalize 不再被第 3 条保护卡死；老需求 / worktree 已被外部清理的场景静默 skip（与 archive_runner.py:204-206 处理一致）；测试用例需覆盖 finalize 三种 cwd 路径（worktree 内 / 主仓根 / worktree 已不存在）
- **时间**：2026-05-21 14:19:45
