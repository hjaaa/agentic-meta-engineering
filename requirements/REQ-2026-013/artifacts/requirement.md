---
id: REQ-2026-013
title: "REQ-2026-012 follow-up bundle：reviewer artifact 选择 / hook 仓库外路径 normalize / archive 前预检 R-rule / experience spec 与实践对齐 / test-assets 经验补节"
created_at: "2026-05-17 18:07:10"
refs-requirement: true
---

# REQ-2026-013 · REQ-2026-012 follow-up bundle

## 背景

REQ-2026-012（CI 工程化补强）在 development → testing → archive 三个阶段累积出 5 项 low 优先级 follow-up，全部 follow-up 共享同一类「framework 流程 / spec 与实践对齐」议题。本需求把这 5 项打包推进，避免 follow-up 散落到多个独立 hotfix 增加追溯成本。

5 项 follow-up 的具体来源：

- **F-A**：D-010 ADR 反思——detail-design reviewer 把 `task.md` 整文件 hash 钉死，dev 期间 `status: pending → in-progress → done` + `updated_at` 推进必然触发 R005 stale；本需求 6 个 feature 串行推进 → 6 次 R005 报错（来源：requirements/REQ-2026-012/plan.md）（来源：context/team/experience/reviewer-artifact-selection-excludes-evolving-frontmatter.md）
- **F-B**：D-011 候选——主 Agent 在 dispatch lock 上锁（current_feature=F-003）期间 Write `/tmp/F-003-verdict.json` 准备 verdict 文件，被 `touches_guard.py` 误记 2 条 violation（来源：requirements/REQ-2026-012/notes.md）（来源：context/team/experience/hook-path-normalization-out-of-repo.md）
- **F-C**：归档时 framework R-rule fullset trap——REQ-2026-012 PR #76 推到 develop 后 CI 红，原因是 `phase=completed` 触发 framework R-rule 全集，暴露 4 处 definition / outline-design 阶段的 R005 hash drift（来源：context/team/experience/archive-completed-triggers-framework-rule-fullset.md）
- **F-D**：F-007 review verdict 已抓出 `context/team/experience/INDEX.md` 的「200 字硬规则」+「四节齐全要求」与 38 邻居实际写作风格双双脱节（94.7% 违反字数 / 2.6% 缺 `## 验证方法` 节）（来源：requirements/REQ-2026-012/artifacts/review-20260517-163512.md）
- **F-E**：同 F-007 review verdict —— `test-assets-must-be-wired-into-ci.md` 本身是 38 邻居中 2.6% 缺 `## 验证方法` 节的孤例（来源：requirements/REQ-2026-012/artifacts/review-20260517-163512.md）

## 目标

- **主目标**：把 5 项 follow-up 打包落地，根治 REQ-2026-012 暴露的 4 类结构性 trap（R005 假阳性 / touches_guard 假阳性 / archive 后 CI 假阴性 / experience spec drift）
- **次要目标**：
  - 让未来「detail-design → dev N feature 串行」的需求**不再**重复 N 次 hash refresh
  - 让主 Agent 在 dispatch lock 期写仓库外路径**不再**被误记 violation
  - 让 archive 流程**在 PR 推出前**就能发现 framework R-rule 漂移
  - 让 experience 体系 spec 与 38 文件既定实践重新对齐（rule == reality）

## 用户场景

### 场景 1：F-A · dev 多 feature 串行推进后切 testing 阶段

- **角色**：主 Agent + 团队工程师
- **前置**：某需求 detail-design 阶段已 reviewer signoff，artifact_hashes 含 N 个 task.md；development 阶段 N 个 feature 已串行 done
- **主流程**：
  1. 切 testing 前主 Agent 跑 `python3 scripts/gates/run.py --trigger=phase-transition --from=development --to=testing`
  2. 期望：**R005 不报 N 个 task.md hash drift**（当前行为：必报，需手动 refresh N 次）
- **期望结果**：phase-transition 一次过，无需逐个 hash refresh，无需更新 plan.md D-010 类 ADR

### 场景 2：F-B · 主 Agent dispatch lock 期写 /tmp 准备 verdict

- **角色**：主 Agent
- **前置**：dispatch-state.json `current_feature=F-xxx`；Reviewer Agent 即将写 verdict，主 Agent 用 Write 工具准备 `/tmp/F-xxx-verdict.json`
- **主流程**：
  1. Write `/tmp/F-xxx-verdict.json` 触发 PreToolUse `touches_guard.py`
  2. 期望：**hook normalize 路径后识别为仓库外 → exit 0 不记 violation**（当前行为：记 violation 到 receipt.json.touches_violations[]，后续 phase-transition / submit GATE-TOUCHES-VIOLATION 误阻断）
- **期望结果**：receipt.json `touches_violations[]` 不增长；phase-transition / submit 不被假阳性阻断

### 场景 3：F-C · 主 Agent 跑 /requirement:archive

- **角色**：主 Agent + 团队工程师
- **前置**：PR squash-merged、需求 phase=testing、5 项 archive 硬门禁已过
- **主流程**：
  1. archive_runner 写 phase=completed + completed_at
  2. 推 chore PR 到 develop
  3. **当前行为**：CI 跑 `--trigger=ci --strict` 才发现 framework R-rule 全集触发 R005 → CI 红 → 手动 refresh 4 处 hash 再推
- **期望结果**：archive 前主 Agent 已知道「先跑 `python3 scripts/gates/run.py --trigger=ci --strict` 看 exit 0 再 archive」并将其写入 `reference/archive-rules.md` 流程清单 + archive 终端 reminder 末段加一行强提示

### 场景 4：F-D · 团队工程师写新经验文件

- **角色**：团队工程师 + 文档 reviewer
- **前置**：某需求归档时沉淀新经验到 `context/team/experience/<slug>.md`，参考 INDEX.md:63-68（格式约定段） 规则
- **主流程**：
  1. 工程师按当前规则「正文 200 字 + 四节齐全（问题/根因/解法/验证方法）」写
  2. **当前行为**：200 字硬规则与 38 邻居实际行为脱节（94.7% 违反），工程师困惑
- **期望结果**：INDEX.md:63-68（格式约定段） 规则改为「正文建议 600 字内，五段结构（问题/根因/解法/验证方法/关联）」，与既定实践对齐；列出 38 邻居中缺 `## 验证方法` 节的清单作为 follow-up 但本需求不补

### 场景 5：F-E · `test-assets-must-be-wired-into-ci.md` 补节

- **角色**：F-D 落地后回头扫，把 test-assets 这一份与新规则对齐
- **前置**：F-D 已合入（INDEX.md 规则已修订）
- **主流程**：把当前 `## 解法` 中的 PR 描述硬约束 + 手跑命令 + owner 抽出来独立成 `## 验证方法` 节
- **期望结果**：文件结构与 97% 邻居一致；F-E 是 F-D 收尾的可见证据

## 非功能需求

- **性能**：F-A 的 hash 比对 normalize 不应明显增加 R005 校验时长（< +5% 在 1000 review 量级）；F-B 的 path normalize 不应增加 PreToolUse hook 延迟（< +1ms p99）
- **兼容性**：
  - F-A：**关键**——既有 ~13 个已 completed 需求的 verdict.artifact_hashes 是「整文件 hash」，A2 方案要求 R005 在比对 task.md 时双侧都先 strip frontmatter status/updated_at 再算 hash，从而不破坏历史 verdict（A1 改 reviewer 写法会破坏，所以放弃；详见 `requirements/REQ-2026-013/plan.md` D-001）
  - F-B：`git rev-parse --show-toplevel` 在 worktree / submodule 场景的边界——需保证 worktree 场景下 normalize 后仍能正确识别仓库根（详见待澄清清单第 1 条）
  - F-D：INDEX.md 规则改后，**不**回头改 38 文件正文（D1 决策），所以兼容性 = 0 破坏
- **安全/合规**：无（本需求纯结构性 + 文档调整，不触敏感数据 / 鉴权 / 加密路径）

## 范围

### 包含

- **F-A**：`scripts/lib/check_reviews.py` 的 R005 hash 比对逻辑：对 `tasks/*.md` 文件路径，去掉 frontmatter `status` / `updated_at` 字段后再算 hash 比对（来源：requirements/REQ-2026-013/plan.md）
- **F-B**：`.claude/hooks/touches_guard.py` PreToolUse：收 file_path 后 `Path(...).resolve()` + `git rev-parse --show-toplevel` 取仓库根，非仓库根之下的路径直接 exit 0 不记 violation（来源：context/team/experience/hook-path-normalization-out-of-repo.md）
- **F-C**：`.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md` 加 §「archive 前流程提示」，强制要求主 Agent 在跑 archive_runner 前先跑 `python3 scripts/gates/run.py --trigger=ci --strict` 看 exit 0；`archive_runner` 终端反馈末段加 `🟢 archive 前请确认 ci gate exit 0` 一行 reminder（来源：requirements/REQ-2026-013/plan.md）
- **F-D**：`context/team/experience/INDEX.md` 「格式约定」段从「正文不超过 200 字 / 必须包含：问题/根因/解法/验证方法」改为「正文建议 600 字内 / 必须包含：问题/根因/解法/验证方法/关联（关联段可空）」；同步补一段「兼容性 review」清单——列出 38 文件中缺 `## 验证方法` 节的孤例（仅本仓库已知就 1 个：`test-assets-must-be-wired-into-ci.md`），但本需求不补正文（来源：requirements/REQ-2026-013/plan.md）
- **F-E**：`context/team/experience/test-assets-must-be-wired-into-ci.md` 把 `## 解法` 段的 PR 描述硬约束 + 手跑命令 + owner 三条抽出独立成 `## 验证方法` 节，与 97% 邻居结构一致；依赖 F-D 已合入（来源：requirements/REQ-2026-013/plan.md）

### testing 阶段回归用例（来自 reviewer v1 建议）

- **schema-sync 回归**（来自 plan.md D-007 reviewer 反馈）：testing 阶段加一条 pytest 用例——读 `context/team/engineering-spec/task-frontmatter-schema.yaml` 的 `enums.status` 字段名集合，与 `check_reviews.py` normalize 白名单（`{"status", "updated_at"}`）对照；若 schema 加新「dev 期演进」字段而白名单未同步则 fail。位置 `tests/lib/test_check_reviews_normalize_schema_sync.py`。
- **F-D baseline 快照**（来自 reviewer v1 建议）：F-D commit 内附一份 `38 文件字数分布.txt` 作 baseline（min=139 / median=365 / max=668 / count=38 等统计），落 `requirements/REQ-2026-013/artifacts/experience-baseline-cjk-stats.txt`，方便未来 D-009 规则调整时回看决策当时的实证基础。

### 不包含（防 scope 蔓延）

- ❌ **不动 framework R-rule 本身**（R001~R007 语义、`check_reviews._run_r_rules` 主框架不改），只调 R005 读 hash 的方式
- ❌ **不补齐 38 份历史经验文件**（F-D D1 路径），列 follow-up backlog 但留下次清扫 REQ
- ❌ **不改 archive_runner 的 5 项硬门禁**（phase / dirty / pr_number / merged / lessons_extracted 不变），仅加文档级流程提示 + 终端 reminder（F-C B3 路径）
- ❌ **不引入新的 reviewer Agent 类型**（不改 code-quality-reviewer / aux-spec / security 等 8 个既有 Agent 实现）
- ❌ **不改 PreToolUse hook 的其它路径**（dispatch_precheck.py / pre-tool-use-guard.sh / 其它 hook 不动），只 normalize touches_guard.py 的 path 校验

## 关键决策记录（前置闭环）

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| D-001 F-A 落地路径 | A1 改 reviewer / A2 改 R005 校验放宽 | **A2** | 兼容历史 ~13 个 completed 需求 verdict；A1 会破坏所有历史 hash 触发全量 R005 红 |
| D-002 F-C 实现方式 | B1 临时 yaml override / B2 写后 rollback / B3 纯文档兜底 | **B3** | 最朴素投入最小；archive 频次低，靠人 + 终端 reminder 已足够；B1/B2 是后续优化议题 |
| D-003 F-D 38 文件 review 范围 | D1 仅列清单 / D2 全补齐 / D3 补 F-E 一份 | **D1** | 避免本需求 scope 爆炸；38 文件补齐留下个清扫 REQ |
| D-004 PR 拆分 | 整批合一 / P1+P2 分批 | **整批合一** | 本 follow-up bundle 立意就是「打包收敛」；分开违反初衷 |
| D-005 「不做的事」段 | 写 5 条 / 删减 | **写 5 条** | 防 scope 蔓延 + 给 reviewer 明确边界 |

## 待澄清清单

definition 一轮回灯后 5 项均已闭环 → 见 plan.md ADR D-006~D-010：

1. **F-B worktree / submodule 边界** → **已闭环**（plan.md D-006）：worktree 场景实测验证按 cwd-driven normalize 工作正常（来源：requirements/REQ-2026-013/plan.md）
2. **F-A normalize 字段集合** → **已闭环**（plan.md D-007）：task-frontmatter-schema 9 字段扫描，dev 期演进仅 status + updated_at 2 个，其余设计期 frozen（来源：context/team/engineering-spec/task-frontmatter-schema.yaml）
3. **F-C `--trigger=ci` 单 req filter** → **已闭环**（plan.md D-008）：ci trigger 不支持 --req，B3 路径文档加 refresh-only-current-req 子句（来源：scripts/gates/plugins/review_verdict.py）
4. **F-D 弹性上限选定** → **已闭环**（plan.md D-009）：800 字（覆盖 38 邻居 ~99%）（来源：requirements/REQ-2026-013/plan.md）
5. **F-E 同 PR 合入顺序** → **已闭环**（plan.md D-010）：F-D commit → F-E commit，同 PR 内（来源：requirements/REQ-2026-013/plan.md）

tech-research 阶段不再需要回头处理这 5 项；可直接进入预研逐 feature 的可行性评估 + 工作量预估。
