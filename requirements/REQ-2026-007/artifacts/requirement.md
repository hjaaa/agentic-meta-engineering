---
id: REQ-2026-007
title: submit Codex review-loop + archive 命令
created_at: 2026-05-04T19:30:00+08:00
refs-requirement: true   # 供 traceability-gate-checker 识别
---

# REQ-2026-007 · submit Codex review-loop + archive 命令

## 背景

需求生命周期当前在「PR 阶段」与「PR 合并后」存在两段流程断裂：

1. **PR 阶段**：`/requirement:submit` 推完 PR 后没有命令承接「触发 codex review → 等响应 → 拉评论 → 据评论调整」的循环。本次会话开始时手工跑了两个后台 polling shell（PID 39042 / 48949）轮询 `gh pr checks` 和 PR reviews，被用户停掉——这就是缺命令承接的现场证据（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:23）。
2. **PR 合并后**：phase 切到 `completed` / 经验沉淀 / 删本地分支全是手工三步。最近 commit `e5cd6e0`（`chore(req-2026-006): finalize phase=completed (post #54 merge)`）和 `9c3743d`（`chore(experience): 沉淀 REQ-2026-006 复盘 4 条到 context/team/experience/`）就是手工版（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:26）。

附带 3 个具体痛点：

3. submit 门禁 GATE-AHEAD-OF-ORIGIN「本地有领先 origin 的 commit」是死规则——只想刷 PR 正文 / 重发 `@codex review` 的场景被卡住（来源：scripts/gates/registry.yaml:314）。
4. submit 门禁 GATE-REVIEW-VERDICT「review verdict 必须存在」对 `--draft` 草稿 PR 也强制——草稿 PR 还没跑过 `/code-review` 就先开起来跑 CI 的场景被卡住（来源：scripts/gates/registry.yaml:136）。
5. `phase-rules.md` 8 阶段表里没列 `completed`，只在合法切换链里出现——文档自相矛盾（8 阶段表起始来源：.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md:4；切换链来源：.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md:22）。

本需求的设计已审定并落到 spec：`context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md`（下文简称 **spec**）。本需求是**实施这份 spec**。

## 目标

- **主目标**：把 PR 阶段与 PR 合并后两段断裂闭环——一条 `submit --codex` 走完「推 PR → 触发 codex review → 落地评论 → 通过判定」单轮循环；一条 `/requirement:archive` 走完「校验 merge → phase=completed + archived_at → 询问经验沉淀 → 询问删本地+远程分支」（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:29）
- **次要目标**：顺手放宽两条不合理的 submit 门禁（GATE-AHEAD-OF-ORIGIN 在同分支已有 open PR 时 skip；GATE-REVIEW-VERDICT 在 `--draft` 模式 skip）（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:57），并补齐 phase-rules.md 第 9 阶段 `completed` 的文档一致性（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:258）

## 用户场景

### 场景 1：submit --codex 单轮循环（场景核心）

- **角色**：主对话 Agent（用户操控）
- **前置**：当前在 `feat/req-XXX` 分支、phase ∈ {`development`, `testing`}、本地有未推 commit、gh 已登录、PR 已存在或将由本次创建
- **主流程**：
  1. 用户：`/requirement:submit --codex`
  2. Skill 执行既有 submit 7 步（rebase / push / 渲染 PR 正文 / 创建或更新 PR）
  3. 记录 `trigger_at = now()`
  4. `gh pr comment <num> --body "@codex review"`，process.txt 写 `codex-review-triggered round=<N> pr=#<num>`
  5. 每 `--codex-poll-interval`（默认 15s）轮询 `gh api repos/<owner>/<repo>/pulls/<num>/reviews`，找首个满足 `submitted_at > trigger_at && /codex/i.test(user.login)` 的 review；总超时 `--codex-timeout`（默认 600s）
  6. 命中 → 落到 `requirements/<id>/artifacts/codex-reviews/round-<N>.md`（frontmatter：round / triggered_at / review_id / reviewer / submitted_at / verdict / state）
  7. 判定 body 是否包含精确字符串 `Didn't find any major issues.`
- **期望结果**：
  - 通过 → 退出 0，stderr：`codex-review: passed (round=N)`，process.txt 写 `verdict=passed`
  - 未通过 → 退出 0（带 ⚠️），stderr：`codex-review: not_passed (round=N), see artifacts/codex-reviews/round-N.md`，并把 review 摘要打给主对话；process.txt 写 `verdict=not_passed`
  - 超时 → 退出 0（带 ⚠️），stderr：`codex-review: timeout after <s>s, retry: /requirement:submit --codex`；process.txt 写 `verdict=timeout`
（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:94）

### 场景 2：submit 门禁放宽——刷 PR 正文场景

- **角色**：主对话 Agent
- **前置**：同分支已有 open PR，本地与 origin 同步（无领先 commit），但 `meta.yaml` / `features.json` / review 报告有更新需要刷到 PR 正文
- **主流程**：用户跑 `/requirement:submit`（无 `--codex`）→ Skill 检测到同分支 open PR 存在 → GATE-AHEAD-OF-ORIGIN skip（log `gate skipped: pr_open_for_branch`）→ 走 `gh pr edit --body-file <rendered>` 幂等更新
- **期望结果**：PR 正文刷新成功，命令退出 0；不被现状的「本地有领先 origin」死规则拦下（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:59）

### 场景 3：submit --draft 跳过 review-verdict 门禁

- **角色**：主对话 Agent
- **前置**：phase = `development`，feature 还没跑过 `/code-review`，但用户想先开草稿 PR 跑 CI 看效果
- **主流程**：用户跑 `/requirement:submit --draft` → `gates/run.py --trigger=submit --draft` 把 GATE-REVIEW-VERDICT 移出当次执行集合（log `gate skipped: draft mode`）→ 其余 6 条 error gate 正常跑 → 通过即创建草稿 PR
- **期望结果**：草稿 PR 创建成功；CI 失败/通过结果可观察；后续转正前再跑 `/code-review` + `/requirement:submit`（不带 `--draft`）补 verdict 后才能脱草稿（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:77）

### 场景 4：archive 收尾闭环

- **角色**：主对话 Agent（用户操控）
- **前置**：PR 已 merged 到 develop / main；当前 phase ∈ {`testing`, `completed`}；工作目录 clean；`meta.yaml.pr_number` 存在
- **主流程**：
  1. 用户：`/requirement:archive`
  2. 4 项预检：phase 范围 / git clean / pr_number 存在 / `gh pr view <pr> --json state` = `MERGED`（除非 `--force`）
  3. 原子写 `meta.yaml`：`phase: completed`、`archived_at: <ISO8601 +08:00>`
  4. process.txt 追加 `archived (PR #<num> merged at <merged_at>)`
  5. 询问经验沉淀（除非 `--no-experience`）→ y 调用 `/knowledge:extract-experience` 传 REQ 路径，n / 默认跳过；失败降级为 `experience: failed (<err>)` 不阻塞
  6. 询问删本地分支（除非 `--keep-branch`）→ y 跑 `git branch -d <branch>`（不允许 `-D`）；squash merge 场景 git 会拒绝，透传原始 error
  7. 询问删远程分支（除非 `--keep-branch`）→ y 跑 `git push origin --delete <branch>`；远程已删折叠为 `already-deleted`；安全校验 `<branch> != base_branch` 拒绝删 develop / main
  8. 终端反馈五行：phase / archived_at / experience / local branch / remote branch
- **期望结果**：需求状态归档完成；list 默认从此不展示该需求；可选副作用按用户选择执行（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:186）

## 非功能需求

- **性能**：submit `--codex` 子模式总耗时 ≤ `--codex-timeout`（默认 600s）+ submit 既有耗时；轮询间隔最小 5s 防限流
- **兼容性**：
  - 既有 `/requirement:submit`（无 `--codex`）行为不变
  - 既有 7 条 submit gate 在不放宽条件不命中时行为不变
  - `phase = completed` 不可回退（rollback 命令拒绝目标 = completed）
  - 既有 8 个 `/requirement:*` 命令行为不变（仅 list 加 `--all` / `--phase`，默认隐藏 completed 是 behavior change，但符合用户预期）
- **安全/合规**：
  - archive 删远程分支前必须显式 y/N 确认 + 校验 `<branch> != base_branch`，禁止删 `develop` / `main` / `master`
  - archive 本地分支删除不允许 `-D` 强删
  - submit `--codex` 在 PR open 状态消失（被关闭/删除）时退出码 2 + 打印原因，不静默重试
  - codex review 通过判定为精确字符串匹配 `Didn't find any major issues.`，且要求 `user.login` 严格匹配 `/codex/i` 防其他 bot 误判（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:348）

## 验收标准

| ID | 验收点 | 来源 |
|---|---|---|
| V-01 | 沙盒 e2e：`REQ-2099-001` 跑 new → development → 推空白改动 → submit 各种参数组合 → archive 各种参数组合 → 清理；全程符合 context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:314 列出的 8 步行为 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:314 |
| V-02 | 单测：`tests/gates/test_ahead_of_origin.py` 加「同分支已有 open PR 时 skip」用例（mock `gh pr list`）通过 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:343 |
| V-03 | 单测：`tests/gates/test_review_verdict.py` 加「`--draft` 时 skip」用例通过 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:343 |
| V-04 | 单测：`tests/lifecycle/test_archive.py` 覆盖 4 个预检 × pass/fail + 三个副作用动作（experience / local branch / remote branch）的 yes / no / skipped / failed 路径 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:343 |
| V-05 | 单测：`tests/lifecycle/test_submit_codex.py` mock `gh pr comment` + `gh api reviews`，覆盖 passed / not_passed / timeout 三条退出路径 + round 编号自增 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:343 |
| V-06 | 回归：`python3 scripts/gates/run.py --trigger=submit --req=REQ-2026-001` 等历史需求 exit code 不变；REQ-2026-006 的 submit 流程能跑通 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:341 |
| V-07 | `phase-rules.md` 8 阶段表第 9 行 `completed` 已落地，与合法切换链一致；archived_at 字段语义说明完整 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:258 |
| V-08 | 自举：本需求自身用 `/requirement:archive` 归档完成，archived_at 写入，list 默认不再展示 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:341 后续动作 #6，行 380 |
| V-09 | codex review 通过用语集中在 `submit-rules.md` 的 `CODEX_PASS_PHRASE` 常量；用户改一行配置即可调整 | context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:359 风险表 + §10 修订 |

## 范围

- **包含**：
  - 新增 `.claude/commands/requirement/archive.md`（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:286）
  - 新增 `.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md`（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:286）
  - 修改 `.claude/commands/requirement/submit.md`：加 `--codex` / `--codex-poll-interval` / `--codex-timeout` 参数说明（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:296）
  - 修改 `.claude/commands/requirement/list.md`：加 `--all` / `--phase` 参数；默认过滤 phase=completed（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:296）
  - 修改 `.claude/skills/managing-requirement-lifecycle/SKILL.md`：子动作清单加 `archive`、意图映射表更新（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:296）
  - 修改 `.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md`：第 7.5 步 codex 子模式细则、门禁放宽逻辑、`CODEX_PASS_PHRASE` 常量定义（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:296）
  - 修改 `.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md`：8 阶段表加 #9 completed、切换链增补、archived_at 语义（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:296）
  - 修改 `scripts/gates/registry.yaml`：GATE-AHEAD-OF-ORIGIN / GATE-REVIEW-VERDICT 的 `applies_when`（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:296）
  - 修改 `scripts/gates/run.py`：加 `--draft` 参数透传 + `pr_open_for_branch` 谓词解释或等价 plugin 自处理（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:296）
  - 更新 `context/team/engineering-spec/specs/INDEX.md` 已挂入本 spec ✅（已落地，commit `31f21db`）
  - 单测套件 4 个文件（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:343）
- **不包含**：
  - archive 不迁移 `requirements/<id>/` 目录到 `archive/` 子目录（D-005，来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:348）
  - 不新增 `phase=archived` 状态，仅用 `archived_at` 字段标记（D-006，来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:348）
  - submit 命令内不做多轮 codex 自循环——多轮交主对话 Agent 推动（D-002，来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:348）
  - 不做 PR merged 后台自动检测进程（用户必须显式跑 archive）（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:348）
  - codex review 命中后不自动改代码——review 内容供主对话 Agent 决策（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:348）
  - 不做非 Codex bot 的兜底——`user.login` 严格匹配 `/codex/i` 防其他 bot 干扰（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:348）
  - 不在本需求里启用 `Automatically delete head branches` 仓库设置——这是仓库管理员动作，不属于代码改动范围

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| D-001 codex review-loop 与 submit 关系 | 集成进 submit / 拆独立命令 / 仅 submit 加 --kick-codex | **集成进 submit (`--codex` 子模式)** | 用户已确认；一条命令走完便于反复跑（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-002 命令内是否多轮自循环 | 单轮 / 多轮 / 自适应 | **单轮**（多轮交主对话 Agent 推动） | 简化超时模型，拒绝失控自循环（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-003 codex 通过判定方式 | review state=APPROVED / body 含关键字 / 该轮无 must-fix / 人判定 | **body 含精确字符串 `Didn't find any major issues.`** | 用户已确认；codex bot 当前固定用语（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-004 submit 门禁放宽实施方式 | applies_when 字段 / escape hatch | **applies_when 字段** | 「设计上不该挂」≠「强制绕过」，语义更准（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-005 archive 是否迁目录 | 不动 / 迁 archive/ / 二阶段 | **不动目录**，仅状态化 | 用户已确认；list 用 phase 过滤即可，最小改动面（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-006 是否新增 phase=archived | 加 / 不加 | **不加**，仅用 `archived_at` 字段 | 避免 phase 状态机膨胀；区分「完成但未归档」与「完成且归档」（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-007 archive 副作用动作 | 全自动 / 全问人 / 部分自动 | **全问人**（experience / local branch / remote branch 三问串行） | 经验沉淀是创造性动作不适合默认跑；删除分支风险高需显式确认（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-008 codex review 落地位置 | artifacts/codex-reviews/round-N.md / process.txt 内联 / .review-scope.json | **artifacts/codex-reviews/round-N.md** | 与既有 artifacts 风格一致，可追溯多轮调整原因（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-009 phase-rules.md completed 阶段 | 不补 / 补 | **补**（D-005 / D-006 都引用它，必须先存在） | 文档自身一致性修复（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:41） |
| D-010 archive 是否清远程分支 | 只清本地 / 也问远程 / --remote 显式启用 | **也问远程，默认 N 不勾选不删** | 用户已确认；本地+远程对称、默认保守（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:213） |

## 待澄清清单

1. **codex bot 的 `user.login` 实际值**（对应正文场景 1）：spec 假设 `/codex/i` 正则匹配可命中，但实际 bot 可能叫 `chatgpt-codex-connector[bot]` / `codex-bot[bot]` / `openai-codex[bot]` 之一。**建议**：detail-design 阶段实跑一次 `gh api repos/<owner>/<repo>/pulls/<num>/reviews` 抓真实 login 字段，落到 `submit-rules.md` 的 `CODEX_REVIEWER_LOGIN_PATTERN` 常量。

2. **`applies_when` schema 是否支持谓词扩展**（对应 V-02、范围列里的 `scripts/gates/run.py`）：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:59 提到「若 `applies_when.requires` 当前 schema 不支持谓词表达式，作为 F-001 子任务一并扩展。最小变更优先：可改成 plugin 内自处理」（来源：context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:75）。**建议**：detail-design 阶段先看 `scripts/gates/registry.py` 的 `applies_when` 实现，确认采用方案 A（schema 扩展）还是方案 B（plugin 内自处理）。

3. **本 REQ 的 `feature_area`**（meta.yaml 语义组待补）：候选 `requirement-lifecycle` / `gate-system` / `cli-tooling`。本需求横跨「需求生命周期管理（archive 命令）」「门禁系统（submit 门禁放宽）」两块，建议主标 `requirement-lifecycle`，affected_modules 列两者。**建议**：detail-design 前由用户确认 feature_area 主标（项目 `areas.yaml` 白名单需要先确认）。

4. **squash merge 场景下 archive 删本地分支的策略**（对应场景 4 步骤 6）：squash merge 后本地分支会被 git 判为「未合并」，`git branch -d` 会拒绝。context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md:213 的处理是「透传原始 error 提示用户手工处理」。**建议**：detail-design 阶段确认这个体验是否够用，或在 archive 命令里检测 squash merge 场景给出更友好提示（如建议用户先 `git fetch && git reset --hard origin/<base>`）。
