---
id: REQ-2026-014
title: "outline-design · worktree 隔离能力完整迁移"
created_at: "2026-05-18"
refs-outline-design: true
---

# REQ-2026-014 · 概要设计

> 设计权威单源：`context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md` v0.2（DRAFT）。
> 本文档按 plan.md D-000 决议从 spec 抽取 + 补缺口；与 spec 偏差按"反修 spec → bump v0.3"路径处理。
> 阶段边界：只画**模块切分图 / 数据流 / 状态机 / 架构级选型摘要**；接口签名 / `features.json` / 字段 schema 留 detail-design。

## 架构方案

### 整体分层（在既有 4 层结构上定向补齐）

```text
命令层（slash commands）
  /workflow:run standard-8phase
  /requirement:submit          /requirement:archive
            │
            ▼
Skill 编排层
  managing-requirement-lifecycle   workflow-engine
            │
            ▼
新增 lib（本需求引入）
  scripts/lib/worktree_manager.py        ← detect / select / ignore / create / setup / cleanup
  scripts/lib/requirement_naming.py      ← slug / key / legacy 识别 / 分支 & 目录解析
            │
            ▼
既有 lib（本需求改造切面）
  workflow_run.py / workflow_bootstrap.py   ← bootstrap 替换点 + rollback
  archive_runner.py                         ← cleanup_worktree_if_owned 注入
  common.py / infer_run_id_from_branch      ← 新旧 key 并存识别
            │
            ▼
Git plumbing（subprocess）
  git rev-parse --git-dir / --git-common-dir
  git worktree add / list / remove / prune
  git branch / checkout / status --porcelain
```

四层职责分离原则：

- **命令层**只负责入参（含 `--slug` / `--no-worktree` / `--worktree-policy`）解析与提示输出；不直接调 git。
- **Skill 层**只编排顺序（bootstrap → setup → baseline → 提示），不内联策略判定。
- **新增 lib** 是本需求的"知识封装层"：所有 worktree 决策（policy 解析 / detect / owner / 白名单）单点收口在 `worktree_manager`，命名规则（slug / key / legacy / 分支 & 目录解析）单点收口在 `requirement_naming`，避免散落到 run / submit / archive。
- **既有 lib** 只做切面注入，不重写主干（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:261）。

### 数据流向

**bootstrap 时序（默认路径）：**

```text
/workflow:run standard-8phase "title" [--slug X]
  │
  ▼ workflow_run.main
parse_args → load workflow yaml → resolve worktree config（policy/location/baseline）
  │
  ▼
requirement_naming.generate_requirement_key(date, slug, requirements_root)
  → YYYYMMDD-<slug>[-NN]
  │
  ▼
worktree_manager.detect_worktree_state(repo_root)
  → {normal | linked | submodule | detached}
  │
  ▼ policy × state 决策（见关键流程一）
worktree_manager.select_worktree_location(...)
worktree_manager.ensure_worktree_dir_ignored(...)
worktree_manager.create_worktree(...)   ← git worktree add -b feat/req-<key> <base>
  │
  ▼
write requirements/<key>/meta.yaml / plan.md / process.txt / run-state.jsonl
  （路径 = worktree path，非主仓根）
  │
  ▼
worktree_manager.run_worktree_setup(worktree_path, policy)
  → make gates-validate（baseline.required=true 则失败即 fail）
  │
  ▼
append run-state.jsonl workflow_started（含 worktree 摘要）
  │
  ▼ 输出 cd 提示
```

**external worktree 复用分支（已在 linked worktree 内）：**

```text
detect_worktree_state → linked
  │
  ▼ 工作区 clean 校验：git status --porcelain
  │   非空 → fail-closed exit 1
  │   （来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:104）
  ▼
bind_current_worktree → owner=external
ensure_or_create_branch_in_current_worktree（若分支非目标 feat/req-* 才切）
  │
  ▼
write requirements/<key>/...  （路径 = 当前 worktree path）
skip baseline auto-run（external 不强制；可由 yaml.worktree.baseline.required 覆盖）
```

**archive cleanup 分支：**

```text
/requirement:archive
  │
  ▼ archive_runner.archive_requirement 内部
预检 5 项 → 4 个新 gate（POST-DEV-RECEIPT / TOUCHES-VIOLATION / FEATURES-SCHEMA / TASK-FRONTMATTER）
  │
  ▼ 新增切入点
worktree_manager.cleanup_worktree_if_owned(meta, REPO_ROOT)
  三重保护：owner=workflow ∧ path in whitelist ∧ cwd != worktree
  │
  ▼ 通过则
cd main_repo_root → git worktree remove <path> → git worktree prune
  │
  ▼ 未通过则
log "worktree cleanup skipped: external" 并继续
  │
  ▼
write meta.phase=completed + archived_at
```

### 关键组件职责（按"知识封装而非流程脚本"原则）

| 组件 | 单一职责 | 不做什么 |
|---|---|---|
| `worktree_manager.py` | 封装 worktree 全部决策与 git plumbing；输入是状态/策略，输出是 `WorktreeInfo` / `SetupResult` / `CleanupResult` | 不感知 requirement key 命名；不读 meta.yaml 字段语义之外的字段；不直接写 jsonl |
| `requirement_naming.py` | 单点封装命名规则（slug / key / legacy 识别 / 分支与目录解析） | 不感知 git；不感知 worktree；不读写文件 |
| `workflow_run.py` / `workflow_bootstrap.py` | 编排顺序 + active_repo_root 显式传递 + rollback 顺序 | 不内联 git worktree 命令；不内联 slug 校验 |
| `archive_runner.py` | 调用 `cleanup_worktree_if_owned`；保持 archive 接口契约 frozen（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:64） | 不直接调 `git worktree remove`；不改外部 owner 状态 |
| `common.py / infer_run_id_from_branch` | 新旧 key 并存识别（已落地于 commit #899b45f，来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:10） | 不感知 worktree 字段 |

---

## 模块划分

### 既有模块改造点（保持文件位置，新增切面）

| 文件 | 切面 | 改造规模 |
|---|---|---|
| `scripts/lib/workflow_run.py` | `_generate_req_id` → 改调 `requirement_naming.generate_requirement_key`；解析 `--slug` / `--no-worktree` / `--worktree-policy` | 中（≈ 50 行） |
| `scripts/lib/workflow_bootstrap.py` | `_checkout_feature_branch` 替换为 `worktree_manager.create_worktree` 路径；写文件顺序改为 worktree-first；`_bootstrap_rollback` 顺序补 worktree remove 前置（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:46） | 中（≈ 80 行） |
| `scripts/lib/archive_runner.py` | `archive_requirement` 5 项预检通过后、写 meta 之前注入 `cleanup_worktree_if_owned(meta, REPO_ROOT)`；外部 worktree 输出 skipped 日志（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:64） | 小（≈ 20 行） |
| `scripts/lib/common.py` | `infer_run_id_from_branch` 已支持新旧双格式（来源：scripts/lib/common.py:27），本需求不再改 | 不动 |
| `.claude/commands/requirement/submit.md` / Skill `managing-requirement-lifecycle` | submit 成功提示追加 `worktree retained at <path>; use /requirement:archive to clean up`；不调 `git worktree remove`（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:56） | 小（≈ 5 行 md） |
| `.claude/commands/requirement/archive.md` | 文档同步 cleanup 三重保护语义；接口契约保持 frozen（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:64） | 小（≈ 10 行 md） |

### 新增模块（2 个 .py 文件）

| 文件 | 行数估算 | 依赖 |
|---|---|---|
| `scripts/lib/requirement_naming.py` | ≈ 150 | `re` / `datetime` / `os.path`；标准库 only（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:18） |
| `scripts/lib/worktree_manager.py` | ≈ 250 | `subprocess` / `pathlib`；标准库 only（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:26） |

### 配置确认（不是新模块，仅审视既有文件）

| 文件 | 改动 |
|---|---|
| `.claude/workflows/requirement/standard-8phase.yaml` | 顶层增加 `worktree:` 配置组（enabled / policy / location / setup.baseline）；`workflow_loader._validate_schema_top` 不拒绝额外顶层字段，无 schema 修改风险（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:72） |
| `.gitignore` | 一次性追加 `.worktrees/`（已存在 `.claude/worktrees/`，来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:29） |
| `templates/meta.yaml.tmpl`（managing-requirement-lifecycle Skill） | 新增 `worktree:` 空结构占位（owner/path/baseline/cleanup） |

### 模块依赖关系（无环）

```text
requirement_naming.py  ──┐
                          │（key + 分支 + 目录解析）
                          ▼
worktree_manager.py  ─────┤  workflow_bootstrap.py  ─→  workflow_run.py
                          │            ▲
                          │            │
                          └─→  archive_runner.py
                                       ▲
                                       │
                          common.py（infer_run_id_from_branch）
```

环路审计：

- `requirement_naming` 不引用任何项目 lib → 叶子节点。
- `worktree_manager` 只引用 `subprocess` / `pathlib` / `common`；**不**引用 `requirement_naming`（命名/git 解耦）。
- `workflow_bootstrap` 同时引用 `requirement_naming` 与 `worktree_manager`，作为汇合点。
- `archive_runner` 仅引用 `worktree_manager`（不需要命名规则），保持单一职责。

---

## 技术选型（架构级 7 条 D 摘要）

> **筛选标准**：仅纳入影响**模块边界 / 数据流向 / 状态机字段**三类之一的决策；其余决策（D-002 启用范围 / D-007 submit 不清理 / D-008 archive cleanup 范围 / D-011 baseline 命令 / D-012 逃生阀策略 / D-015 分支前缀）只影响外部契约 / 默认值 / 策略文案，本阶段保持 spec / requirement 原表为权威。

### 选型一：worktree 隔离粒度 = requirement run（D-001）

- 候选：requirement run / feature / project / workflow run
- 选择：**requirement run**
- 取舍：一个需求目录 + 分支 + PR ↔ 一个隔离工作区，语义最简单，与 `feat/req-*` 现有契约一一对应（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:91）
- 演化触发：见 AC-A1

### 选型二：worktree 目录采用 `.worktrees/`（D-003）

- 候选：`.worktrees/` / `worktrees/` / `.claude/worktrees/` / `~/.config/superpowers/worktrees/<project>/`
- 选择：**`.worktrees/`**（对齐 Superpowers）
- 兼容：`.claude/worktrees/` 保留为 legacy 识别；`worktrees/` 与 global 仅做白名单识别（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:93）
- 风险：`.gitignore` 未生效 → 运行时 fail-closed（D-010）

### 选型三：已在 linked worktree 时复用（D-004 + D-005 兜底）

- 候选：嵌套创建 / 复用 / 报错
- 选择：**复用**（owner=external）；脚本层 fallback 始终用 `git worktree`，不调 harness native tool
- 取舍：脚本入口无法可靠探测 Codex/Claude harness native worktree tool，统一用 `git worktree` 命令兼容性最稳；harness 自有 worktree 由 detect 兜底（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:94）
- 风险：外部 worktree 内 dirty workspace → fail-closed（详见关键流程二）

### 选型四：provenance 写入 `meta.yaml`（D-006）

- 候选：单独 `worktree.json` / `meta.yaml.worktree` 块 / git note
- 选择：**`meta.yaml.worktree` 块**
- 取舍：meta.yaml 是单一事实源，status / archive / cleanup 都已经读它；新增独立文件会引入第二个同步点（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:96）
- 字段范围（6 类，具体字段列表与类型留 detail-design）：开关位（enabled）/ provenance（owner）/ 路径（path 系列）/ 分支引用（branch 系列）/ 生命周期时间戳（created_at / submitted_at / removed_at）/ baseline 与 cleanup 子块

### 选型五：cleanup 在主仓根执行（D-009）

- 候选：worktree 内 self-remove / 主仓根远程 remove
- 选择：**主仓根 remove**
- 取舍：在将被删除的 worktree 内调 `git worktree remove` 会因 cwd 失效报错；统一从主仓根执行更稳（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:99）
- 实现：`worktree_manager.resolve_main_repo_root(worktree_path)` 先解析主仓根 → cd → remove → prune

### 选型六：ignore 校验 fail-closed（D-010）

- 候选：warning / fail-closed
- 选择：**fail-closed**
- 取舍：未 ignore 的项目内 worktree 会污染 `git status`，让后续 git 操作误判；warning 无法保证开发者注意（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:100）
- 实现：`ensure_worktree_dir_ignored` 检查 `.gitignore` 中目标目录前缀；不匹配则 raise `WorktreeIgnoreNotConfigured` → exit 1

### 选型七：requirement key 命名 = `YYYYMMDD-<slug>`（D-013 + D-014 兼容）

- 候选：`REQ-YYYY-NNN`（旧） / `YYYYMMDD-<slug>`（新） / UUID / Jira ID
- 选择：**`YYYYMMDD-<slug>`**，旧需求兼容 in-place（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:103）
- 取舍：可读 + 并行友好 + 不依赖全局 max+1 扫描；牺牲数字递增的"自然排序"由日期前缀替代
- 实现：`requirement_naming.generate_requirement_key` 用原子 `mkdir(exist_ok=False)` 探测冲突 → `-02 / -03 / ... / -99` 顺序生成 → 溢出 fail-closed 提示改 slug（来源：requirements/REQ-2026-014/artifacts/requirement.md:173）

### 新依赖盘点

- 无新增三方依赖（标准库 `re` / `datetime` / `os.path` / `subprocess` / `pathlib` 已足够，来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:18）
- 不引入 pinyin / slugify 库（D-013 风险缓解：中文标题在命令层提示 `--slug`，脚本层 fail-closed，来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:170）

---

## 关键流程

### 流程一：bootstrap policy × state 决策（4×4 矩阵）

输入：

- `yaml.worktree.policy ∈ {auto, never, require, current}`（CLI `--worktree-policy` 可覆盖；`--no-worktree` ⇔ policy=never）
- `detect_worktree_state(repo_root) ∈ {normal, linked, submodule, detached}`

决策矩阵：

| policy ＼ state | normal | linked | submodule | detached |
|---|---|---|---|---|
| `auto` | **create owned**（默认） | **reuse external** | abort `E-WT-DETECT-001` | abort `E-WT-DETECT-002` |
| `never` | no worktree（owner=none） | no worktree（owner=none）但 warn 已在 worktree | no worktree | no worktree |
| `require` | **create owned** | **reuse external** | abort | abort |
| `current` | abort `E-WT-POLICY-CURRENT-001` | **reuse external** | abort | abort |

错误码（占位，detail-design 阶段精确化）：

- `E-WT-DETECT-001`：submodule 中不可创建 worktree（误判风险高，来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:34）
- `E-WT-DETECT-002`：detached HEAD 中不可创建 worktree
- `E-WT-POLICY-CURRENT-001`：policy=current 但当前为普通 repo（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:97）

### 流程二：external worktree 复用与 owner 判定（含 dirty workspace fail-closed）

```text
detect_worktree_state(repo_root) → linked
  │
  ▼
git status --porcelain
  │      ┌─ 非空且非白名单路径前缀（.worktrees/ / .claude/）─→ fail-closed exit 1
  │      │   stderr: 当前外部 worktree 存在未提交改动，请先 commit / stash / discard
  │      │           后重试，或加 --no-worktree 显式逃生
  │      │   （来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:104）
  │      └─ 空 或 全在白名单 → 继续
  ▼
解析当前 branch
  │      ┌─ branch == feat/req-<requirement_key> → 直接复用
  │      └─ branch != → 创建或切换到 feat/req-<requirement_key>
  ▼
WorktreeInfo(path=cwd, owner=external, created=false)
  │
  ▼
meta.worktree.owner = "external"
（后续 archive 阶段不会清理）
```

`owner` 三态约束：

- `workflow`：本需求 bootstrap 创建 → archive/discard 才清理
- `external`：harness 已在的 worktree 中复用 → 永不清理（输出 `worktree cleanup skipped: external`）
- `none`：policy=never 或非 worktree 模式 → 无清理动作

### 流程三：setup baseline 与失败处理

```text
worktree_manager.run_worktree_setup(worktree_path, baseline_cmd="make gates-validate")
  │
  ▼ subprocess.run(baseline_cmd, cwd=worktree_path)
  │  （gates/run.py 用 __file__ 定位 REPO_ROOT，不受 cwd 影响，
  │   来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:32）
  ▼
        ┌─ exit 0 ──→ meta.worktree.baseline.status=passed → 流程结束（成功）
        │
        └─ exit ≠ 0 ──→ meta.worktree.baseline.status=failed
                       worktree **保留**（不自动删失败现场，来源：spec §7.3）
                       branch **保留**
                       命令退出非零
                       stdout 输出修复建议：
                         · cd <worktree_path> 排查
                         · 修复后人工跑一次 baseline
                         · 或 /requirement:archive 收尾
```

设计意图（来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:478）：

- baseline 失败 ≠ 需要回滚 bootstrap：失败现场对排查有价值，不主动 cleanup
- `baseline.required=false` 可在 yaml 配置时让 setup 失败降级为 warning（仅 detail-design 实装）

### 流程四：archive/discard cleanup 三重保护

```text
/requirement:archive
  │
  ▼ archive_runner.archive_requirement
预检 5 项 + 4 新 gate（features schema / task frontmatter / receipt / touches）
  │
  ▼
worktree_manager.cleanup_worktree_if_owned(meta, repo_root)
  │
  ▼ 三重保护（任一失败 → skip + log）
  ┌──────────────────────────────────────────────────────┐
  │ 1. meta.worktree.enabled == true                     │
  │ 2. meta.worktree.owner == "workflow"                 │
  │ 3. meta.worktree.path startswith ∈ 允许目录白名单：  │
  │      .worktrees/ / worktrees/ / .claude/worktrees/   │
  │ 4. cwd != meta.worktree.path（cd 主仓根后才执行）    │
  └──────────────────────────────────────────────────────┘
  │
  ▼ 全过
cd <main_repo_root>
git worktree remove <meta.worktree.path>
git worktree prune
meta.worktree.cleanup.removed_at = now()
  │
  ▼ 任一失败
log "worktree cleanup skipped: <reason>"  （reason ∈ external / not-owned / path-not-whitelisted / cwd-collision）
meta.worktree.cleanup.removed_at = null
继续后续 archive 步骤（completed + archived_at）
```

discard 与 archive 的差异（详见 spec §8.3，本阶段不展开）：

- discard 走二次确认 + 强制清理（需明确"确认词"输入）
- archive 走默认 cleanup（三重保护不主动 prompt）

### 状态机：worktree.state 主状态机

```text
                    ┌──────────────────────────────┐
                    │  absent                       │   meta.worktree.enabled=false 或字段缺失
                    │  （legacy 旧需求 / never 路径）│
                    └──────────────────────────────┘
                          │ bootstrap create / reuse
                          ▼
            ┌─────────────────────────────┐ ◀──────────────────────────────┐
            │  pending                     │                                  │
            │  baseline.status=null        │                                  │
            └─────────────────────────────┘                                  │
              │                       │                                       │
        baseline pass            baseline fail                                │
              ▼                       ▼                                       │
   ┌─────────────────────┐  ┌─────────────────────────┐                       │
   │  active              │  │  baseline_failed         │ ── retry baseline ──┘
   │  baseline.status=    │  │  baseline.status=failed  │   （人工修复后回 pending）
   │  passed              │  │  worktree 保留排查       │
   └─────────────────────┘  └─────────────────────────┘
          │                       │
          │ submit                │ archive/discard 也可直接收尾
          ▼                       ▼
   ┌─────────────────────┐    （走下方 archived / discarded 路径）
   │  submitted           │
   │  pr_url 已回写       │
   │  cleanup 不触发      │
   └─────────────────────┘
          │
          │ archive（PR merged）         discard（明确确认）
          ▼                              ▼
   ┌─────────────────────┐    ┌─────────────────────────┐
   │  archived            │    │  discarded               │
   │  owned=workflow 才删  │    │  二次确认 + 强制清理      │
   └─────────────────────┘    └─────────────────────────┘
```

字段映射（meta.worktree.*）：

| 状态 | enabled | owner | baseline.status | cleanup.removed_at |
|---|---|---|---|---|
| absent | false / 缺 | none / 缺 | – | – |
| pending | true | workflow / external | null | null |
| active | true | workflow / external | passed | null |
| baseline_failed | true | workflow | failed | null |
| submitted | true | workflow / external | passed | null |
| archived | true | workflow / external | passed | timestamp（owner=workflow）或 null（external） |
| discarded | true | workflow | passed/failed | timestamp |

### 子状态机：bootstrap policy 决策

```text
yaml.worktree.policy（auto / never / require / current）
              │
              ▼
detect_worktree_state(repo_root)
   ┌──────────┬──────────┬──────────┬──────────┐
normal      linked    submodule    detached
   │          │           │           │
   ▼          ▼           ▼           ▼
matrix lookup（见关键流程一 4×4）
   │
   ├─ create owned ─→ select_location → ensure_ignored → git worktree add → WorktreeInfo(workflow)
   ├─ reuse external ─→ git status clean check → WorktreeInfo(external, created=false)
   ├─ no worktree ─→ WorktreeInfo(none)
   └─ abort ─→ raise WorktreePolicyError(<错误码>)
```

### rollback 顺序（spec §6.3 精炼）

bootstrap 任一步失败时 best-effort 回滚：

```text
1. 如果 worktree 已创建（owner=workflow）：
     cd <main_repo_root>
     git worktree remove --force <path>
     git worktree prune
2. 如果新 branch 已创建且未被 worktree 占用：
     git branch -D <feat/req-*>
3. 如果 requirements/<key>/ 残留（主仓根 / worktree 路径）：
     shutil.rmtree（防御性）
4. 输出原始失败原因（不用 rollback 失败掩盖根因，来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md:437）
```

注意顺序：必须 worktree remove 在 branch -D 之前，否则 branch 被 worktree 占用 git 会拒绝删除。

---

## 架构关注点与演化触发

> 这一节列出"本期不做、但需要在结构层面对其演化预留通道"的关注点。每条给出**触发条件**与**预留位置**，让未来扩展不至于重写主干。

### AC-A1：feature 级 worktree 粒度演化触发

- **现状**：粒度 = requirement run（D-001）
- **预留位置**：`worktree_manager.create_worktree` 的 `branch` 参数已抽象，未来支持 `feat/<req-key>-<feature-id>` 命名不需要改 API；`meta.yaml.worktree` 块设计为单 worktree，但 `features.json` 已有 feature_id，未来可扩展为 `features[i].worktree` 子块
- **触发条件**：
  - 同一 requirement 内多 feature 并行开发出现合并冲突 ≥ 3 次/周
  - 或 subagent 并行修改同 feature 内 ≥ 2 文件出现 lock 等待 > 30s
- **演化路径**：增加 `feature_id` 维度即可；本期不预创建 feature 级 worktree
- **detail-design 落地提示**：写 `meta-schema.yaml` 时 `worktree` 字段在注释中显式标注 "当前为单 worktree；未来 feature 级隔离需扩为 list / map by feature_id"，避免后续重构破坏向后兼容（依据：本阶段 reviewer 评审 architectural_concerns 第 1 条）

### AC-A2：Codex / Claude harness worktree 行为差异

- **现状**：`detect_worktree_state` 用 `git-dir` vs `git-common-dir` 二值判定 + submodule 路径排除；harness 行为差异由"复用 + owner=external"统一兜底
- **预留位置**：`WorktreeState` dataclass 已含 `git_dir / git_common_dir / is_submodule / is_detached` 字段，未来增加 `is_harness_native: bool` 仅需扩展字段不破契约
- **触发条件**：
  - 出现 harness 自带 worktree 但 `git-dir == git-common-dir` 的边缘 case（即 harness 不走 linked 路径）
  - 或 harness 注入环境变量 `CODEX_WORKTREE_PATH` / `CLAUDE_WORKTREE_PATH` 时需要识别
- **演化路径**：`detect_worktree_state` 增加 env 探测分支；外部 worktree 优先级仍高于 linked

### AC-A3：历史 `REQ-YYYY-NNN` 目录迁移演化触发

- **现状**：legacy in-place，不迁移（D-014）；`requirement_naming.is_legacy_requirement_key` 单点识别
- **预留位置**：`infer_run_id_from_branch` 与 `directory_for_requirement_key` 已支持新旧两种 key 解析（来源：scripts/lib/common.py:27）；任何"批量迁移"工具只需读 `legacy_numeric_id` 字段就能识别
- **触发条件**：
  - 历史 REQ 目录数量 ≥ 50 且经常被检索时
  - 或团队决定统一命名风格（业务决策）
- **演化路径**：单独需求 + `scripts/migrations/legacy_req_rename.py` 工具；本期不实施

---

## 待澄清清单

按当前阶段确认点继承自 requirement.md + tech-feasibility.md 的执行级遗留项，不在 outline 阶段新增"刨根问底"硬约束。本阶段新增以下结构级开放项：

### OD-1. `worktree_manager` 与 `requirement_naming` 是否解耦到底（架构级）

- **内容**：当前设计 `worktree_manager` 不引用 `requirement_naming`，让 worktree 决策与命名规则正交；好处是 worktree_manager 可单元复用，坏处是 `workflow_bootstrap` 需要同时持有两个 lib 的引用做组装
- **默认选择**：保持解耦，`workflow_bootstrap` 作为汇合点
- **备选**：在 `requirement_naming` 内提供 `WorktreeAddressing` helper（路径 + 分支同时给），让 `worktree_manager` 只接受组合对象
- **风险**：默认选择对 `workflow_bootstrap` 的圈复杂度有 +1~2 影响；备选会让 `requirement_naming` 失去"纯函数 / 无 git"特性
- **验证时机**：detail-design 阶段写两个 lib 的接口签名时复审

### OD-2. baseline.required 的 yaml 语义（结构级）

- **内容**：`yaml.worktree.setup.baseline.required` 当 true 时 baseline 失败 ⇒ exit non-zero；当 false 时 baseline 失败 ⇒ warning，bootstrap 仍成功。但此时 `meta.worktree.state` 落点是 `pending`、`active` 还是 `baseline_failed`？
- **默认选择**：required=true（默认） → 失败落 `baseline_failed` + exit 1；required=false → 失败落 `active`（baseline.status=failed）+ exit 0 + warning
- **风险**：required=false 路径让 `baseline_failed` 状态语义只在 required=true 时存在，状态机变成"按配置剪枝"
- **验证时机**：detail-design 阶段写状态机契约时锁死

### OD-3. `cleanup.policy` 字段是否本期落地（meta 字段）

- **内容**：spec §5.2 给出 `meta.worktree.cleanup.policy ∈ {owned-only, never}` 字段，但本需求"clean up 永远走 owned-only 三重保护"，`never` 选项当前无入口
- **默认选择**：**本期不读写** `cleanup.policy`；字段保留在 meta 模板作为未来扩展位（用户显式标"永不清理"的 owned worktree）；archive_runner 不消费此字段
- **风险**：模板字段冗余 → meta-schema CI 校验时可能 warn
- **验证时机**：detail-design 阶段决定是否在 `meta-schema.yaml` 中标 `cleanup.policy` 为 optional

### OD-4. baseline 在 owner=external 路径是否默认跑

- **内容**：external worktree 已由 harness 管理，主仓 bootstrap 默认**不**跑 baseline；但 `yaml.worktree.setup.baseline.required=true` 时是否强跑？
- **默认选择**：external 始终跳过 baseline；`required=true` 仅作用于 owner=workflow
- **风险**：external 用户得不到 baseline pass 保证；可通过 plan.md 或 onboarding 文档告知 external 路径需用户手动 `make gates-validate`
- **验证时机**：detail-design 阶段在 `run_worktree_setup` 函数注释中固化

---

## 阶段约束自检

- ✅ 未引入 detail-design 强度内容（无接口签名 / 无字段 schema / 无 `features.json` 拆分）
- ✅ 所有架构级决策标注引用来源（spec / requirement / tech-feasibility 行号）
- ✅ 状态机两张：worktree.state 主状态机 + bootstrap policy 决策子状态机
- ✅ 关键流程四条 + rollback 顺序，全覆盖 bootstrap / external / setup / cleanup
- ✅ 模块依赖无环（已审计）
- ✅ 架构关注点 3 条，预留位置 + 触发条件双字段
