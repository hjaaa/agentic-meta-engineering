# `/requirement:submit` 执行规则

## Codex Review 三常量（F-004，唯一事实源）

| 常量名 | 值 | 用途 |
|---|---|---|
| `CODEX_PASS_PHRASE` | `"Didn't find any major issues."` | codex review 通过判定：body 精确包含此串 → verdict=passed |
| `CODEX_REVIEWER_LOGIN_PATTERN` | `/codex/i` | review 命中过滤：login 匹配此正则（大小写不敏感） |
| `CODEX_REVIEWER_USER_TYPE` | `Bot` | review 命中过滤：user.type 必须为 Bot |

> `scripts/lib/submit_codex.py` 的 `_PASS_PHRASE` 从 `CODEX_PASS_PHRASE` 派生（运行时拼合，V-09 grep 唯一点在此处）。

`submit` 是在 `development` 或 `testing` 阶段内部的一次"推分支 + 开 PR"动作，**不改变 phase**。设计意图：把需求 artifacts 沉淀出的信息自动灌到 PR 正文，并把 PR 元数据回写到 `meta.yaml`。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--draft` | false | 开草稿 PR |
| `--target <branch>` | 自动推断 | 覆盖 PR base |
| `--skip-rebase` | false | 跳过 rebase（冲突时用户手动处理后重跑） |
| `--reviewer <user>` | — | 可多次，追加 reviewer |
| `--force-with-blockers` | false | 允许在有 blocker 级审查问题时仍开 PR（需显式） |

## 步骤

### 1. 解析目标分支（base）

按优先级取第一个可用：

1. `--target` 参数
2. `meta.yaml.base_branch`
3. `origin/develop` 存在 → `develop`
4. 兜底 `main`

### 2. 前置门禁

全部通过方可继续。统一调度入口（F-003 H3 改造后唯一通道）：

```bash
python scripts/gates/run.py --trigger=submit --req=<id>
```

具体 gate 由 `scripts/gates/registry.yaml` 定义（与 `phase-transition` 同源 + 多出 `GATE-PR-MERGED-STATE` 等 submit-only gate）；渲染产物与失败处置见 `gate-checklist.md`（F-004 落地）。任一失败立即终止，不污染任何文件。

### 3. 同步 base

- `git fetch origin <base>`
- 非 `--skip-rebase`：`git rebase origin/<base>`
- 冲突 → 打印冲突文件清单 + 提示 `rebase --continue` 后重跑 submit。**不**自动写 meta.yaml。

### 4. 推送

```bash
git push -u origin <branch>
```

若 push 被远端保护规则拒绝（如缺少 reviewer / 缺少 CI 通过），按原始 error 提示用户处理，不 swallow。

### 5. 构建 PR 正文

- 渲染 `templates/pr-body.md.tmpl`，占位符来源：

| 占位符 | 来源 |
|---|---|
| `__REQ_ID__` | `meta.yaml.id` |
| `__REQ_TITLE__` | `meta.yaml.title` |
| `__PHASE__` | `meta.yaml.phase` |
| `__FEATURES_SUMMARY__` | `artifacts/features.json` 里 `status=done` 的每条一行 |
| `__SERVICES__` | `meta.yaml.services`，join `, ` |
| `__FILES_STAT__` | `git diff --stat origin/<base>..HEAD` |
| `__TEST_STRATEGY__` | `artifacts/detailed-design.md` 的"测试策略"段（读不到则填 `见详细设计`） |
| `__REVIEW_REPORTS__` | `artifacts/review-*.md` 相对路径列表（由 `/code-review` 命令产出） |
| `__RISK__` | `artifacts/requirement.md` 的"风险/回滚"段（读不到则填 `无已知风险`） |

### 6. 推断 PR 标题

- 主 type 从 `features.json` 的 type 字段聚合：
  - 全 feat → `feat`
  - 全 fix → `fix`
  - 混合 → `feat`（主）
- scope = `meta.yaml.id`（如 `req-2026-042`）
- title 格式：`<type>(<scope>): <meta.yaml.title>`

### 7. 开 PR / 更新 PR

- 先检查是否已存在同分支 PR：`gh pr list --head <branch> --state open --json number,url`
- 若存在：`gh pr edit <num> --body-file <rendered>`（幂等更新）
- 若不存在：`gh pr create --base <base> --title "..." --body-file <rendered> [--draft] [--reviewer ...]`

### 8. 回写 meta.yaml

原子写入（先写临时文件再 mv）：

```yaml
pr_url: https://github.com/.../pull/<num>
pr_number: <num>
```

### 9. 记录 process.txt

追加一行：

```
[YYYY-MM-DD HH:MM:SS] submitted PR #<num> → <base> (<url>)
```

### 10. 终端反馈

```
✅ PR #<num>: <url>
   base:     <base>
   title:    <title>
   phase:    <phase>（未变更）
   reviewers: @<list>
```

### 11. CI 等待与判定（默认开启）

PR 开启 / 更新成功后，必须等待该 PR 关联的 GitHub Actions 状态稳定再进入 codex review-loop 或终态汇报。

**轮询命令**（Bash 工具调用）：

```bash
gh pr checks <num> --json name,status,conclusion,bucket
```

**轮询节奏与终止条件**：

- 间隔：`--ci-poll-interval`，默认 15s
- 总超时：`--ci-timeout`，默认 600s
- 终止条件：所有 check 的 `status == "COMPLETED"`（无 PENDING / IN_PROGRESS / QUEUED）

**判定矩阵**：

| 全部 check 终态 | 行为 |
|---|---|
| 全部 SUCCESS | step 11 通过；若 `--codex` 同传则进入 §7.5 状态机；否则进入 step 12 终端反馈 |
| 任一 FAILURE / CANCELLED / TIMED_OUT | exit 1，stderr 列出失败 check 名 + `gh run view <runId> --log-failed` 提示；**不**继续 codex；process.txt 追加 `[ci-failed]` 事件 |
| 全部 NEUTRAL / SKIPPED | 视为通过（无错误信号），警告并放行 |
| 总超时未稳定 | exit 0，stderr `⚠️ CI did not stabilize within <timeout>s`；process.txt 追加 `[ci-timeout]` 事件；**不**继续 codex（避免对未知质量 PR 触发 review） |
| `--no-ci-wait` 传入 | 跳过 step 11 的 CI 等待**但仍要求 codex 进入前 CI 状态为 SUCCESS**（codex 仍走 §7.5；CI 红或未跑时 `--no-ci-wait` 不放行 codex，等同 CI failed 路径 exit 1）；仅用于已知 CI 配置缺失场景以加速终态反馈 |

**硬约束（2026-05-21 强化）**：

> Codex review-loop 的前置条件是 **PR CI 已全绿**（或 NEUTRAL/SKIPPED）。
> 无论传不传 `--no-ci-wait`，**进入 §7.5 状态机前 runner 必须显式查询 `gh pr checks <num>` 一次**：
> - 任一 check `conclusion=FAILURE/CANCELLED/TIMED_OUT` → 拒绝进入 codex，exit 1
> - 任一 check `status != COMPLETED` 且未传 `--no-ci-wait` → 进入轮询等待
> - 任一 check `status != COMPLETED` 且传了 `--no-ci-wait` → 视为"未稳定"，拒绝进入 codex，exit 0 + warning
>
> 这条约束的存在理由：codex review 是稀缺成本（每次都消耗注意力 + bot 配额），
> 对 CI 都跑不绿的 PR 触发 review 等于把 reviewer 拉进无效会话。`--no-ci-wait` 的
> 设计意图是"我已经在 GitHub Web 端确认 CI 绿了，跳过本地等待"，不是"无视 CI 强冲"。

**process.txt 事件**：

```
[YYYY-MM-DD HH:MM:SS] [ci-passed] PR #<num> all checks green: <name1>,<name2>,...
[YYYY-MM-DD HH:MM:SS] [ci-failed] PR #<num> failed: <name>=<conclusion> (run <runId>)
[YYYY-MM-DD HH:MM:SS] [ci-timeout] PR #<num> CI not stable within <timeout>s
```

**为什么阻塞 codex**：codex review 在 CI 红灯时跑很容易把 reviewer 注意力引到无效的 PR 上，而 CI 错误（lint / format / type）通常 1-2 分钟可修；先 CI 绿后再 review-loop 投资回报率更高。

### 12. 终端反馈（含 CI 状态）

```
✅ PR #<num>: <url>
   base:     <base>
   title:    <title>
   phase:    <phase>（未变更）
   reviewers: @<list>
   CI:       <all-green | failed: ... | timeout>
```

## 失败处理矩阵

| 场景 | 行为 |
|---|---|
| 门禁任一项失败 | 打印缺口清单，不改任何文件，退出 1 |
| rebase 冲突 | 提示冲突文件 + 恢复命令（`git rebase --abort` / `--continue`），退出 1 |
| `gh` 未安装 | 打印安装链接 + 等价 `gh pr create` 命令供用户手动跑，退出 1 |
| `gh` 未登录 | 提示 `gh auth login`，退出 1 |
| 存在 blocker 级审查问题 | 默认阻止；`--force-with-blockers` 显式放行，同时在 PR 正文顶部加 `⚠️ 含未解决 blocker` |
| 同分支 PR 已合并 | 阻止（不能向已合并的 PR push 新 commit），提示用户切分支或改基点 |
| CI 任一 check 失败 | exit 1，列出失败 check + `gh run view --log-failed` 提示，不进 codex |
| CI 超时未稳定 | exit 0 + warning，不进 codex，由用户手工裁决重跑 |

## 和追溯链的关系

`submit` **不**调用 `traceability-gate-checker`。追溯链是 `development → testing` 的硬门禁，PR 开出时代码可能还在补单测；submit 只要求"已有 review 报告且无 blocker"即可。PR 合并后再由 `/workflow:next [F-012 待落地]` 驱动追溯链校验。

## §7.5 `--codex` 子模式状态机（F-004，默认翻转 2026-05-21）

**默认行为变更（2026-05-21）**：

`/requirement:submit` 包装层（slash command / SKILL）**默认会向底层 `scripts/lib/submit_codex.py`
CLI 追加 `--codex`**，进入 codex review-loop。仅当用户显式传 `--no-codex` 时跳过。

> 底层 `submit_codex.py` 的 argparse `--codex` 仍是 opt-in flag（默认 False，CLI 向后兼容）；
> 默认翻转只发生在 wrapper（包装 skill / command）层。这避免破坏直接调用 Python CLI 的脚本。

**翻转理由**：实践中 codex review-loop 是发现合并前 critical 缺陷的关键防线，多次需求闭环表明
"忘记 --codex" 是引入 main 后回归的常见根因。默认开启降低人为遗漏成本；用 `--no-codex` 显式
跳过满足快速迭代 / 本地拒绝 codex 的边角场景。

**前置条件（自 step 11 起强制）**：进入 codex 状态机前必须完成 step 11 CI 等待，且判定为「全部 SUCCESS」或「全部 NEUTRAL/SKIPPED」；CI 失败或超时时禁止进入 codex（避免无效 review 噪声）。


### 参数

| 参数 | 默认（CLI 层 / wrapper 层） | 语义 |
|---|---|---|
| `--codex` | CLI: false / wrapper: **true** | 启用 codex 单轮 review-loop。wrapper 默认追加；用户显式传 `--codex` 也接受（幂等） |
| `--no-codex` | false | wrapper 专用：禁止 wrapper 追加 `--codex` 到底层调用；底层 CLI 不识别此 flag |
| `--codex-poll-interval` | 10 | 仅 codex 开启时生效（与 `--codex` 同传） |
| `--codex-timeout` | 600 | 同上 |

参数互斥：
- `--codex` 与 `--no-codex` 不能同传，否则 wrapper 报错 exit 1（stderr: `mutually exclusive`）
- `--codex-poll-interval` / `--codex-timeout` 必须与 `--codex` 同传，否则底层 CLI exit 1 并提示 `requires --codex`
- `--draft` 与 `--codex` 可同传

### 状态机骨架

```
[idle] --submit --codex--> [ci-precheck]
[ci-precheck] --all SUCCESS / NEUTRAL / SKIPPED--> [pr-opened/updated]
[ci-precheck] --any FAILURE--> exit 1 (stderr ❌ CI failed; codex skipped)
[ci-precheck] --pending + --no-ci-wait--> exit 0 (stderr ⚠️ CI not stable; codex skipped)
[ci-precheck] --pending + 无 --no-ci-wait--> [ci-wait-loop] → [pr-opened/updated]
[pr-opened/updated] --post @codex review (含 PR body 阅读指令)--> [poll-loop]
[poll-loop] --hit codex review--> [judge body]
[poll-loop] --elapsed > timeout--> [judge body verdict=timeout]
[poll-loop] --gh 429--> [judge body verdict=timeout]
[poll-loop] --gh 5xx x3--> [error-exit-1]
[judge body] --emit verdict--> [done]
[done] --verdict=passed--> exit 0 (silent stderr)
[done] --verdict=not_passed--> exit 0 (stderr ⚠️ codex review NOT passed)
[done] --verdict=timeout--> exit 0 (stderr ⚠️ codex review TIMEOUT)
[error-exit-1] --> exit 1 (stderr ❌ gh api repeated 5xx during poll; aborting)
```

### @codex review 触发评论模板（2026-05-21 新增硬约束）

**禁止** 只发裸的 `@codex review`。每次触发评论必须显式要求 codex 阅读 PR 正文，
否则 codex 默认只 review diff，遗漏正文中的"变更摘要 / 影响范围 / 风险与回滚 /
验证方式 / 追溯"等关键设计信息，导致 review 视角片面化。

固定模板（`scripts/lib/submit_codex.py` 维护为常量 `CODEX_REVIEW_TRIGGER_BODY`）：

```
@codex review

请在 review 前**先完整阅读本 PR 的正文（description）**，包含：
- 变更摘要：本期 feature/fix 列表与各自 acceptance
- 影响范围：services / 文件清单
- 验证方式：单测 / 门禁 / 真机回归结论
- 风险与回滚：已挂账的 follow-up / known limitations
- 追溯：需求 → 设计 → 任务 → review 的链路

再结合 diff 给出 review 意见。重点关注：
1. 实现是否完整覆盖正文中描述的 acceptance 与设计意图
2. 风险段提到的 follow-up 是否在本 PR 内承担/挂账清晰
3. 是否存在正文未提及的 silent 行为变更
```

实施要求：

- 每次 `submit_with_codex` 调用都使用同一模板字符串（grep 唯一点：`CODEX_REVIEW_TRIGGER_BODY` 常量定义）
- 模板不接受 ad-hoc 拼装（即使是同一开发者多次重跑）；语言版本只一份
- 模板更新需同步本规范文档 + 常量定义 + e2e 测试三处

review 全文留存于 GitHub PR review comments（`gh pr view <num> --comments` 可查），
本地仅记录一行 `[codex-review-received] verdict=<v> round=<N>` 到 `process.txt`。

### 异常文案

| 场景 | stderr | exit code |
|---|---|---|
| `gh pr comment` 失败 | `❌ failed to post @codex review comment: <gh error>` | 1 |
| 连续 3 次 5xx | `❌ gh api repeated 5xx during poll; aborting` | 1 |
| 429 限流 | 直接走 verdict=timeout（不重试），stderr 含 `⚠️ codex review TIMEOUT` | 0 |
| verdict=not_passed | `⚠️ codex review NOT passed ...` | 0 |
| verdict=timeout | `⚠️ codex review TIMEOUT ...` | 0 |

### 留痕策略（2026-05 改造：不再本地落盘）

codex review 的 finding 全文保留在 GitHub PR review comments（可通过 `gh pr view
<num> --comments` 或 PR Web UI 查看），本地不再生成 `codex-reviews/round-N.md`。

`submit_with_codex` 仅向 `requirements/<req_id>/process.txt` 追加一行：

```
[YYYY-MM-DD HH:MM:SS] [codex-review-received] verdict=<passed|not_passed|timeout> round=<N>
```

`round` 字段保留为兼容字段；由于本地不再有 `round-*.md` 文件可数，新一次 submit
--codex 总是 round=1（多轮区分仅靠 GitHub PR comments 的时间序）。

实现入口：`scripts/lib/submit_codex.py:submit_with_codex`。
