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
