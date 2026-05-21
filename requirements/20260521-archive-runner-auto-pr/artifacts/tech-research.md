---
id: 20260521-archive-runner-auto-pr
phase: tech-research
created_at: 2026-05-21 11:37:32
title: archive_runner 自动开归档 PR + 单需求单分支闭环 · 技术预研
---

# 20260521-archive-runner-auto-pr · 技术预研

## 可行性结论

**feasibility: feasible**

8 条已锁定决策（plan.md D-001 ~ D-008）在现有代码库内全部有明确改造锚点，无新第三方库，无 DB 改动，无新技术依赖。核心依赖（`gh pr view` subprocess 模式 / `_ask` + `ArchivePrompt` 问询框架 / `worktree_manager.resolve_main_repo_root` / `_atomic_write_meta`）均已落地。

**关键可行性证据**：

- D-008（archive_pr_number 三路径 fail-closed）可直接复用 `_precheck_pr_merged` 的 try/except + `json.loads` + `_abort` exit 1 模式（来源：scripts/lib/archive_runner.py:225）。
- D-005 合并问询可复用 `_ask` + `ArchivePrompt` 三态问询框架（来源：scripts/lib/archive_runner.py:370）。
- D-003 worktree cleanup 搬到 finalize 是现有 `_cleanup_worktree_before_archive` 的位置迁移（来源：scripts/lib/archive_runner.py:683），三步硬约束（`resolve_main_repo_root` → `os.chdir` → `cleanup_worktree_if_owned`）保留不变。
- D-007 fail-closed / fail-soft 分层与现有 `_delete_local_branch`（来源：scripts/lib/archive_runner.py:430）/ `_delete_remote_branch`（来源：scripts/lib/archive_runner.py:546）失败累积模式（`result.error_messages`）兼容。
- D-002 archive_pr_number 字段引入 meta-schema 可对照 `archived_at` optional_fields 现有规范（来源：context/team/engineering-spec/meta-schema.yaml:134）+ 状态机校验模式 `_check_archived_at_state_machine`（来源：scripts/lib/check_meta.py:150）。

**唯一新模式**：scripts/lib/ 内**零** `gh pr create` 调用先例（grep 全仓 scripts/ 与 .claude/skills/ 后确认）—— submit 流程的 PR 创建在 Skill 层（来源：.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md:89），让 main agent 直接调 gh CLI。D-001 / D-004 把 PR 创建从 Skill 层搬到 Python runner 是项目内首例。但 `gh pr view` subprocess 模式已成熟（archive_runner.py:225），对称实现风险可控。

---

## 设计要点评估（D-001 ~ D-008）

### D-001 归档 PR 跳过 codex + rebase

**代码锚点**：archive 主流程在 `_run_experience` 之后、`_delete_remote_branch` 之前插入新步骤（来源：scripts/lib/archive_runner.py:807）。

**实现要点**：
- 不调 `submit_codex.py`（codex review-loop 独立 runner，来源：scripts/lib/submit_codex.py:1）
- 直接 `subprocess.run(["gh", "pr", "create", "--base", base_branch, "--head", branch, "--title", ..., "--body-file", ...])`
- PR body 顶部明示「仅 metadata 改动，含代码改动请关 PR」（detail-design 落 body 模板）
- 不做 `git rebase` 步骤（archive_runner.py 全量内零 rebase 调用，本就无需 skip）

详见 R-T01。

---

### D-002 远程 feat 删时机推迟 + meta-schema 新增 archive_pr_number

**代码锚点（archive_runner.py 主流程改造）**：
- 现状 `archive_requirement`（来源：scripts/lib/archive_runner.py:733）中 `_delete_remote_branch`（来源：scripts/lib/archive_runner.py:814）/ `_delete_local_branch`（来源：scripts/lib/archive_runner.py:822）是主流程末尾两步
- 改造：把这两步**搬出**主流程进 finalize 子命令；archive 主流程在 `_run_experience` 后追加 commit + push + gh pr create + 写 archive_pr_number

**代码锚点（meta-schema 改造）**：
- `optional_fields` 段（来源：context/team/engineering-spec/meta-schema.yaml:132）新增 `- archive_pr_number   # 归档 PR number；archive 第一阶段创建后写入；finalize 阶段读取校验 MERGED`
- `fields:` 段新增 archive_pr_number: type=int, required=false（参照 cleanup.removed_at 模式，来源：context/team/engineering-spec/meta-schema.yaml:191）
- check_meta.py 新增 `_check_archive_pr_number_state_machine`（对照 `_check_archived_at_state_machine`，来源：scripts/lib/check_meta.py:150）：phase != completed 时 archive_pr_number 必须为 0/缺失；phase == completed 时允许有值

**backward-compat**：老 meta（15 个已 completed REQ）无 archive_pr_number 字段时，check_meta 在 phase == completed 路径不要求该字段非零（视同 0/缺失为合法）；finalize 子命令读 archive_pr_number 缺失时 fail-closed，但允许 `--force` 跳过。

详见 R-T02 / R-I02。

---

### D-003 worktree cleanup 推迟到 --finalize

**代码锚点**：
- 现状：`_cleanup_worktree_before_archive`（来源：scripts/lib/archive_runner.py:683）在 archive 主流程内调用（来源：scripts/lib/archive_runner.py:791）
- 改造：删 archive 主流程的 :791 调用；finalize 子命令内复用此函数（参数 + 行为不变）
- 三步硬约束 `resolve_main_repo_root` → `os.chdir` → `cleanup_worktree_if_owned` 保留不变（来源：scripts/lib/archive_runner.py:694）

**worktree cleanup 时机**：finalize 内部「删本地+远程分支之前」（顺序：chdir 主仓 → pull --ff develop → cleanup_worktree → git branch -D → git push --delete）。

详见 R-T03。

---

### D-004 归档 PR 创建失败 fail-closed exit 1

**代码锚点**：archive 主流程新增的 gh pr create 调用包 try/except + 检查 returncode；失败时调 `_abort("R-ARCHIVE-PR-CREATE-FAILED", ...)`（参照 `_precheck_pr_merged` 现有失败处置，来源：scripts/lib/archive_runner.py:236 / :243）。

**与 idempotent 重跑机制的关系**：本阶段确认采用方案 A 全自动 idempotent（见「P0 待澄清关闭」段）。D-004 fail-closed 后用户直接重跑 archive，runner 内部跳过已完成步骤；无需手工 `git reset --soft`。

详见 R-T04 / R-I01。

---

### D-005 finalize 默认询问 + --yes-finalize 跳问

**代码锚点**：
- 复用 `_ask` + `ArchivePrompt`（来源：scripts/lib/archive_runner.py:370）
- finalize 新增 ArchivePrompt(kind="finalize", question="确认删除本地+远程 feat/<id> + 本地 worktree？", default=False)
- `--yes-finalize` flag 跳问（对照 `--yes-experience` / `--yes-local-branch` 现有 flag 风格，来源：scripts/lib/archive_runner.py:854 ~ :856）

**detail-design 阶段补充实现细节（P0 待澄清 #3 关闭决议）**：D-005 合并问询保留；新增 `--keep-local-branch` / `--keep-remote-branch` / `--keep-worktree` 三个 flag 兜底高级用户场景（如 hotfix 需保留 feat 分支）。建议 detail-design 阶段把这 3 个 flag 收进 plan.md 决策记录（新增 D-009 或扩 D-005）。

---

### D-006 --force 仅跳 merged 检查

**代码锚点**：finalize 子命令读 `--force` 时跳 D-008 的 `gh pr view archive_pr_number` MERGED 校验；**不**影响 D-001 PR 自动创建路径（archive 主流程内的 commit + push + gh pr create 仍走默认路径）。

**`--force` 与 `--legacy-resurrect-remote`（F-007）的关系**：
- `--force`：跳 MERGED 校验（异常恢复，如归档 PR 被手工 closed）
- `--legacy-resurrect-remote`：兼容老 archive 已删远程的兜底（finalize 时远程不存在 → 按 already-deleted 处理而非 fail-soft）
- 两个 flag 独立，可同时传

详见 R-S01。

---

### D-007 finalize 子步骤混合失败策略

**代码锚点（fail-closed 步骤）**：
- `os.chdir(main_repo_root)`：复用 `_cleanup_worktree_before_archive` 现有 OSError 兜底模式（来源：scripts/lib/archive_runner.py:706）
- `git pull --ff develop`：新增；失败 fail-closed（防 finalize 时 develop 落后导致 feat 分支误删）
- `git branch -D feat/<id>` 非 not-found 失败：现有 `_delete_local_branch` 是 fail-soft（来源：scripts/lib/archive_runner.py:516），finalize 路径改为 fail-closed

**代码锚点（fail-soft 步骤）**：
- `git push --delete origin feat/<id>` 网络/权限失败：fail-soft，追加 `result.manual_recovery_commands`（见 P0 待澄清 #2 关闭决议）
- `git worktree remove --force` 失败：fail-soft + 不写 `meta.worktree.cleanup.removed_at`

**新模式（P0 待澄清 #2 关闭决议）**：
- 新增 `ArchiveResult.manual_recovery_commands: list[str]` 字段
- fail-soft 步骤把恢复命令 append 进此 list
- `_render_summary`（来源：scripts/lib/archive_runner.py:614）末尾追加 `manual recovery:` 段
- 顺手清掉 `_delete_local_branch` 保护分支拦截路径现有的双打印（来源：scripts/lib/archive_runner.py:456）

详见 R-T05。

---

### D-008 archive_pr_number 三路径 fail-closed

**代码锚点**：finalize 入口新增 `_precheck_archive_pr_merged(req_id)`：
- 字段缺失：`meta.archive_pr_number` is None or 0 → `_abort("R-FINALIZE-ARCHIVE-PR-MISSING", ...)`
- `gh pr view <archive_pr_number> --json state` 调用失败：`_abort("R-FINALIZE-ARCHIVE-PR-FETCH-FAILED", ...)`
- state != "MERGED"：`_abort("R-FINALIZE-ARCHIVE-PR-NOT-MERGED", ...)`

完全对照 `_precheck_pr_merged` 现有模式（来源：scripts/lib/archive_runner.py:225），仅换字段名 + error code。

**`--force` 跳过此校验**：见 D-006。

---

## 风险识别（按严重度排序）

### 技术风险

**R-T01：scripts/lib 内零 gh pr create 调用先例，初次实现需验证 edge case**

- severity: medium
- description: grep 全仓 scripts/ 与 .claude/skills/ 后确认零 Python 直接调 `gh pr create` 先例。submit 流程的 PR 创建在 Skill 层（来源：.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md:89），让 main agent 直接调 gh CLI。D-001 把这个调用搬进 Python runner 需重新验证 edge case：gh 未登录 / 远程分支保护规则拒推 / title/body 含特殊字符
- likelihood: medium
- mitigation: 参照 `_precheck_pr_merged`（archive_runner.py:225）已有的 subprocess + json.loads + fail-closed 模式；title/body 用 `subprocess.run(args=list)` 而非 shell=True 规避注入；unit test 覆盖 4 类失败（OSError / returncode!=0 / stdout 非合法 JSON / PR 已存在等价路径）

**R-T02：archive 主流程在 feat 分支自动 commit 后，重跑撞 _precheck_dirty**

- severity: high
- description: 现有 `_precheck_dirty`（来源：scripts/lib/archive_runner.py:180）在 archive 主流程开头检查 `git status --porcelain` 全量 dirty；新流程 step 3 _atomic_write_meta 改 meta.yaml + step 4 追 process.txt + step 6 commit 都会让 worktree 短暂 dirty。重跑场景：第一次跑到 step 7 push 失败时已 step 6 commit；第二次跑 step 2 _precheck_dirty 看到 worktree clean（commit 已收 dirty）但 step 6 的归档 commit 已存在，需要 idempotent 跳过 step 6 重复 commit
- likelihood: high（确定会发生，是 idempotent 设计核心场景）
- mitigation: 方案 A 全自动 idempotent（P0 待澄清 #1 关闭决议）：step 2 _precheck_dirty 加白名单（meta.yaml / process.txt / artifacts/ 内文件 dirty 不计 dirty，前缀必须 `requirements/<id>/`，前缀外仍 fail-closed）；step 6 commit 前用 `git log -1 --format=%s` 在 feat 分支检查是否含 `archive(<req_id>): metadata` 前缀，已存在 → skip

**R-T03：worktree cleanup 推迟到 finalize 后，finalize 在 worktree 内跑时第 3 条保护触发**

- severity: medium
- description: D-003 已识别此风险——「现有 _cleanup_worktree_before_archive 在 pre-archive 即清理 worktree，与新流程‘在 feat 分支自动 commit/push + 开归档 PR + 等待 reviewer 迭代’冲突」（来源：requirements/20260521-archive-runner-auto-pr/plan.md:79）。改造后 finalize 子命令内部先 `os.chdir(主仓根)`（复用 worktree_manager.resolve_main_repo_root，来源：scripts/lib/archive_runner.py:695），再 cleanup worktree
- likelihood: medium
- mitigation: 测试覆盖 finalize 三种 cwd 路径：worktree 内 / 主仓根 / worktree 已不存在（与 archive_runner.py:204 已有 worktree-deleted 跳过逻辑对齐）

**R-T04：gh pr create 失败但 PR 实际已建（gh CLI 网络重试 / 异步）**

- severity: medium
- description: 极小概率场景：网络抖动让 gh pr create 返 non-zero 但实际 PR 已在 GitHub 侧创建；重跑会撞「PR 已存在」错误
- likelihood: low
- mitigation: 方案 A 的 step 8 idempotent 检查（P0 待澄清 #1）：先 `gh pr list --head feat/<id> --base develop --json number,state`，OPEN 取 number 写回 meta + 跳过 create；CLOSED / MERGED 异常路径 fail-closed exit 1

**R-T05：finalize stderr 实时打印 vs _render_summary 汇总打印分工**

- severity: medium
- description: D-007 自述「fail-soft 后 stderr 打印手工命令是 archive_runner 现有代码风格里没有的新模式」（来源：requirements/20260521-archive-runner-auto-pr/plan.md:103）；实际现有 `_delete_local_branch` 保护分支拦截路径（来源：scripts/lib/archive_runner.py:456）已有 `print(stderr) + result.error_messages.append` 双打印 bug
- likelihood: high（确定发生，是 P0 待澄清 #2 决议关闭点）
- mitigation: P0 待澄清 #2 关闭方案：新增 ArchiveResult.manual_recovery_commands 字段，fail-soft 步骤只 append 此 list；_render_summary 末尾追 manual recovery 段；顺手清掉保护分支拦截的双打印

### 集成风险

**R-I01：archive 主流程在 _atomic_write_meta 之后 commit 之前，meta 已落盘但 commit 失败 → meta 已是 completed 但 PR 没建**

- severity: high
- description: archive 主流程顺序 atomic_write_meta（step 3）→ append_process_event（step 4）→ run_experience（step 5）→ commit（step 6）；step 6 失败时 meta.phase 已是 completed 但 archive_pr_number 仍为 0。第二次跑撞 `_precheck_phase` 默认仅允许 phase ∈ {testing}（来源：scripts/lib/archive_runner.py:149）
- likelihood: high（半完成状态下确定撞校验）
- mitigation: 方案 A 的 step 2 _precheck_phase 改造（P0 待澄清 #1）：允许 phase ∈ {testing} OR (phase == completed AND archive_pr_number == 0)；后者代表"半完成归档"状态，runner 内部 step 3-5 各步 idempotent 跳过已完成项（_atomic_write_meta 保留原 archived_at；_append_process_event 检查 process.txt 末 10 行是否已含 [archived] tag；_run_experience 复用现有 lessons_extracted=True 跳过）

**R-I02：D-002 archive_pr_number 字段引入对历史 completed REQ 的 backward-compat**

- severity: medium
- description: 老 meta.yaml（REQ-2026-001 ~ REQ-2026-014 + 20260519-* 共 15 个 completed 需求）无 archive_pr_number 字段。check_meta.py 若强制 phase=completed 时该字段必须非零，会让所有历史 REQ 校验失败
- likelihood: high（确定会发生）
- mitigation: backward-compat 设计——`_check_archive_pr_number_state_machine` 仅校验「phase != completed 时该字段必须为 0/缺失」（防误填），**不**要求 phase == completed 时必须非零（兼容历史）；finalize 子命令读 archive_pr_number 缺失时 fail-closed，但允许 `--force` 跳过

### 性能风险

**R-P01：gh pr create / gh pr list 网络调用延迟**

- severity: low
- description: 归档主流程新增 2 个 gh CLI 调用（create / list idempotent 检查），单次约 0.5-2s（与 `_precheck_pr_merged` 现有 `gh pr view` 同量级，来源：scripts/lib/archive_runner.py:231）；archive 总时长从 ~2s 升至 ~5s
- likelihood: low
- mitigation: 无需特别优化；archive 是手工触发的低频操作（每需求 1-2 次），延迟可接受

### 安全风险

**R-S01：finalize --force 跳 MERGED 校验后误删活跃 feat 分支**

- severity: high
- description: `--force` 设计目的是异常恢复（归档 PR 被手工 closed / 老需求无 archive_pr_number）；若用户误传 `--force` 跳 MERGED 校验，会直接进 git branch -D + git push --delete 路径，可能丢失未 merged 的代码
- likelihood: low（用户需主动加 flag）
- mitigation: `--force` 路径下 D-005 合并问询仍触发（不跳问，除非同时传 `--yes-finalize`）；stderr 显式打印「警告：跳过归档 PR MERGED 校验，本地+远程 feat 分支将被删除」让用户三思

---

## 工作量估算

| Feature | 描述 | design (天) | dev (天) | test (天) | 合计 (天) |
|---|---|---:|---:|---:|---:|
| F-001 archive_runner 第一阶段重构（写元信息 → 切 feat → commit） | step 6 commit idempotent + dirty 白名单 + _precheck_phase 改造 | 0.3 | 1.0 | 0.5 | **1.8** |
| F-002 archive PR 自动创建 | gh pr create + body 模板 + step 7-8 idempotent（gh pr list 检查） | 0.3 | 1.0 | 0.7 | **2.0** |
| F-003 archive_runner --finalize 二阶段 | 新子命令；D-005 合并问询 + 3 --keep-* flag；D-007 fail-closed/soft 分层；D-008 三路径 fail-closed；worktree cleanup 搬迁；manual_recovery_commands 字段 | 0.5 | 2.0 | 1.2 | **3.7** |
| F-004 meta-schema 加 archive_pr_number + check_meta 状态机 | optional_fields + fields: 段 + _check_archive_pr_number_state_machine + backward-compat | 0.2 | 0.5 | 0.5 | **1.2** |
| F-005 单元测试 + e2e fake-repo 流程 | step 6/7/8 idempotent 单测；finalize 三 cwd 路径；--force / --keep-* / --legacy-resurrect-remote 组合 | 0.3 | 0.3 | 1.5 | **2.1** |
| F-006 skill / command 文档同步 | archive-rules.md + archive.md 三重保护语义更新 | 0.2 | 0.3 | 0 | **0.5** |
| F-007 --legacy-resurrect-remote 兜底 | finalize 内远程已删时按 already-deleted 处理 | 0.2 | 0.3 | 0.3 | **0.8** |

**合计：12.1 天**（区间 10-14 天）

**关键路径**：

```
F-004（meta-schema + check_meta）→ F-001（archive 主流程改造）→ F-002（PR 创建）→ F-003（finalize）→ F-005（e2e）
                                                                        ↓
                                                                  F-007（可与 F-003 并行）
                                                                  F-006（任何时候并行）
```

关键路径深度：F-004 → F-001 → F-002 → F-003 → F-005（约 10.8 天串行）。F-006 / F-007 可并行。

**PR 拆分建议**：

- **PR-A**：F-004 + F-006（meta-schema 字段 + check_meta 状态机 + 文档），无依赖，可单独上绿
- **PR-B**：F-001 + F-002 + F-007（archive 主流程改造 + PR 自动创建 + 老需求兜底），依赖 PR-A 字段定义
- **PR-C**：F-003 + F-005（finalize 子命令 + e2e），依赖 PR-B 主流程稳定

---

## 影响模块

**已在 meta.yaml.affected_modules 列出**：

- `scripts/lib/archive_runner.py`（F-001 / F-002 / F-003 主战场）
- `context/team/engineering-spec/meta-schema.yaml`（F-004 字段定义）
- `.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md`（F-006 文档）
- `.claude/commands/requirement/archive.md`（F-006 文档）
- `tests/lifecycle/test_archive_runner.py`（F-005 测试）

**本轮新增（detail-design 阶段补录至 meta.yaml.affected_modules）**：

- `scripts/lib/check_meta.py`（F-004 _check_archive_pr_number_state_machine）
- `.claude/skills/managing-requirement-lifecycle/templates/archive-pr-body.md.tmpl`（F-002 新增 PR body 模板）
- `tests/lifecycle/test_finalize.py`（或并入 test_archive_runner.py，F-005 finalize 子命令测试）

---

## P0 待澄清关闭情况

本阶段共识别 3 个 P0 待澄清，全部关闭：

| 待澄清 | 关闭方案 | 关闭决议来源 |
|---|---|---|
| **#1 idempotent 重跑机制** | 方案 A 全自动 idempotent（每步 idempotent 检查 + _precheck_dirty 白名单 + _precheck_phase 允许 phase=completed AND archive_pr_number=0 重跑） | 用户对话确认；详见 R-T02 / R-I01 |
| **#2 D-007 stderr 实时打印 vs _render_summary 双打印** | 方案 1 全走 _render_summary 汇总；新增 ArchiveResult.manual_recovery_commands 字段；顺手清保护分支拦截双打印 | 用户对话确认；详见 R-T05 |
| **#3 D-005 finalize 合并问询粒度** | 方案 3 合并问 + `--keep-local-branch` / `--keep-remote-branch` / `--keep-worktree` 三 flag 兜底 | 用户对话确认；建议 detail-design 阶段把 3 flag 收进 plan.md 决策（新增 D-009 或扩 D-005） |

---

## detail-design 阶段处理项

不阻塞本阶段切换，detail-design 阶段需要决定：

1. **PR body 模板内容**（F-002）：archive-pr-body.md.tmpl 顶部明示「仅 metadata 改动，含代码改动请关 PR」+ archive 元信息 diff 摘要 + 关联需求 PR number。
2. **--force 与 --yes-finalize 组合的 stderr 警告文案**（D-006 + R-S01）：明确不同组合下的提示语，避免用户误传。
3. **commit message 前缀稳定化**（R-T02 + R-T05）：`archive(<req_id>): metadata` 是否含 archive_pr_number 后缀？多需求并发场景识别符是否足够稳定？
4. **gh pr list idempotent 检查的 PR 状态处置**（R-T04）：OPEN 取 number 写回；CLOSED / MERGED 是否一律 fail-closed？还是 MERGED 视同 finalize 已完成走下游？
5. **manual_recovery_commands 字段在 ArchiveResult dataclass 中的位置 + dump 格式**（R-T05）：是否要写进 meta.yaml 留痕？
6. **--keep-local-branch / --keep-remote-branch / --keep-worktree 三 flag 的 process.txt 事件**（D-005 落实）：finalize 跑成功时 process.txt 是否打印每个 keep 标记？
