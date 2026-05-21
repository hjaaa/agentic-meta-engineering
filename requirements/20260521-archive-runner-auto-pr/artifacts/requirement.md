---
id: 20260521-archive-runner-auto-pr
title: archive_runner 自动开归档 PR + 单需求单分支闭环
created_at: 2026-05-21 11:37:32
refs-requirement: true
---

# 20260521-archive-runner-auto-pr · archive_runner 自动开归档 PR + 单需求单分支闭环

## 背景

需求归档（phase: testing → completed）当前流程存在结构性断点：

`archive_runner` 第一阶段执行后留下三个副作用：删远程 feat 分支 / 把 `phase=completed` 等元信息变更**留在 working tree 不 commit** / 退出（来源：scripts/lib/archive_runner.py）。主仓 `develop` 被 protect-branch hook 拦 Edit/Write（来源：context/team/git-workflow.md）+ auto-mode classifier 拦 direct commit（来源：CLAUDE.md），所有 `feat/* / chore/* / feature/*` 必须经 PR 合入 develop。结果：用户被迫切到新 chore 分支 + 手工 commit + 手工 push + 手工 `gh pr create`，5 步 git 操作只为完成 metadata-only 收尾。

PR #83（20260519-remove-human-signoff）与 PR #85（20260519-context-usage-report）两次实践证实这是**系统性断点**而非孤例（来源：requirements/20260519-remove-human-signoff/meta.yaml）（来源：requirements/20260519-context-usage-report/meta.yaml）。流程文档（来源：.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md）描述的「3 问串行 + 删本地+远程分支」与工具实现一致，但**没有把"开归档 PR"这一步封装进工具**——这是当前的关键缺口。

本期改造目标：让 `archive_runner` 自动接管归档闭环全链（写元信息 → 在原 feat 分支 commit → push → 自动 `gh pr create` 归档 PR → `--finalize` 二阶段清理）。

## 目标

- **主目标**：单个需求所有 git 操作都在原 `feat/req-<id>` 分支闭环——归档元信息 commit 与 feature 开发 commits 同分支累积，无需切换到 `chore/*` 分支
- **次要目标 1**：archive_runner 把"机械化收尾"5 个手工 git/gh 命令封装进工具，用户感知层只需触发 archive + 回答三问 + 触发 `--finalize`
- **次要目标 2**：兼容老需求（远程 feat 已被旧 archive 删过的场景），提供 `--legacy-resurrect-remote` 兜底
- **次要目标 3**：归档 PR 跳 codex review-loop（纯 metadata 变更不需要 review-bot 注意力），节省 ~10min 等待

## 用户场景

### 场景 1：正常归档（happy path）

- **角色**：需求 owner（功能开发完成 + PR 已 merged + 测试验收无回归后归档）
- **前置**：
  - 主 PR 状态 `MERGED`（来源：.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md）
  - meta.yaml.lessons_extracted=true（经验已沉淀）
  - worktree 工作区 clean
- **主流程**：
  1. 用户触发 `archive_runner <req-id>` 或 `/requirement:archive`
  2. 工具跑 5 项预检 + 三问串行（经验沉淀 / 本地分支 / 远程分支）
  3. 工具写归档元信息（phase=completed / archived_at / outcome / worktree.cleanup.removed_at）
  4. **新增**：工具自动 `git switch feat/req-<id>` + commit 归档元信息 + `git push origin feat/req-<id>`
  5. **新增**：工具自动 `gh pr create --base develop --head feat/req-<id> --no-codex --skip-rebase`，body 顶部含 ⚠️ "仅 metadata，含代码改动请关 PR"
  6. **新增**：工具写 `meta.yaml.archive_pr_number` 字段记录新 PR 号
  7. 工具输出归档 PR URL + 下一步提示「review + merge 后跑 `--finalize`」
- **期望结果**：用户在主对话里看到归档 PR 链接，无需切分支 / 手工 commit / 手工开 PR

### 场景 2：归档 PR merged 后清理

- **角色**：同上
- **前置**：场景 1 完成 + 归档 PR 已 merged
- **主流程**：
  1. 用户触发 `archive_runner --finalize <req-id>` 或 `/requirement:archive --finalize`
  2. 工具读 `meta.yaml.archive_pr_number` → `gh pr view` 验证 state==MERGED
  3. 工具问一问「确认删除本地+远程 `feat/req-<id>` + 本地 worktree（若有）？Y/N」（默认 N；`--yes-finalize` 跳问）
  4. 用户确认后工具执行：
     1. 若 cwd 在 owned worktree 内，先 `os.chdir(主仓根)`（复用 `worktree_manager.resolve_main_repo_root`）
     2. 切 develop → `git pull --ff` → `git branch -D feat/...` → `git push origin --delete feat/...`
     3. **新增**：清理 owned worktree——`worktree.owner == workflow` 且 `worktree.path` 命中 `.worktrees/` 白名单时执行 `git worktree remove --force <path>` 并写 `meta.yaml.worktree.cleanup.removed_at`；path 不存在或 worktree 已被外部清理时静默 skip（与现有 `_check_git_status_clean` 对不存在 worktree 的处理一致——来源：scripts/lib/archive_runner.py:204-206）
- **期望结果**：本地 + 远程 feat 分支 + 本地 owned worktree 全清，需求生命周期闭环

### 场景 3：老需求兼容（legacy resurrect）

- **角色**：归档历史需求（如 20260519-context-usage-report 复盘重跑场景）的工程师
- **前置**：远程 `feat/req-<id>` 已被旧版 `archive_runner` 删除
- **主流程**：
  1. 用户触发 `archive_runner --legacy-resurrect-remote <req-id>`
  2. 工具探测远程分支不存在（`gh api repos/.../branches/<name>` 404）
  3. 工具从本地 feat 分支 `git push -u origin feat/req-<id>` 重建远程
  4. 后续走场景 1 流程
- **期望结果**：老需求重跑 archive 不再触发"必须切 chore 分支"的反模式

### 场景 4（异常）：归档 PR 创建失败

- **角色**：同场景 1
- **前置**：场景 1 步骤 1-4 成功，步骤 5（`gh pr create`）失败（gh 未登录 / 远程分支保护规则拒推 / 网络挂等）
- **期望结果**：archive_runner fail-closed exit 1，**保留 feat 分支上 commit 不回滚**，stderr 打印失败原因 + 提示用户手工命令 `gh pr create --base develop --head feat/req-<id> ...`

## 非功能需求

- **性能**：archive_runner 首次调耗时增加 < 5s（多了 push + gh pr create 两次网络 IO；`gh pr create` 历史耗时 ~2-3s）
- **兼容性**：保留所有现有 `--keep-branch / --no-experience / --yes-* / --outcome / --force` CLI flag 子集（不破坏 PR #83 / PR #85 调用约定）
- **安全/合规**：
  - 归档 PR body 顶部必含 ⚠️ "仅 metadata，含代码改动请关 PR"——防御场景：用户在 feat 分支上手动加代码 commit 然后误以为归档 PR 跳 codex 就能蒙混过关
  - `--legacy-resurrect-remote` 探测到远程已存在同名分支时**拒绝覆盖**（fail-closed），避免覆盖他人 in-flight 工作

## 范围

- **包含**：
  - `scripts/lib/archive_runner.py` 改造：写元信息后自动 commit/push/开 PR；新增 `--finalize` / `--yes-finalize` / `--legacy-resurrect-remote` flag
  - 归档 PR body 模板（含 ⚠️ 警告头 + 主 PR 引用 + meta 字段差异列表）
  - `context/team/engineering-spec/meta-schema.yaml` 加 `archive_pr_number: int (>=0, default 0)` 字段
  - `check_meta.py` 兼容历史 meta 缺该字段（不挂 schema 检）
  - **worktree cleanup 时机迁移**：从 `_cleanup_worktree_before_archive`（pre-archive，archive_runner.py:683）挪到 `--finalize` 子命令内部；保留三重保护中的 owner=workflow + `.worktrees/` 前缀两条；第 3 条「cwd ≡ 主仓根」改为「finalize 内部先 `os.chdir(主仓根)` 再 cleanup」（否则用户在 worktree 内跑 finalize 永远清不掉）
  - 单元测试 + e2e fake-repo 流程（覆盖 4 个场景 + 边界，含 worktree 不存在 / cwd 在 worktree 内 / cwd 已在主仓根三种 finalize 路径）
  - 文档同步：`archive-rules.md` + `.claude/commands/requirement/archive.md`（重点更新「worktree cleanup 三重保护」一节的时机描述）
- **不包含**：
  - PR merge 策略改造（squash 保持，不切 `--merge`）—— 详见 C-1 强约束
  - `--force` 范围扩展—— 详见本期决定 ARS-3
  - 自动开归档 PR 后的等待/轮询 merge 状态（首次调即返回；merged 检测留给 `--finalize`）—— 避免 archive_runner 演变成长尾轮询工具
  - 主 PR (feat) 的归档准备工作前移——本期不在 PR submit 阶段提前写 phase=completed

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| ARS-1：归档 PR 创建失败处理 | A. fail-closed exit 1 + 保留 working tree / B. 全回滚 / C. 静默不开 PR | **A** | 本期前置对话用户决定；最简单 + 失败可见 + 用户手恢复成本最低 |
| ARS-2：finalize 是否需要 yes flag | A. 默认问一问 / B. 直接删 | **A** | 与现有 archive 三问串行风格一致；防止误调直接清掉分支 |
| ARS-3：`--force` 范围 | A. 仅跳 merged 检查 / B. 也自动开 PR | **A** | 维持现状；--force 是异常恢复场景，复杂度不应加大 |
| ARS-4：远程 feat 删除时机 | A. archive PR merged 后才删（`--finalize`） / B. 第一次调就删 / C. 完全不删 | **A** | 本期前置对话用户决定；让归档 PR 有同分支可推 |
| ARS-5：归档 PR codex 策略 | A. 强制跳 `--no-codex` / B. 默认走 codex / C. 用户选 | **A** | 本期前置对话用户决定；纯 metadata 变更不值得耗费 codex 注意力配额 |
| ARS-6：归档 PR rebase 策略 | A. `--skip-rebase` / B. 默认 rebase | **A** | 沉淀经验 `squash-merged-branch-cannot-be-rebased.md` 明示——feat 被 squash-merged 后再 rebase 必撞冲突（来源：context/team/experience/squash-merged-branch-cannot-be-rebased.md） |
| ARS-7：finalize 状态源 | A. meta.yaml.archive_pr_number / B. 扫远程同分支最近 PR | **A** | 本期前置对话用户决定；schema 显式化优于依赖外部状态推断 |
| ARS-8：worktree cleanup 时机 | A. pre-archive（现状）/ B. `--finalize` 与本地 feat 删除同步 / C. 完全不动 | **B** | 本期 2026-05-21 对话补充确定；归档 PR 期间 reviewer 可能在 worktree 内迭代提交，提前删会自删脚下文件；finalize 内部 `os.chdir(主仓根)` 替代原第 3 条「cwd ≡ 主仓根」保护（来源：scripts/lib/archive_runner.py:695）`resolve_main_repo_root` 调用点已就绪 |

## 待澄清清单

> 与「## 待确认 / 待补充」语义等价；保留本节是为满足 `check_sourcing.py` W001 / W003 校验项（regex 只认 `待澄清清单`）。详见 notes.md Bug-4 经验（来源：context/team/experience/INDEX.md）。
>
> 下表 enumeration 与下文 `[` 待用户确认 `]` / `[` 待补充 `]` 标记一一对应（数量必须相等，否则触发 W003）。

- ~~条目 1：[待用户确认] develop direct commit 是否允许~~ **已确认（2026-05-21）**：`context/team/git-workflow.md:24` 明示 `develop` 行「Hook 拦截 Edit/Write = ✅」，且 `feat/req-* / feature/* / chore/* / hotfix/* / release/*` 全部经 PR 合入 develop（git-workflow.md:25-28 + :88 squash merge 约定）。结论：本期设计前提成立，archive_runner 必须经 PR。
- 条目 2：[待补充] archive PR body ⚠️ 警告头文案。**内容**：`⚠️ **本 PR 仅归档元信息变更**（meta.yaml + process.txt）。任何代码改动请关闭本 PR 并开 feat PR。本 PR 跳过 codex review-loop。`。**依据**：本期 ARS-5（跳 codex）+ 防御"用户在 feat 分支误加代码"的安全模型考量。**风险**：文案过短可能被 reviewer 略过；过长则模板复杂度上升。**验证时机**：阶段 5 detail-design 拍板最终文案，testing 阶段真机生成一份归档 PR body 截图对照。
- 条目 3：[待补充] archive_pr_number jsonschema 表达式。**内容**：`archive_pr_number: { type: integer, minimum: 0, default: 0 }`，与现有 `pr_number` 字段同模。**依据**：复用现有 schema 风格（来源：context/team/engineering-spec/meta-schema.yaml）。**风险**：历史 meta.yaml（PR #83 之前）缺该字段，check_meta.py 在 strict 模式可能挂——需 backward-compat 测试。**验证时机**：阶段 5 detail-design 跑 check_meta.py against 历史所有 meta.yaml，确认 0 fail。
