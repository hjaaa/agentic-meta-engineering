---
id: 20260521-archive-runner-auto-pr
phase: outline-design
created_at: 2026-05-21 11:37:32
title: archive_runner 自动开归档 PR + 单需求单分支闭环 · 概要设计
---

# 概要设计 · 20260521-archive-runner-auto-pr

> 权威单源同 plan.md 与 tech-research.md（来源：requirements/20260521-archive-runner-auto-pr/plan.md:11）。本文档聚焦 archive_runner 双阶段拓扑下的模块边界 / 接口契约 / 数据结构 / PR 拆分，不重复 spec / tech-research 内容。

## 1. 架构方案：archive_runner 双阶段拓扑

archive_runner 从「一次性 5 步」改造为「双阶段闭环」：

```
   ┌─────────────────────────────────────────────────────────┐
   │   阶段 1: archive  ($ archive_runner <req_id>)          │
   │  ────────────────────────────────────────────────────   │
   │  _rebind_to_main_repo       (已有, scripts/lib/archive_runner.py:650)
   │  _load_meta                 (已有, scripts/lib/archive_runner.py:113)
   │  _precheck × 5              (已有, scripts/lib/archive_runner.py:149)
   │    └─ _precheck_dirty 加白名单 (F-001 改造)
   │    └─ _precheck_phase 允许半完成 (F-001 改造)
   │  _atomic_write_meta         (已有, scripts/lib/archive_runner.py:291; F-001 加 idempotent)
   │  _append_process_event      (已有, scripts/lib/archive_runner.py:325; F-001 加 idempotent)
   │  _run_experience            (已有, scripts/lib/archive_runner.py:387; idempotent 已具备)
   │  ★ _commit_archive_metadata  (F-001 新增, idempotent: 前缀检查)
   │  ★ _push_feat_branch         (F-001 新增, idempotent: HEAD == origin)
   │  ★ _create_archive_pr        (F-002 新增, idempotent: gh pr list 先查)
   │  ★ _write_archive_pr_number  (F-002 新增, idempotent: 字段相等跳)
   │  _render_summary             (已有, scripts/lib/archive_runner.py:614; F-003 加 manual_recovery 段)
   └─────────────────────────────────────────────────────────┘
                │ feat 分支保留 + 归档 PR 等 reviewer
                │ ──────────── PR merged 后 ─────────
                ▼
   ┌─────────────────────────────────────────────────────────┐
   │   阶段 2: finalize  ($ archive_runner <req_id> --finalize)
   │  ────────────────────────────────────────────────────   │
   │  ★ _precheck_archive_pr_merged  (F-003 新增, fail-closed)
   │  ★ 合并问询                       (F-003, 复用 _ask + ArchivePrompt)
   │  ★ os.chdir(主仓根)               (F-003, 复用 _rebind_to_main_repo 逻辑)
   │  ★ git pull --ff develop          (F-003, fail-closed)
   │  ★ _cleanup_worktree_before_archive (F-003 搬迁, scripts/lib/archive_runner.py:683)
   │  ★ _delete_local_branch           (F-003 搬迁, scripts/lib/archive_runner.py:430)
   │  ★ _delete_remote_branch          (F-003 搬迁, scripts/lib/archive_runner.py:546)
   │       └─ F-007 加 --legacy-resurrect-remote 分支
   │  _render_summary                  (复用 + manual_recovery_commands 段)
   └─────────────────────────────────────────────────────────┘

   ★ = 本期新增/搬迁
```

**核心改造原则**：
- 阶段 1 保留 feat 分支；只新增 commit + push + PR 创建步骤
- 阶段 2 承接全部"删除类不可逆操作"——本地分支 / 远程分支 / worktree 三件套，全部推迟到归档 PR merged 后
- 三件套**搬迁**而非重写：finalize 复用现有 `_delete_local_branch` / `_delete_remote_branch` / `_cleanup_worktree_before_archive`，仅调整调用点与失败策略

## 2. 模块切分

将 plan.md §Features 预估的 7 项映射为本期 features.json（来源：requirements/20260521-archive-runner-auto-pr/plan.md:34）：

| Feature | 制品类别 | 入口 | 主要动作 | 依赖 |
|---|---|---|---|---|
| F-001 | code | `archive_requirement()` 主流程 | step 1-9 重排；step 2 _precheck_dirty 白名单 + _precheck_phase 允许 (phase=completed AND archive_pr_number=0)；step 3-4 idempotent；step 6 commit + idempotent prefix 检查；step 7 push + idempotent HEAD 对比 | F-004 |
| F-002 | code + template | `_create_archive_pr()` 新函数 + `.claude/skills/managing-requirement-lifecycle/templates/archive-pr-body.md.tmpl` | gh pr create 调用 + body 模板 + gh pr list idempotent + 写 archive_pr_number + archive_pr_url | F-001 |
| F-003 | code | `finalize_requirement()` 新函数 + CLI `--finalize` subcommand | 6 步执行链；D-005 合并问询 + 5 flag；D-007 fail-closed/soft 分层；D-008 三路径 fail-closed；worktree cleanup 搬迁；manual_recovery_commands 字段填充 | F-002 |
| F-004 | schema + code | `context/team/engineering-spec/meta-schema.yaml` + `scripts/lib/check_meta.py` | optional_fields 加 archive_pr_number + fields 段新字段 + `_check_archive_pr_number_state_machine`（对照 _check_archived_at_state_machine，来源：scripts/lib/check_meta.py:150） | none |
| F-005 | test | `tests/lifecycle/test_archive_runner.py` + `tests/lifecycle/test_finalize.py`（新） | step 6/7/8 idempotent 单测；finalize 三 cwd 路径；--force / --keep-* / --legacy-resurrect-remote 组合 e2e；commit prefix 识别正则 | F-001 ~ F-004 |
| F-006 | doc | `.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md` + `.claude/commands/requirement/archive.md` | 双阶段流程语义；三重保护移到 finalize；--finalize / --keep-* flag 文档；commit prefix 约定 | F-003 |
| F-007 | code | `finalize_requirement()` 内 git push --delete 分支 | --legacy-resurrect-remote flag：远程 not-found 视为 already-deleted；现有 `_delete_remote_branch` 已折叠 "remote ref does not exist" → already-deleted（来源：scripts/lib/archive_runner.py:607），本期复用 + 加 flag 显式声明 | F-003 |

**依赖关系**：

```
F-004 (schema)
  └─→ F-001 (archive 主流程)
        └─→ F-002 (PR 创建)
              └─→ F-003 (finalize 子命令)
                    └─→ F-007 (老需求兜底, 与 F-003 同 PR)
                    └─→ F-005 (e2e, 与 F-003 同 PR)

  F-006 (文档) 与主链解耦, 可并行
```

## 3. 关键技术选型

### 选型 1：idempotent 重跑机制

- 候选 A：全自动 idempotent（每步加检查 + dirty 白名单 + _precheck_phase 改造）
- 候选 B：`--resume` flag（fail-closed 默认 + 显式 flag）
- 候选 C：手工恢复（仅改 stderr 文案 + 用户 git reset）
- 候选 D：重排顺序（先 PR 后落 meta）
- **决策**：候选 A
- 理由：用户负担为 0；step 6-9 idempotent 检查复杂度可控（commit prefix 正则 + HEAD 对比 + gh pr list）；候选 C 撞 protect-branch hook（meta.phase 已 completed 手工回滚被拦）；详 tech-research §P0 待澄清 #1 关闭决议（来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:267）

### 选型 2：fail-soft 步骤的恢复命令分发通道

- 候选 1：全走 _render_summary 汇总（新增 ArchiveResult.manual_recovery_commands 字段）
- 候选 2：实时 stderr 打印 + _render_summary 跳过重复
- 候选 3：保留现有双打印（不改 _delete_local_branch:456 既有行为）
- **决策**：候选 1
- 理由：单一通道无双打印；用户在 summary 末段一次性看到所有手工恢复命令；现有 `_delete_local_branch` 保护分支拦截路径双打印（来源：scripts/lib/archive_runner.py:456）顺手收敛进统一通道；详 tech-research §P0 待澄清 #2 关闭决议（来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:268）

### 选型 3：finalize 问询粒度

- 候选 1：合并问询（D-005 原决策）
- 候选 2：分三次问询（沿用现有 archive 三问风格）
- 候选 3：合并问 + `--keep-local-branch` / `--keep-remote-branch` / `--keep-worktree` 三 flag 兜底
- **决策**：候选 3
- 理由：默认 UX 简单（一次确认覆盖三件套）；高级用户可细粒度控制（hotfix 保 feat 分支 / debug 保 worktree 等场景）；与现有 `--yes-experience` / `--yes-local-branch` / `--yes-remote-branch` 现有 flag 风格一致（来源：scripts/lib/archive_runner.py:854）；详 tech-research §P0 待澄清 #3 关闭决议（来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:269）

### 选型 4：archive_pr_number 字段位置

- 候选 A：required_fields（强制）
- 候选 B：optional_fields + 状态机校验
- 候选 C：fields 段独立（不进 required/optional）
- **决策**：候选 B
- 理由：候选 A 让 15 个历史 completed REQ 直接 fail 校验；候选 B 对照 `archived_at` 现有规范模式（来源：context/team/engineering-spec/meta-schema.yaml:134）+ 状态机校验 `_check_archived_at_state_machine`（来源：scripts/lib/check_meta.py:150），新字段背景一致；候选 C 缺约束语义；详 R-I02 兼容设计（来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:200）

### 选型 5：archive commit message 前缀

- 候选 A：`archive(<req_id>): metadata`
- 候选 B：`chore(archive): <req_id> metadata`（符合现有 chore 风格）
- 候选 C：`archive(<req_id>): metadata #<archive_pr_number>`（含 PR number）
- **决策**：候选 A
- 理由：git log 看 archive 历史时 req_id 一目了然；idempotent 检查正则简单（`^archive\(<req_id>\):`）；候选 B 与现有 `chore(phase-transition): xxx`（git log 历史）风格相近但 idempotent 匹配要跨 chore/feat 后缀复杂；候选 C 在 commit 时 archive_pr_number 还未生成（commit 早于 gh pr create），顺序冲突

## 4. 关键流程

### 流程 1：archive 主流程（happy path）

```
$ python3 scripts/lib/archive_runner.py 20260521-archive-runner-auto-pr
  │
  ├─ _rebind_to_main_repo  (cwd 可能在 worktree 内, 锁定到主仓)
  ├─ _load_meta  (从主仓 requirements/<id>/meta.yaml 读)
  │
  ├─ _precheck_dirty  (whitelist requirements/<id>/, 前缀外仍 fail-closed)
  ├─ _precheck_phase  (允许 phase ∈ {testing} OR (completed AND archive_pr_number=0))
  ├─ _precheck_pr_number  (需求 PR, 字段=meta.pr_number)
  ├─ _precheck_pr_merged  (需求 PR state == MERGED, 来源：scripts/lib/archive_runner.py:225)
  ├─ _precheck_lessons_extracted  (经验沉淀)
  │
  ├─ _atomic_write_meta  (phase=completed; idempotent: 已 completed 时保留原 archived_at)
  ├─ _append_process_event  (idempotent: process.txt 末 10 行检查 [archived] tag)
  ├─ _run_experience  (idempotent: lessons_extracted=True 跳)
  │
  ├─ _commit_archive_metadata
  │      ├─ idempotent: git log -1 --format=%s 含 "archive(<req_id>): metadata" 跳
  │      └─ commit: git add requirements/<id>/{meta.yaml,process.txt,notes.md,artifacts/} + git commit -m "archive(<req_id>): metadata"
  │
  ├─ _push_feat_branch
  │      ├─ idempotent: git rev-parse HEAD == git rev-parse origin/feat/<id> 跳
  │      └─ push: git push origin feat/<id>
  │
  ├─ _create_archive_pr
  │      ├─ idempotent: gh pr list --head feat/<id> --base develop --json number,state --limit 1
  │      │      ├─ OPEN → 取 number 直接回写 + 跳
  │      │      ├─ MERGED → fail-closed (异常: 归档 PR 已合并但 archive_pr_number 未写)
  │      │      └─ CLOSED → fail-closed (异常: 用户手工关 PR, 待手工恢复)
  │      └─ create: gh pr create --base develop --head feat/<id> --title "archive(<id>): ..." --body-file archive-pr-body.md
  │
  ├─ _write_archive_pr_number
  │      ├─ idempotent: meta.archive_pr_number == 当前 number 跳
  │      └─ _atomic_write_meta(archive_pr_number=N)
  │
  └─ _render_summary  (含 manual_recovery_commands 段, 本流程通常为空)
```

### 流程 2：finalize 子命令（happy path）

```
$ python3 scripts/lib/archive_runner.py 20260521-archive-runner-auto-pr --finalize
  │
  ├─ _precheck_archive_pr_merged
  │      ├─ meta.archive_pr_number 缺失/0  → _abort R-FINALIZE-ARCHIVE-PR-MISSING (--force 跳)
  │      ├─ gh pr view 失败              → _abort R-FINALIZE-ARCHIVE-PR-FETCH-FAILED (--force 跳)
  │      └─ state != MERGED              → _abort R-FINALIZE-ARCHIVE-PR-NOT-MERGED (--force 跳)
  │
  ├─ 合并问询 ArchivePrompt(kind="finalize", question="...", default=False)
  │      ├─ --yes-finalize → 跳
  │      └─ user N → result.experience="aborted by user" + exit 0
  │
  ├─ os.chdir(main_repo_root)  (fail-closed, OSError 兜底 abort)
  ├─ git pull --ff develop      (fail-closed, 非 fast-forward 失败 abort)
  │
  ├─ _cleanup_worktree_before_archive  (--keep-worktree 跳)
  │      └─ 三步硬约束: resolve_main_repo_root → chdir → cleanup_worktree_if_owned
  │
  ├─ _delete_local_branch  (--keep-local-branch 跳; fail-closed 非 not-found)
  │
  └─ _delete_remote_branch  (--keep-remote-branch 跳)
         ├─ --legacy-resurrect-remote → remote not-found 视为 already-deleted (F-007)
         ├─ network/auth 失败 → fail-soft + append manual_recovery_commands
         └─ "remote ref does not exist" → already-deleted (现有逻辑保留, 来源：scripts/lib/archive_runner.py:607)
```

### 流程 3：失败重跑（idempotent）

```
$ python3 scripts/lib/archive_runner.py <req_id>    # 第一次, step 8 gh pr create 失败 fail-closed
... commit 已 step 6 落地, push 已 step 7 落地, archive_pr_number=0 ...

$ python3 scripts/lib/archive_runner.py <req_id>    # 第二次, 用户直接重跑
  │
  ├─ _precheck_dirty   PASS (whitelist 通过)
  ├─ _precheck_phase   PASS (phase=completed AND archive_pr_number=0 → 半完成允许)
  ├─ _atomic_write_meta  保留原 archived_at, 仅写缺字段
  ├─ _append_process_event  process.txt 末已含 [archived] 跳
  ├─ _run_experience      lessons_extracted=True 跳
  ├─ _commit_archive_metadata  git log 已含前缀, 跳
  ├─ _push_feat_branch        HEAD == origin/feat/<id>, 跳
  ├─ _create_archive_pr       gh pr list 返回 number, 直接取 + 跳 create
  ├─ _write_archive_pr_number  写 archive_pr_number=N
  └─ exit 0
```

## 5. 数据结构

### 5.1 ArchiveResult dataclass 扩展

定位：现有 ArchiveResult 已是阶段 1 / 阶段 2 汇总输出的载体；扩展 4 字段覆盖 PR + worktree + manual_recovery 新语义。

```python
@dataclass
class ArchiveResult:
    # —— 现有字段（保留, 不改）——
    req_id: str
    archived_at: str = ""
    phase: str = ""
    experience: str = ""       # yes / no / skipped / failed
    local_branch: str = ""     # deleted / kept / skipped / failed
    remote_branch: str = ""    # deleted / kept / skipped / already-deleted / failed
    error_messages: list[str] = field(default_factory=list)

    # —— F-002 新增（archive 主流程写入）——
    archive_pr_number: int = 0     # 0 表示未写入；render_summary 跳过
    archive_pr_url: str = ""       # render_summary 展示
    archive_pr_action: str = ""    # created / reused (idempotent 命中) / skipped

    # —— F-003 新增（finalize 子命令写入）——
    worktree_removed: str = ""     # removed / kept / skipped / failed
    manual_recovery_commands: list[str] = field(default_factory=list)  # D-007 fail-soft
```

### 5.2 meta-schema 字段新增

**optional_fields 段**（来源：context/team/engineering-spec/meta-schema.yaml:132）追加：

```yaml
optional_fields:
  - reviews
  - archived_at
  - legacy
  - archive_pr_number   # 新增：归档 PR number；archive 阶段 1 创建后写入；finalize 阶段读取校验 MERGED
```

**fields 段**（来源：context/team/engineering-spec/meta-schema.yaml:141）追加：

```yaml
fields:
  archive_pr_number:
    type: int
    required: false
    description: "归档 PR number (archive 阶段 1 创建; finalize 阶段读取校验 MERGED); 0/缺失视同未创建"
```

### 5.3 check_meta.py 状态机

新增 `_check_archive_pr_number_state_machine(meta, report, file_label)`，对照 `_check_archived_at_state_machine`（来源：scripts/lib/check_meta.py:150）模式：

| 场景 | meta.phase | meta.archive_pr_number | 校验结果 |
|---|---|---|---|
| 1 | != completed | 0 / 缺失 | PASS |
| 2 | != completed | > 0 | FAIL（"非 completed 阶段不应写 archive_pr_number"） |
| 3 | == completed | 0 / 缺失 | PASS（兼容 15 个历史 completed REQ） |
| 4 | == completed | > 0 | PASS（正常归档完成） |

**backward-compat 保证**：场景 3 PASS 让历史 REQ 不需要 backfill；finalize 子命令读 archive_pr_number=0 时 fail-closed exit 1，--force 跳过。

## 6. PR 拆分

| PR | Features | 依赖 | 工作量 | 关键风险 |
|---|---|---|---|---|
| **PR-A** | F-004 + F-006 | 无 | ~1.7 天 | check_meta 状态机回归测试需覆盖 4 场景 |
| **PR-B** | F-001 + F-002 | PR-A 字段 | ~3.8 天 | R-T02 _precheck_dirty 白名单 / R-T04 gh pr create 失败但 PR 已建 |
| **PR-C** | F-003 + F-005 + F-007 | PR-B 主流程稳定 | ~6.6 天 | R-T03 finalize 三 cwd 路径 / R-S01 --force 误删 |

**关键路径**：PR-A → PR-B → PR-C 串行（10-14 天区间，来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:228）。

**PR-A 内部并行**：F-004 + F-006 可同 commit 也可分两个 commit（schema 单文件改 + 文档分开）。

**PR-B / PR-C 内部并行**：F-002 依赖 F-001 主流程稳定；F-003 / F-005 / F-007 依赖 PR-B 整体合入后才能 e2e。

## 7. 待澄清（沿用 tech-research）

继承 tech-research §detail-design 阶段处理项 6 条（来源：requirements/20260521-archive-runner-auto-pr/artifacts/tech-research.md:271）：

1. PR body 模板内容定稿（F-002）
2. `--force` 与 `--yes-finalize` 组合 stderr 警告文案（D-006 + R-S01）
3. commit message 前缀（本期决策落地：`archive(<req_id>): metadata`）✅
4. gh pr list idempotent 检查的 PR 状态处置（R-T04）
5. manual_recovery_commands 字段在 ArchiveResult dataclass 中的位置（本期决策落地：见 §5.1）✅
6. `--keep-*` 三 flag 的 process.txt 事件（D-005 落实）

本阶段新增清单：

- **待澄清 #7**：archive 主流程内 `_commit_archive_metadata` 的 `git add` 范围——是否包括 `requirements/<id>/artifacts/lessons-learned.md`（若 F-005 经验沉淀生成）？detail-design 拍板。
- **待澄清 #8**：finalize 子命令的 `git pull --ff develop` 在 worktree 内跑时是否需先回到主仓的 develop？现有 `os.chdir(main_repo_root)` 已先于 pull，但 pull 之后立刻 cleanup_worktree 可能让 chdir 路径失效——执行顺序需明确。

## 8. 结构级开放问题

- **AC-A1**：现有 `_delete_local_branch`（来源：scripts/lib/archive_runner.py:430）在 archive 主流程内 fail-soft；finalize 路径要求改 fail-closed。是新建 `_finalize_delete_local_branch` 还是给现有函数加 `strict: bool` 参数？建议后者（避免代码重复，单一事实源），detail-design 拍板。
- **AC-A2**：`_render_summary` 现有签名 `_render_summary(result: ArchiveResult) -> str`；新增 manual_recovery_commands 段不破坏签名，但 archive 主流程与 finalize 子命令共用同一函数时，"summary 顶部标题行" 是否要区分 stage 1 / stage 2？建议加 `stage: Literal["archive", "finalize"]` 参数，detail-design 落地。
- **AC-A3**：archive_pr_number 字段在 meta.yaml 中的物理位置——放在 process 组（id/title/phase 旁）还是单独的 archive 组？建议跟在 `pr_url: ""` `pr_number: 0` 后面（同属 PR 类元信息），保持流程组紧凑。
