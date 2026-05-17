# REQ-2026-013 · REQ-2026-012 follow-up bundle：reviewer artifact 选择 / hook 仓库外路径 normalize / archive 前预检 R-rule / experience spec 与实践对齐 / test-assets 经验补节

## 目标

将 REQ-2026-012 归档时积累的 5 项低优先级 follow-up 统一打包交付，消除框架层技术债并对齐规约与实践。

## 范围

### 候选 5 feature

来自 REQ-2026-012 归档时累积的 5 项 low 优先级 follow-up，统一打包为本需求：

| 候选 | 来源 | 优先级 | 范围 |
|---|---|---|---|
| F-A | D-010 反思 / `reviewer-artifact-selection-excludes-evolving-frontmatter.md` | P1 | reviewer Agent 写 verdict.artifact_hashes 时，对含 frontmatter 的文件（task.md / features.json）只 hash body，或 R005 校验放宽到去掉 frontmatter `status` / `updated_at` 后比对。择一落地 + 历史已 completed 需求兼容性回归。 |
| F-B | D-011 候选 / `hook-path-normalization-out-of-repo.md` | P1 | `.claude/hooks/touches_guard.py` PreToolUse 收 file_path 时先 `Path(...).resolve()` 取仓库根 `git rev-parse --show-toplevel`；非仓库根之下的路径直接 exit 0 不记 violation。配套 bats 用例（写 /tmp / /var / ~/）。 |
| F-C | `archive-completed-triggers-framework-rule-fullset.md` 已存在；本 feature 在 archive_runner 加预检 | P1 | `archive_runner.archive_requirement` 在 5 项硬门禁后加第 6 项「framework R-rule 全集 selfcheck」——本质就是跑 `scripts/gates/run.py --trigger=ci --strict --req=<id>`，避免归档后 develop CI 红。 |
| F-D | `context/team/experience/INDEX.md:64-65` 规则修订 | P2 | 删字数硬规则（"正文不超过 200 字"）→ 改"建议 600 字内弹性上限"；保留四节齐全语义约束；对 38 份历史经验文件做兼容性 review，标记需补 `## 验证方法` 节的候选清单。 |
| F-E | `test-assets-must-be-wired-into-ci.md` 补 `## 验证方法` 节 | P3 | 把当前 `## 解法` 中的 PR 描述硬约束 + 手跑命令 + owner 信息抽出来独立成 `## 验证方法` 节，与 97% 邻居结构对齐。 |

### 依赖关系

F-A / F-B / F-C 互相独立可并行；F-D 是 F-E 的前置（先修规则再补节，避免补完节字数又被新规则卡）；F-D 引发的"38 文件兼容性 review"如果体量过大，再拆子需求或留入 backlog。

- 包含：见上方「候选 5 feature」表 5 个 feature 的范围列
- 不包含：
  - 不动 framework R-rule 本身（R001~R007 语义、`check_reviews._run_r_rules` 主框架不改），只调 R005 读 hash 的方式
  - 不补齐 38 份历史经验文件（D-003 D1 路径），列 follow-up backlog 但留下次清扫 REQ
  - 不改 archive_runner 的 5 项硬门禁，仅加文档级流程提示 + 终端 reminder（D-002 B3 路径）
  - 不引入新的 reviewer Agent 类型（不改 code-quality-reviewer / aux-spec / security 等 8 个既有 Agent 实现）
  - 不改 PreToolUse hook 的其它路径（dispatch_precheck.py / pre-tool-use-guard.sh / 其它 hook 不动），只 normalize touches_guard.py 的 path 校验

### 候选风险

- F-A 落地需考虑历史 ~10+ completed 需求 hash 是否要 backfill；可能需要 migration 脚本
- F-B `git rev-parse --show-toplevel` 在 worktree / submodule 场景的边界用例
- F-C selfcheck 命令调 `--trigger=ci --strict --req=<id>` 但 ci trigger 默认是全仓扫，需要确认 plugin precheck 是否支持单 req filter
- F-D 修 38 历史文件可能与本需求 scope 冲突，建议把 review 行为限制在「列清单」+「后续单独 PR 改」

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

- F-A hash backfill：历史 completed 需求约 10+ 个，需 migration 脚本；风险：数据不一致 / 回归测试成本高
- F-B worktree/submodule 边界：`git rev-parse --show-toplevel` 在 linked worktree 下可能返回主树路径，需专项 bats 用例覆盖
- F-C ci trigger 单 req filter：需确认 `run.py --req=<id>` 在 ci trigger 下是否已支持，否则 archive_runner 调用会扫全仓
- F-D 38 文件体量：如 review 发现多数文件需改，考虑拆为独立子需求，避免 PR 过大

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 F-A 落地路径——A2 改 R005 校验放宽（不动 reviewer）

- **Context**：F-A 有两条路径修复 detail-design.artifact_hashes 钉 task.md 导致的 R005 假阳性：A1 改 reviewer Agent 写 verdict 时只 hash body / A2 改 `check_reviews.py` R005 比对时双侧 strip frontmatter status+updated_at 再算 hash。
- **Decision**：A2。
- **Consequences**：好——兼容本仓库 ~13 个已 completed 需求 verdict（A1 会让所有历史 hash 立刻失效触发 R005 全红）；逻辑两行 `re.sub` 解决；可扩展（未来若 frontmatter 加新状态字段加到 normalize 白名单即可）。差——R005 校验 normalize 操作在比对侧而非写入侧，逻辑稍隐式；缓解：在 `check_reviews.py` 顶部注释清楚 normalize 字段白名单语义。
- **时间**：2026-05-17

### D-002 F-C 实现方式——B3 纯文档兜底（archive_runner 不写代码）

- **Context**：F-C 有 B1 (临时 yaml override 跑 R-rule 全集) / B2 (写后 rollback) / B3 (纯文档兜底) 三选一。
- **Decision**：B3。在 `.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md` 加 §「archive 前必跑流程」，明确「先跑 `python3 scripts/gates/run.py --trigger=ci --strict` 看 exit 0 再 archive」；`archive_runner` 终端反馈末段加一行 reminder 文案。
- **Consequences**：好——投入最小（archive_runner 代码 0 改动）；archive 是低频动作（一周 1-2 次量级），靠流程提示 + 终端 reminder 已足够；保留 B1/B2 作为未来如果 archive 频次升高再升级的路径。差——靠人执行流程；缓解：终端 reminder 是 archive_runner 自动打印，主 Agent 看不见也会被流程文档约束。
- **时间**：2026-05-17

### D-003 F-D 范围——D1 只改规则不补 38 历史文件

- **Context**：F-007 review verdict 抓出 `context/team/experience/INDEX.md` 规则与 38 邻居实践脱节。可选 D1 仅改规则文本 / D2 改规则 + 补齐 38 文件正文 / D3 改规则 + 补 F-E 一份。
- **Decision**：D1。本需求只动 INDEX.md 规则文本，38 文件正文留下次清扫 REQ；F-E 单独作为本需求收尾的可见证据，独立 commit。
- **Consequences**：好——本需求 scope 可控（5 feature ~250 行代码内）；下次清扫 REQ 可批量校准 38 文件结构。差——规则与历史文件仍有结构不齐（部分文件缺 `## 验证方法` 节）；缓解：F-D 同 commit 内追加一段「兼容性 review 清单」，列出 38 中需补节的文件名，作为下次清扫 REQ 的现成 backlog。
- **时间**：2026-05-17

### D-004 PR 拆分——整批合一

- **Context**：5 个 feature 是否绑定到同一 PR？候选：整批合一 / P1 (F-A/F-B/F-C) + P2/P3 (F-D/F-E) 分批。
- **Decision**：整批合一。
- **Consequences**：好——本 follow-up bundle 立意即是"打包收敛 REQ-2026-012 5 项 follow-up"；分开违反初衷；PR 体量 ~250 行 diff 仍在 reviewer 友好范围。差——P1 风险高时无法单独 revert；缓解：5 个 feature 之间无相互依赖（F-E 依赖 F-D 但在同 PR 内 commit 顺序保证），若 P1 出问题可在 same PR 内 revert 单 commit 而非整 PR。
- **时间**：2026-05-17

### D-005 「不做的事」段——写 5 条防 scope 蔓延

- **Context**：requirement.md §范围 是否要显式列出「不做的事」？候选：写 / 删减。
- **Decision**：写 5 条。
- **Consequences**：好——给 reviewer 明确边界；防止 dev 期间 scope 蔓延（如有人想顺手补 38 文件）；同时给未来读者明确指引「这次没做」。差——文档稍冗长；缓解：5 条都是一句话级别，不影响主文档可读性。
- **时间**：2026-05-17

### D-006 F-B worktree 边界——按 cwd-driven normalize 实测验证

- **Context**：F-B 的 `touches_guard.py` normalize 实现要用 `git rev-parse --show-toplevel`，担心 worktree / submodule 场景反例。
- **Decision**：实测 worktree 场景（commit `4955ff7` 之后的本会话实验）：
  - worktree 添加到 `/tmp/test-wt-req-2026-013`，在 worktree cwd 下 `git rev-parse --show-toplevel` 返回 worktree 根（`/private/tmp/test-wt-req-2026-013`），不是主仓根
  - `Path('/tmp/foo.json').resolve().relative_to(toplevel)` 抛 ValueError → out_of_repo（正确）
  - worktree 内的 `Makefile` 被识别 in_repo（正确）
  - **边界 case**：worktree cwd 下，主仓的 `Makefile` 被识别 out_of_repo（按 worktree 视角合理；hook 默认 cwd ≠ worktree 不触发该 case）
- **Decision**：F-B 实现按「hook 进程 cwd 调 `git rev-parse --show-toplevel` 取仓库根」即可；worktree 场景按 worktree-local 语义工作，符合 normalize 设计意图。
- **Consequences**：好——不需要特判 worktree；语义自然（cwd 即用户当前工作上下文）。差——主仓文件在 worktree cwd 下 false-negative（视为 out_of_repo 不记 violation）；缓解：这是预期行为（worktree 是隔离环境），文档里写明。
- **时间**：2026-05-17

### D-007 F-A normalize 字段集合——只 strip status + updated_at

- **Context**：F-A 双侧 strip frontmatter 需明确「哪些字段属于 dev 期演进 / 哪些属于设计期 frozen」。
- **Decision**：基于 `context/team/engineering-spec/task-frontmatter-schema.yaml` 的 9 个 required 字段全集分析：
  - **dev 期演进**：`status` (pending → in-progress → done) / `updated_at` (随状态推进刷新)
  - **设计期 frozen**：schema_version / feature_id / title / complexity / depends_on / touches / created_at
- **Decision**：normalize 白名单 = `{"status", "updated_at"}`。`check_reviews.py` 比对 task.md hash 时双侧先 strip 这 2 个字段对应的 frontmatter 行再算 hash。
- **Consequences**：好——字段集合明确不漏不多；future-proof（若 schema 加新「dev 期演进」字段，白名单可扩展）。差——字段名硬编码在 `check_reviews.py`，与 schema 解耦；缓解：在白名单常量旁加注释 `# 来源：task-frontmatter-schema.yaml`，且评审 schema 升级时必查白名单同步。
- **时间**：2026-05-17

### D-008 F-C ci trigger 不支持 --req filter——B3 路径加 refresh-only-current-req 子句

- **Context**：F-C 预检要让主 Agent 跑 `python3 scripts/gates/run.py --trigger=ci --strict` 在 archive 前，但 `review_verdict.py:97-98` 显示 ci trigger 直接走 `review_verdict_ci.run_all_requirements` 全仓扫，不支持 `--req=<id>` filter。
- **Decision**：B3 路径文档在 `archive-rules.md` 写明：
  - 预检 ci gate 会扫全仓所有需求，可能暴露**其它历史 REQ 的 R005**
  - 处置原则：只 refresh **当前归档 REQ** 的 hash（按 D-010 同源原则）；其它 REQ 的 R005 单独记 follow-up 不强行修
  - 若现 ci gate exit ≠ 0 但所有 R005 都属于其它 REQ → 视为可放行 archive（手动 ack）
- **Consequences**：好——不需要给 ci trigger 加 `--req` filter（plugin precheck 改造可避免）；让流程文档承担过滤职责。差——主 Agent 需要按指引判断 R005 是否属于当前 REQ；缓解：grep `meta_path` 列即可快速分类。
- **时间**：2026-05-17

### D-009 F-D 弹性上限——800 字（覆盖 ~99% 既定文件）

- **Context**：F-D 把 INDEX.md「200 字硬规则」改为弹性上限，候选 600 字 / 800 字 / 500 字 / 1000 字。
- **Decision**：800 字。
- **Consequences**：好——覆盖 38 邻居 ~99%（max=668 / median=365），几乎所有历史文件裁未动；规则上线后立刻与实践对齐；保留 5 段结构语义约束（问题/根因/解法/验证方法/关联）。差——隐含"写长也行"宽松信号，可能让未来经验文件膨胀；缓解：INDEX.md 规则文本加一句"建议精简到 600 字内，800 字是软上限；超出考虑拆分到独立 reference 文件"。
- **时间**：2026-05-17

### D-010 F-E commit 顺序——同 PR 内 F-D commit → F-E commit

- **Context**：F-E 依赖 F-D 合入（INDEX.md 规则改完才能补节）。整批合一 PR 内 commit 顺序如何？
- **Decision**：F-D commit（INDEX.md 规则修订 + 兼容性 review 清单）在 F-E commit（test-assets-must-be-wired-into-ci.md 补节）之前。同 PR squash 后是单个 merged commit，但分批 cherry-pick 时序保留。
- **Consequences**：好——F-E 是 F-D 的可见证据，顺序符合阅读直觉；revert 时按 commit 反序可单独退 F-E。差——squash merge 后顺序信息丢失（develop 上看不到）；缓解：PR 正文 §变更摘要 段标注「F-D / F-E 顺序合入」。
- **时间**：2026-05-17
