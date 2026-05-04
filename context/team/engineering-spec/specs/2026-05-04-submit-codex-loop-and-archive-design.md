# Submit 增强 Codex review-loop + 新增 Archive 命令 · 设计留档

**日期**：2026-05-04
**作者**：huangjian
**状态**：设计中
**关联需求**：REQ-2026-007
**关联文档**：
- `.claude/commands/requirement/submit.md`（待修改）
- `.claude/commands/requirement/archive.md`（新增）
- `.claude/skills/managing-requirement-lifecycle/SKILL.md`（伞形 Skill 入口）
- `.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md`（待修改）
- `.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md`（待补 `completed` 阶段）
- `scripts/gates/registry.yaml`（GATE-AHEAD-OF-ORIGIN / GATE-REVIEW-VERDICT 调整）

---

## 1. 背景与目标

### 1.1 现状痛点

| 痛点 | 现象 | 来源 |
|---|---|---|
| P-001 | submit 推完 PR 后，没有命令承接「触发 codex review → 等响应 → 拉评论」，全靠手工跑后台轮询脚本 | 本次会话停掉的两个后台 polling shell（PID 39042 / 48949）就是手工版 |
| P-002 | submit 「本地有领先 origin 的 commit」一条死规则——只想刷 PR 正文 / 重发 @codex review 的场景被卡住 | `scripts/gates/registry.yaml#GATE-AHEAD-OF-ORIGIN` |
| P-003 | submit 「review verdict 必须存在」对 `--draft` 草稿 PR 也强制——草稿 PR 还没跑过 `/code-review` 就先开起来跑 CI 的场景被卡住 | `scripts/gates/registry.yaml#GATE-REVIEW-VERDICT` |
| P-004 | PR merge 后没命令承接收尾——`phase=completed` / 经验沉淀 / 删本地分支全是手工三步 | 最近 commit `e5cd6e0` + `9c3743d` 就是手工版 |
| P-005 | `phase-rules.md` 8 阶段表里没列 `completed`，只在合法切换链里出现——文档不一致 | `phase-rules.md` 第 4-14 行 vs 第 22 行 |

### 1.2 目标

一次性闭环 PR 流程，包含三块联动改造：

1. **submit 门禁放宽**——P-002 / P-003
2. **submit `--codex` 子模式**——P-001（Codex review loop）
3. **`/requirement:archive` 新命令**——P-004 / P-005

不做：迁移目录、phase 状态机膨胀、PR merged 后台自动检测进程、命令内多轮自循环。

---

## 2. 关键设计决策（D-001 ~ D-009）

| 决策代号 | 内容摘要 | 落地位置 |
|---|---|---|
| D-001 | Codex review-loop 集成进 submit（一体），不拆独立命令 | submit `--codex` 子模式 |
| D-002 | 命令内**单轮**轮询；多轮交主对话 Agent 推动（用户改代码 → 再次 submit --codex） | 简化超时模型、拒绝失控自循环 |
| D-003 | Codex review 通过判定使用精确字符串匹配 `Didn't find any major issues.` | 用户已确认 |
| D-004 | submit 门禁放宽通过 `applies_when` 字段而非 escape hatch ——它是**设计上不该挂**而非**强制绕过** | `registry.yaml` |
| D-005 | archive 不动 `requirements/<id>/` 目录，仅状态化 | 用户已确认；list 默认过滤 |
| D-006 | 不新增 `phase=archived` 状态，仅用 `archived_at` 字段标记 | 避免 phase 状态机膨胀 |
| D-007 | archive 副作用动作（经验沉淀 / 删本地分支）都「问人」而非默认跑——降低误删风险 | 用户已确认 |
| D-008 | Codex review 落到 `artifacts/codex-reviews/round-N.md`——可追溯、便于回溯多轮调整原因 | 与既有 artifacts 风格一致 |
| D-009 | `phase-rules.md` 顺手补 `completed` 阶段——D-005 / D-006 都引用它，必须先存在 | 文档一致性修复 |

---

## 3. Submit 门禁放宽

### 3.1 GATE-AHEAD-OF-ORIGIN

**现状**（`scripts/gates/registry.yaml:314-`）：在 `submit` trigger 上无条件检查"本地是否有领先 origin 的 commit"。

**改造**：增加 `applies_when` 条件——同分支已有 open PR 时跳过此项。

```yaml
- id: GATE-AHEAD-OF-ORIGIN
  ...
  applies_when:
    requires:
      - "!pr_open_for_branch"   # 同分支无 open PR 时才检查
```

`!pr_open_for_branch` 是 `applies_when` plugin 解释器需要新增的条件谓词：调 `gh pr list --head <branch> --state open --json number` 判断结果是否为空数组。

> 实施细节：若 `applies_when.requires` 当前 schema 不支持谓词表达式，作为 F-001 子任务一并扩展。最小变更优先：可改成 plugin 内自处理（plugin 收到 trigger=submit 时检查 pr open 状态返回 `skip`）。

### 3.2 GATE-REVIEW-VERDICT

**现状**（`registry.yaml:136-`）：在 `submit` trigger 上必查 verdict 存在 + 无 blocker。

**改造**：`--draft` 模式跳过整条。

实施路径有两选：

| 方案 | 改动 | 备注 |
|---|---|---|
| A | submit 透传 `--draft` → `gates/run.py` → registry `applies_when` 增加 `pr_draft_mode` 上下文 | 字段化、对未来其他"draft 跳过"诉求可复用 |
| B | submit Skill 直接在 `--draft` 时不触发 `GATE-REVIEW-VERDICT` 调度 | 仅本场景；其他 trigger 不影响 |

**采用 B（最小变更）**：在 `gates/run.py` 的参数表加 `--draft`，draft=true 时把 `GATE-REVIEW-VERDICT` 移出当次执行集合（log 一行 `gate skipped: draft mode`）。

---

## 4. Submit `--codex` 子模式

### 4.1 CLI 形态

```
/requirement:submit [既有参数] [--codex] [--codex-poll-interval 15] [--codex-timeout 600]
```

| 参数 | 默认 | 语义 |
|---|---|---|
| `--codex` | false | 开启子模式（关时行为完全等同当前 submit） |
| `--codex-poll-interval` | 15s | 轮询间隔，最小 5s |
| `--codex-timeout` | 600s | 总轮询超时，超时后退出但不报错 |

### 4.2 执行流程（在现有 submit-rules.md 第 7 步「开/更新 PR」之后追加第 7.5 步）

```
推完 PR / 更新完 PR
   ↓
trigger_at = now()
   ↓
gh pr comment <num> --body "@codex review"
process.txt 追加：[ts] codex-review-triggered round=<N> pr=#<num>
   ↓
loop（每 interval 秒）：
  reviews = gh api repos/<owner>/<repo>/pulls/<num>/reviews
  hit = reviews.find(r =>
          r.submitted_at > trigger_at
          && /codex/i.test(r.user.login))
  break if hit or elapsed > timeout
   ↓
找到 codex review              超时
   ↓                            ↓
落地到 artifacts/codex-reviews/round-<N>.md
process.txt 追加 codex-review-received verdict=...
   ↓                            ↓
判定 body 是否包含 "Didn't find any major issues."
   ↓                            ↓
通过                           未通过
✅ 退出 0                      ⚠️ 退出 0（带警示标记）
                              打印 review 摘要给主对话
```

### 4.3 Round 编号 + 落地格式

`N = 已有 round-*.md 数 + 1`

```
requirements/<id>/artifacts/codex-reviews/
  round-1.md
  round-2.md
  ...
```

每个文件 frontmatter：

```yaml
---
round: 1
triggered_at: 2026-05-04T18:30:00+08:00
review_id: 1234567
reviewer: codex-bot[bot]
submitted_at: 2026-05-04T18:32:11+08:00
verdict: passed   # 或 not_passed | timeout
state: COMMENTED  # GitHub review state 原值
---

<review body 原文，markdown 直接落>
```

### 4.4 退出码 + stderr 关键串

| 情形 | 退出码 | stderr 关键串 |
|---|---|---|
| 子模式关闭（默认） | 沿用 submit 原有退出码 | — |
| Codex review 通过 | 0 | `codex-review: passed (round=N)` |
| Codex review 未通过 | 0 ⚠️ | `codex-review: not_passed (round=N), see artifacts/codex-reviews/round-N.md` |
| 轮询超时 | 0 ⚠️ | `codex-review: timeout after <s>s, retry: /requirement:submit --codex` |
| `gh pr comment` 失败 | 1 | gh 原始 error 透传 |
| trigger 后 PR 被关闭 / 删除 | 2 | `codex-review: pr #<num> not open during polling` |

> 注：未通过 / 超时都退出 0 是有意为之——主对话 Agent 不应被强制中断，应该接收摘要后决定下一步动作。

### 4.5 process.txt 新增事件类型

```
[YYYY-MM-DD HH:MM:SS] codex-review-triggered round=<N> pr=#<num>
[YYYY-MM-DD HH:MM:SS] codex-review-received round=<N> verdict=<passed|not_passed|timeout>
```

---

## 5. `/requirement:archive` 新命令

### 5.1 CLI 形态

```
/requirement:archive [--force] [--keep-branch] [--no-experience]
```

| 参数 | 默认 | 语义 |
|---|---|---|
| `--force` | false | 跳过 PR merged 校验（异常恢复，如手动合并） |
| `--keep-branch` | false | 跳过删本地分支提示 |
| `--no-experience` | false | 跳过经验沉淀提示 |

### 5.2 预检（硬门禁）

| # | 检查项 | 失败时 |
|---|---|---|
| 1 | 当前 phase ∈ {`testing`, `completed`} | 退出 1，提示当前 phase + 期望 |
| 2 | 工作目录 clean (`git status --porcelain` 为空) | 退出 1 |
| 3 | meta.yaml 有 `pr_number` 字段 | 退出 1，提示先跑 submit |
| 4 | `gh pr view <pr_number> --json state` = `MERGED`（除非 `--force`） | 退出 1，提示等 merge 或加 `--force` |

### 5.3 执行步骤

1. **更新 meta.yaml**（原子写：tmp + mv）：
   ```yaml
   phase: completed
   archived_at: 2026-05-04T19:30:00+08:00
   ```

2. **process.txt 追加**：
   ```
   [YYYY-MM-DD HH:MM:SS] archived (PR #<num> merged at <merged_at>)
   ```

3. **询问经验沉淀**（除非 `--no-experience`）：
   - 提示："是否沉淀经验到 `context/team/experience/`？(y/N)"
   - y → 调用 `/knowledge:extract-experience` 传当前 REQ 路径
   - n / 默认 → 跳过；不阻塞 archive 完成
   - 经验沉淀失败时：打印原始 error，archive 命令依然 exit 0（副作用动作降级）

4. **询问删除本地分支**（除非 `--keep-branch`）：
   - 提示："是否删除本地分支 `<branch>`？(y/N)"
   - y → `git branch -d <branch>`（safe delete，git 拒绝时透传 error）
   - n / 默认 → 跳过
   - 不能强删（不允许 `-D`）；分支没合并到 develop 时 git 自然拒绝

5. **终端反馈**：
   ```
   ✅ REQ-2026-XXX archived
      phase: completed
      archived_at: 2026-05-04T19:30:00+08:00
      experience captured: yes / no / skipped
      local branch:        deleted / kept / skipped / failed (<git error>)
   ```

### 5.4 委托

调用 Skill `managing-requirement-lifecycle` 的 **archive** 子动作，按 `reference/archive-rules.md` 执行（新增文档）。

### 5.5 与 list 命令的协同

`/requirement:list` 默认过滤 `phase = completed` 的项。
新增参数：`--all`（含 completed）/ `--phase <p>`（指定阶段）。

---

## 6. `phase-rules.md` 修复 `completed` 阶段（D-009）

### 6.1 8 阶段表加第 9 行

| # | 英文标识 | 中文名 | 做什么 |
|---|---|---|---|
| 9 | `completed` | 已完成 | PR 已合并 + archive 命令归档 + 可选经验沉淀 |

### 6.2 合法切换增补

```
... → testing → completed
```

- testing → completed 由 `/requirement:archive` 推进（不走 `/requirement:next`，因为 archive 有副作用动作）
- completed 状态**不可回退**（rollback 命令拒绝目标 = completed）

### 6.3 `archived_at` 字段语义

- 不存在 / null → "未归档"（即使 phase=completed 也算"完成但未归档"）
- ISO8601 + +08:00 → "已归档"，list 默认隐藏

> 区分意义：测试结束 + PR 合并后，phase 切换 + 归档可以**分开发生**，比如团队希望保留若干天用于复盘后再归档。

---

## 7. 影响文件清单

### 7.1 新增（2）

| 文件 | 内容 |
|---|---|
| `.claude/commands/requirement/archive.md` | archive 命令定义 + 参数 + 委托给 Skill |
| `.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md` | archive 执行细节、错误矩阵 |

### 7.2 修改（7）

| 文件 | 改动要点 |
|---|---|
| `.claude/commands/requirement/submit.md` | 加 `--codex` / `--codex-poll-interval` / `--codex-timeout` 参数；预检 4/5 调整说明 |
| `.claude/commands/requirement/list.md` | 加 `--all` / `--phase` 参数；默认过滤 completed |
| `.claude/skills/managing-requirement-lifecycle/SKILL.md` | 子动作清单加 `archive`；意图映射表更新 |
| `.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md` | 第 7.5 步 codex 子模式细则；门禁条件章节补放宽逻辑 |
| `.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md` | 8 阶段表加 #9 completed；切换链 + archived_at 语义 |
| `scripts/gates/registry.yaml` | GATE-AHEAD-OF-ORIGIN / GATE-REVIEW-VERDICT 的 `applies_when` |
| `scripts/gates/run.py` | 加 `--draft` 参数透传；`!pr_open_for_branch` 谓词或等价 plugin 自处理 |

### 7.3 INDEX 更新

- `context/team/engineering-spec/specs/INDEX.md` —— 列入本 spec
- `.claude/commands/requirement/`（如有 README/INDEX，需补 archive）

---

## 8. 验证策略

### 8.1 沙盒 e2e（按既有 REQ-2099-NNN 通道）

1. 跑 `/requirement:new` 创建 REQ-2099-001 → development 阶段
2. 推一个空白改动到 feat/req-2099-001
3. **submit 门禁放宽测试**：
   - `submit --draft`（验证 GATE-REVIEW-VERDICT 跳过）
   - submit 无新 commit、同分支已有 open PR 时再跑（验证 GATE-AHEAD-OF-ORIGIN 跳过）
4. **submit --codex 测试**：
   - submit --codex（让真实 codex 介入）→ 等结果
   - 验证 round-1.md 落地、frontmatter 字段、退出码、process.txt 事件
   - 故意让 review 不通过（构造 codex 会指出问题的代码）→ 验证 ⚠️ 摘要
   - 故意把 timeout 设小（如 30s）→ 验证 timeout 路径
5. merge PR
6. **archive 测试**：
   - `/requirement:archive` → phase=completed、archived_at、提示经验沉淀、提示删分支
   - `--no-experience` / `--keep-branch` 各跑一次
   - PR 未 merge 时跑（验证拦截）；加 `--force` 跑（验证放行）
7. `/requirement:list`（验证默认隐藏）；`--all`（验证可见）
8. 清理：`rm -r requirements/REQ-2099-001`

### 8.2 回归

- `python3 scripts/gates/run.py --trigger=submit --req=REQ-2026-001` 等历史需求不能挂掉
- 既有 REQ-2026-006 的 submit / archive 流程能走通

### 8.3 单测

- `tests/gates/test_ahead_of_origin.py` 新增"PR open 时 skip"用例
- `tests/gates/test_review_verdict.py` 新增"--draft skip"用例
- `tests/lifecycle/test_archive.py` 新增（4 个预检 × pass/fail + 副作用动作 mock）
- `tests/lifecycle/test_submit_codex.py` 新增（轮询 mock、verdict 解析、超时）

---

## 9. YAGNI 边界（明确不做）

- ❌ archive 不迁移 `requirements/<id>/` 目录（D-005）
- ❌ 不新增 `phase=archived` 状态（D-006）
- ❌ submit 命令内不做多轮 codex 自循环（D-002）
- ❌ 不做 PR merged 后台自动检测进程（用户必须显式跑 archive）
- ❌ codex review 命中后不自动改代码（review 内容供主对话 Agent 决策，不直接 patch）
- ❌ 不做 PR review 触发的非-Codex bot 兜底（用 `user.login` 严格匹配 `/codex/i` 规避其他 bot 干扰）

---

## 10. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Codex bot 修改通过用语 | 中 | review 永远判 not_passed，循环卡死 | 通过用语集中在 `submit-rules.md` 的 `CODEX_PASS_PHRASE` 常量；用户可改一行配置 |
| `gh pr review` 限流 | 低 | 轮询返回 429 | 退避策略：429 → 直接 timeout 退出，不重试 |
| `applies_when` 谓词扩展破坏既有 gate | 中 | 既有需求 submit 挂掉 | 预检 8.2 回归用例必须先跑 |
| archive `git branch -d` 删错分支 | 低 | 用户改动丢失 | safe delete only；交互问人；`--keep-branch` 兜底 |

回滚：把 spec 涉及的 9 个文件 `git revert` 即可（无破坏性数据迁移）。

---

## 11. 后续动作

1. ✅ 本 spec 落档
2. ⬜ 用户 review spec（pending）
3. ⬜ 写 implementation plan（spec 通过后调用 `superpowers:writing-plans` skill）
4. ⬜ 实施（按 plan 分 feature 推进，每 feature 走 `/code-review`）
5. ⬜ 沙盒 e2e（§8.1）
6. ⬜ archive 自身需求（自举）
