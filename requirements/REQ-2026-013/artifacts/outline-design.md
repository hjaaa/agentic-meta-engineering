---
id: REQ-2026-013
phase: outline-design
title: "REQ-2026-012 follow-up bundle · 概要设计"
created_at: 2026-05-17 18:47:37
refs-outline-design: true
inputs:
  - requirements/REQ-2026-013/artifacts/requirement.md
  - requirements/REQ-2026-013/artifacts/tech-feasibility.md
  - requirements/REQ-2026-013/plan.md
---

# REQ-2026-013 · 概要设计

> 仅覆盖**模块边界 / 模块间契约 / 技术选型 / 关键流程时序**。
> 具体函数签名 / 代码片段 / pytest 文件名 / Markdown 文案最终行归 detail-design 阶段。

## 1. 设计目标与约束回顾

回应 requirement.md 的 5 feature 验收（来源：requirements/REQ-2026-013/artifacts/requirement.md）+ plan.md 的 10 条 ADR（D-001~D-010，来源：requirements/REQ-2026-013/plan.md）+ tech-feasibility.md 的 7 项风险 R-1~R-7（来源：requirements/REQ-2026-013/artifacts/tech-feasibility.md）：

- F-A R005 假阳性根治（A2 路径，D-001）；F-B PreToolUse 仓库外路径假阳性根治；F-C archive 前 CI gate 预检（B3 路径，D-002）；F-D INDEX.md 五段结构 + 800 字软上限（D-009）；F-E test-assets 补 `## 验证方法` 节（依赖 F-D，D-010）。
- 设计约束：不动 framework R001~R007 主框架（来源：requirements/REQ-2026-013/artifacts/requirement.md）「范围 §不包含」段；不改 archive_runner 5 项硬门禁；不补齐 38 邻居经验文件正文（D-003 D1）；整批合一 PR（D-004）。

## 2. 整体架构

### 2.1 模块视图

```
┌──────────────────── R005 hash 校验层 ────────────────────┐
│ scripts/lib/check_reviews.py::_r005_hash_drift           │
│   读 artifacts/tasks/*.md → strip frontmatter ──┐        │
│                                ↑                │        │
│        normalize 白名单契约 ←─ │                ▼        │
│        {"status","updated_at"}                   sha256  │
│        （来源：plan.md D-007）                            │
└──────────────────────────────────────────────────────────┘
   ↑ 比对方                                                  
   │ schema 来源                                              
   └── context/team/engineering-spec/task-frontmatter-schema.yaml

┌─────────────────── PreToolUse hook 层 ────────────────────┐
│ .claude/hooks/touches_guard.py::_main_inner               │
│   ┌──────────────────────────────────────────────────┐    │
│   │ 新增 _is_out_of_repo(fp)：                       │    │
│   │   resolve() + git rev-parse --show-toplevel      │    │
│   │   返回 True → continue（不记 violation）         │    │
│   │   返回 False → 原 _is_in_touches 路径不变        │    │
│   └──────────────────────────────────────────────────┘    │
│   契约：worktree cwd-driven 语义（plan.md D-006）         │
└───────────────────────────────────────────────────────────┘

┌─────────────────── archive 流程层 ────────────────────────┐
│ .claude/skills/managing-requirement-lifecycle/             │
│     reference/archive-rules.md                             │
│   §「archive 前 CI gate 预检」（新增节）                  │
│   ├─ 必跑：python3 scripts/gates/run.py --trigger=ci --strict│
│   ├─ refresh-only-current-req 子句（D-008）              │
│   └─ 其他 REQ 的 R005 手动 ack 流程                       │
│                                                            │
│ scripts/lib/archive_runner.py::_render_summary             │
│   尾段追加 1 行 🟢 reminder（B3 路径，不改硬门禁）         │
└────────────────────────────────────────────────────────────┘

┌──────────────── experience spec 层 ───────────────────────┐
│ context/team/experience/INDEX.md                           │
│   「格式约定」段：200 字 → 600 字建议 / 800 字软上限       │
│   节结构：四节 → 五节（新增「关联」节，可空）             │
│   兼容性 review 清单：列 38 邻居缺验证方法节孤例           │
│                                                            │
│ context/team/experience/test-assets-must-be-wired-into-ci.md│
│   「## 解法」段抽出验证方法节（独立 `## 验证方法`）        │
│   依赖 F-D 已合入（D-010 commit 顺序）                    │
└────────────────────────────────────────────────────────────┘
```

### 2.2 模块清单（commit 拆分对应）

| 模块 | 物理位置 | 本次改动 | 关联 feature | commit |
|---|---|---|---|---|
| R005 hash 校验 | scripts/lib/check_reviews.py | normalize body 前 strip 白名单字段 | F-A | C-A |
| PreToolUse hook | .claude/hooks/touches_guard.py | 新增 _is_out_of_repo 短路 | F-B | C-B |
| archive 流程文档 | .claude/skills/managing-requirement-lifecycle/reference/archive-rules.md | 新增 §「archive 前 CI gate 预检」 | F-C | C-C |
| archive 终端反馈 | scripts/lib/archive_runner.py | _render_summary 末段加 1 行 | F-C | C-C |
| experience 规则 | context/team/experience/INDEX.md | 格式约定段改写 + 兼容性 review 清单 | F-D | C-D |
| experience 实例 | context/team/experience/test-assets-must-be-wired-into-ci.md | 「## 解法」抽出验证方法节 | F-E | C-E |
| schema-sync 回归 | tests/lib/test_check_reviews_normalize_schema_sync.py | 新增 pytest 校验白名单 vs schema | F-A 配套 | C-A |
| baseline 快照 | requirements/REQ-2026-013/artifacts/experience-baseline-cjk-stats.txt | 38 文件字数分布统计落档 | F-D 配套 | C-D |

**commit 合并硬链**：C-D → C-E 顺序依赖（D-010，来源：requirements/REQ-2026-013/plan.md）；C-A / C-B / C-C / C-D 之间无强依赖、可并行；整批合一同 PR 内提交（D-004）。

## 3. 模块详细设计（概要）

### 3.1 R005 hash 校验层（F-A）

**改造点**：scripts/lib/check_reviews.py `_r005_hash_drift` 函数（来源：scripts/lib/check_reviews.py）。

**契约**：
- **触发**：仅当 `path_str.startswith("artifacts/tasks/")` 时执行 normalize；其他文件（requirement.md / outline-design.md 等）维持整文件 hash 不变。
- **strip 范围**：在首对 `---` 之间用 `re.sub(r"^(status|updated_at):.*$", "", content, flags=MULTILINE)` 去掉两行。
- **白名单常量**：`_NORMALIZE_FIELDS = {"status", "updated_at"}`，定义在 `check_reviews.py` 顶部，注释标注「来源：task-frontmatter-schema.yaml dev 期演进字段」。
- **向后兼容**：历史 ~13 个 completed 需求 verdict.artifact_hashes 钉的是整文件 hash；A2 双侧 normalize 后，已 done 状态 task.md strip 掉相同字段值，body 与 status 行外其余 frontmatter 不变，hash 不变（来源：context/team/experience/reviewer-artifact-selection-excludes-evolving-frontmatter.md）。
- **schema-sync 防漂**：新增 pytest 用例对比 `task-frontmatter-schema.yaml::enums.status` 字段集与白名单常量；schema 加新「dev 期演进」字段而白名单未同步即 fail（来源：requirements/REQ-2026-013/artifacts/requirement.md）「testing 阶段回归用例」段。

**模块边界**：normalize 是 R005 比对侧（read path）的局部行为，不向外暴露；其它 R-rule（R001~R004 / R006~R007）不感知（来源：scripts/lib/check_reviews.py）。

### 3.2 PreToolUse hook 层（F-B）

**改造点**：.claude/hooks/touches_guard.py `_main_inner` 函数（来源：.claude/hooks/touches_guard.py）。

**契约**：
- **新函数**：`_is_out_of_repo(fp: str) -> bool`——`Path(fp).resolve()` + 缓存 `git rev-parse --show-toplevel` 结果（函数局部变量缓存，单次 hook 调用内复用），路径不在 toplevel 子树则返回 True。
- **短路点**：`for fp in fps:` 循环开头加 `if _is_out_of_repo(fp): continue`，**早于** `_is_in_touches` 判断。
- **fail-open**：`git rev-parse` subprocess 异常仍走原 try/except（来源：.claude/hooks/touches_guard.py），异常时**不**短路，回退到原 in-touches 路径。
- **worktree 语义**：cwd-driven——`git rev-parse --show-toplevel` 在 worktree cwd 下返回 worktree 根；worktree 内路径按 worktree-local 语义判定（来源：requirements/REQ-2026-013/plan.md）D-006 决策。

**模块边界**：仅 touches_guard.py 一处，**不**改 dispatch_precheck.py / pre-tool-use-guard.sh / 其它 hook（来源：requirements/REQ-2026-013/artifacts/requirement.md）「范围 §不包含」段。

### 3.3 archive 流程层（F-C）

**改造点 1**：`.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md`（来源：.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md）。

**契约**：在现有 §「5 项预检」之后新增 §「archive 前 CI gate 预检」节，内容约 150 字：
- 强制要求主 Agent 调 `archive_runner.archive_requirement` 前先执行 `python3 scripts/gates/run.py --trigger=ci --strict`，exit 0 才继续。
- 说明 ci trigger **不**支持 `--req` filter（来源：scripts/gates/plugins/review_verdict.py），扫全仓时可能暴露其他历史 REQ 的 R005。
- 处置原则：只 refresh 当前归档 REQ 的 hash；其他 REQ 的 R005 单独记 follow-up，**不**强行修；若 ci gate exit ≠ 0 但所有 R005 都属于其他 REQ → 手动 ack 后可放行 archive（D-008，来源：requirements/REQ-2026-013/plan.md）。

**改造点 2**：scripts/lib/archive_runner.py `_render_summary` 函数（来源：scripts/lib/archive_runner.py）。

**契约**：在现有 6 行终端反馈末尾追加 1 行字符串字面量：
```
🟢 archive 前请确认 ci gate exit 0：python3 scripts/gates/run.py --trigger=ci --strict
```
不改 5 项硬门禁（phase / dirty / pr_number / merged / lessons_extracted），不引入新的 abort 路径（B3 路径，来源：requirements/REQ-2026-013/plan.md D-002）。

**模块边界**：reminder 是被动提示而非主动预检；将来如果 archive 频次升高，可升级为 B1（临时 yaml override 跑 R-rule 全集）或 B2（写后 rollback）路径（来源：context/team/experience/archive-completed-triggers-framework-rule-fullset.md）。

### 3.4 experience spec 层（F-D + F-E）

**F-D 改造点**：context/team/experience/INDEX.md「格式约定」段（来源：context/team/experience/INDEX.md）。

**契约**：
- **字数规则**：「正文不超过 200 字」改为「正文建议 600 字内，800 字是软上限；超出考虑拆分到独立 reference 文件」（D-009，来源：requirements/REQ-2026-013/plan.md）。
- **节结构规则**：四节齐全（问题/根因/解法/验证方法）→ 五节（问题/根因/解法/验证方法/关联，关联段可空）。
- **兼容性 review 清单**：F-D 同 commit 内附 38 邻居字数 baseline 快照 + 缺 `## 验证方法` 节孤例清单（已知 1 个：`test-assets-must-be-wired-into-ci.md`），落 `requirements/REQ-2026-013/artifacts/experience-baseline-cjk-stats.txt`（来源：requirements/REQ-2026-013/artifacts/requirement.md）「testing 阶段回归用例」段。
- **不补 38 文件正文**（D1 路径，来源：requirements/REQ-2026-013/plan.md D-003），留下次清扫 REQ。

**F-E 改造点**：context/team/experience/test-assets-must-be-wired-into-ci.md（来源：context/team/experience/test-assets-must-be-wired-into-ci.md）。

**契约**：
- 「## 解法」段中的「不进 CI 必须说明：手跑命令 + owner」三条信息**抽出独立**成「## 验证方法」节。
- 「## 解法」保留核心两条规则（PR 描述硬约束 + 默认进 CI），与「## 验证方法」职责拆分清晰。
- 与 F-D 新五段结构对齐（97% 邻居既有结构，来源：requirements/REQ-2026-013/artifacts/requirement.md）。

**commit 顺序硬约束**：C-D（INDEX.md 规则修订）→ C-E（test-assets 补节），同 PR 内（D-010，来源：requirements/REQ-2026-013/plan.md）。

## 4. 关键流程时序

### 4.1 R005 hash 比对 normalize 流程（F-A）

```
reviewer Agent         check_reviews._r005_hash_drift           verdict.json
   │                              │                                  │
   │  artifact_hashes={tasks/F-A.md: sha256_v1}                     │
   │ ─────────────────────────► │                                   │
   │                              │  for path, hash_v1 in items():  │
   │                              │    if path.startswith("artifacts/tasks/"): │
   │                              │      content = read_text(path)  │
   │                              │      content = re.sub(strip_fields, "", content) │
   │                              │      hash_now = sha256(content.encode()) │
   │                              │    else:                        │
   │                              │      hash_now = sha256(read_bytes(path)) │
   │                              │  drift = hash_now != hash_v1    │
   │                              │ ─────► R005 fail? ──┐           │
   │                              │                      ▼           │
   │                              │  历史 verdict.json 的 hash_v1   │
   │                              │  与 normalize 后 hash 相等       │
   │                              │  （因为 status / updated_at      │
   │                              │  在 hash 计算前已被 strip）      │
   │                              │  → drift=False → 通过           │
```

### 4.2 archive 前 CI gate 预检流程（F-C）

```
主 Agent              CLI: gates/run.py            ci.txt 全仓扫
   │                       │                          │
   │  /requirement:archive │                          │
   │  ┌──────────────┐     │                          │
   │  │ 步骤 1：预检 │     │                          │
   │  │ ci gate（B3）│     │                          │
   │  └──────┬───────┘     │                          │
   │         │ python3 scripts/gates/run.py            │
   │         │  --trigger=ci --strict                  │
   │         ├──────────────► │ run_all_requirements   │
   │         │                ├────────────────────► │ 全仓扫所有 REQ
   │         │                │  ◄─ 报告 R005 列表 ─ │
   │         │                │ exit code             │
   │         │ ◄─ exit 0 ─────│                       │
   │         │                                         │
   │         │ exit 0 → 继续 archive_runner            │
   │         │ exit ≠ 0 → 检查 R005 归属：             │
   │         │   - 全是其他 REQ → 手动 ack 后续        │
   │         │   - 含当前 REQ → refresh-only-current   │
   │         │                                         │
   │  ┌──────▼───────┐                                 │
   │  │ 步骤 2：调   │                                 │
   │  │ archive_runner│                                │
   │  └──────┬───────┘                                 │
   │         │ archive_requirement(REQ-ID)             │
   │         │ → _render_summary 末段                  │
   │         │   🟢 archive 前请确认 ci gate exit 0    │
   │         │ → phase=completed + completed_at        │
```

## 5. 技术选型 / ADR 回顾

| ADR | 选型结论 | 影响模块 |
|---|---|---|
| D-001 | F-A 走 A2（改 R005 校验放宽）不走 A1（改 reviewer Agent） | R005 hash 校验层 |
| D-002 | F-C 走 B3（纯文档兜底 + reminder）不走 B1 / B2（主动预检） | archive 流程层 |
| D-003 | F-D 走 D1（仅改规则，不补 38 文件正文） | experience spec 层 |
| D-004 | 5 feature 整批合一 PR | 全模块 |
| D-005 | requirement.md 写 5 条「不做的事」防 scope 蔓延 | 全模块（流程） |
| D-006 | F-B 用 cwd-driven `git rev-parse --show-toplevel`（worktree 实测通过） | PreToolUse hook 层 |
| D-007 | F-A normalize 白名单 = `{status, updated_at}`（schema 9 字段中仅这 2 个 dev 期演进） | R005 hash 校验层 |
| D-008 | F-C 文档加 refresh-only-current-req 子句（ci trigger 不支持 --req） | archive 流程层 |
| D-009 | F-D 字数软上限 = 800（覆盖 38 邻居 ~99%） | experience spec 层 |
| D-010 | F-E 在 F-D commit 之后（同 PR 内） | experience spec 层 |

## 6. 风险与回滚策略

| 风险 ID | 关联模块 | 回滚动作 |
|---|---|---|
| R-1 F-A normalize re.sub 误 strip body 内容行 | R005 hash 校验层 | revert C-A 提交即可恢复整文件 hash 路径 |
| R-2 F-A 白名单字段名与 schema 解耦静默失效 | R005 hash 校验层 | testing 阶段 schema-sync 用例兜底；fail 时手动同步白名单 |
| R-3 F-A 历史 completed 需求 A2 兼容性未实测 | R005 hash 校验层 | testing 阶段跑 ci gate 全仓扫确认；若新增 R005 → 手动 refresh + 记录 |
| R-4 F-B git subprocess 在非 git 目录抛异常 hook crash | PreToolUse hook 层 | fail-open try/except 兜底；revert C-B 回到原假阳性路径 |
| R-5 F-B worktree cwd 下主仓文件 false-negative | PreToolUse hook 层 | 设计内行为（worktree 隔离语义），不回滚；文档说明 |
| R-6 F-C reminder 被主 Agent 忽略 archive 后 CI 仍红 | archive 流程层 | revert 不需要；将来升级 B1 / B2 路径 |
| R-7 F-D 规则改完与 38 历史文件结构仍有 gap | experience spec 层 | F-D commit 内附兼容性清单作为下次清扫 REQ backlog |

**整体回滚原则**：5 个 feature 各自独立 commit（C-A / C-B / C-C / C-D / C-E），逆序 revert 可线性回到 develop 当前状态；C-E 单独 revert 时 C-D 的规则更新成果保留（C-D / C-E 是顺序依赖但不强耦合，来源：requirements/REQ-2026-013/plan.md D-010）。同 PR squash merge 后若需精细回滚，按 commit hash 单独 cherry-pick revert。

## 7. detail-design 阶段后续动作

- 输出 `artifacts/detailed-design.md`：
  - F-A 的 `_normalize_task_md_for_hash` 函数签名 + 完整 normalize 实现伪代码 + pytest 参数化用例骨架（含 body-contains-status 反例）
  - F-B 的 `_is_out_of_repo` 函数签名 + worktree / submodule / 非 git 三类 bats 用例骨架
  - F-C 的 archive-rules.md §「archive 前 CI gate 预检」完整 Markdown 文案 + _render_summary 改动行
  - F-D 的 INDEX.md 格式约定段最终 Markdown + 38 邻居字数 baseline 统计表（min/median/max/count + 缺验证方法节孤例清单）
  - F-E 的 test-assets-must-be-wired-into-ci.md diff（解法段缩减 + 验证方法节新增文案）
  - 5 项 detail-design 待决问题闭环（来源：requirements/REQ-2026-013/artifacts/tech-feasibility.md）§4「detail-design 待决问题」段
- 输出 `artifacts/features.json`：F-A / F-B / F-C / F-D / F-E 5 项 + 各自 `touches[]` + AC 引用 + 依赖关系（F-E depends_on F-D）。
- 输出 `tasks/F-*.md`：每个 feature 一份 task frontmatter（含 schema_version / feature_id / title / status=pending / created_at / updated_at / complexity / depends_on / touches 9 字段，来源：context/team/engineering-spec/task-frontmatter-schema.yaml）。

## 8. 引用源汇总

- requirements/REQ-2026-013/artifacts/requirement.md — 需求文档（5 feature 验收 / 5 决策 D-001~D-005 / 范围段「不做的事」5 条）
- requirements/REQ-2026-013/artifacts/tech-feasibility.md — 技术可行性（5 feature 逐项 high / 7 风险 R-1~R-7 / 工作量 7h / 5 detail-design 待决）
- requirements/REQ-2026-013/plan.md — D-001~D-010 ADR
- scripts/lib/check_reviews.py — `_r005_hash_drift` 函数（F-A 改造点）
- .claude/hooks/touches_guard.py — `_main_inner` 函数（F-B 改造点）
- .claude/skills/managing-requirement-lifecycle/reference/archive-rules.md — archive 流程文档（F-C 改造点 1）
- scripts/lib/archive_runner.py — `_render_summary` 函数（F-C 改造点 2）
- context/team/experience/INDEX.md — 格式约定段（F-D 改造点）
- context/team/experience/test-assets-must-be-wired-into-ci.md — 经验文件（F-E 改造点）
- context/team/engineering-spec/task-frontmatter-schema.yaml — task frontmatter 9 字段 schema（F-A 白名单同步源）
- context/team/experience/reviewer-artifact-selection-excludes-evolving-frontmatter.md — F-A 经验
- context/team/experience/hook-path-normalization-out-of-repo.md — F-B 经验
- context/team/experience/archive-completed-triggers-framework-rule-fullset.md — F-C 经验
- scripts/gates/plugins/review_verdict.py — ci trigger 不支持 --req filter 源（F-C D-008 依据）
