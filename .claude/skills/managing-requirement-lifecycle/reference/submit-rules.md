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
| `--no-ci-wait` 传入 | 跳过整个 step 11，直接进入 codex / step 12（不推荐，仅用于已知 CI 配置缺失的边角场景） |

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

## §7.5 `--codex` 子模式状态机（F-004）

**前置条件（自 step 11 起强制）**：进入 codex 状态机前必须完成 step 11 CI 等待，且判定为「全部 SUCCESS」或「全部 NEUTRAL/SKIPPED」；CI 失败或超时时禁止进入 codex（避免无效 review 噪声）。


### 参数

| 参数 | 默认 | 语义 |
|---|---|---|
| `--codex` | false | 启用 codex 单轮 review-loop |
| `--codex-poll-interval` | 10 | （需 `--codex`）轮询间隔秒数 |
| `--codex-timeout` | 600 | （需 `--codex`）整轮超时秒数 |

参数互斥：`--codex-poll-interval` / `--codex-timeout` 必须与 `--codex` 同传，否则 exit 1 并提示 `requires --codex`；`--draft` 与 `--codex` 可同传。

### 状态机骨架

```
[idle] --submit --codex--> [pr-opened/updated]
[pr-opened/updated] --post @codex review--> [poll-loop]
[poll-loop] --hit codex review--> [persist round-N.md]
[poll-loop] --elapsed > timeout--> [persist round-N.md verdict=timeout]
[poll-loop] --gh 429--> [persist round-N.md verdict=timeout]
[poll-loop] --gh 5xx x3--> [error-exit-1]
[persist round-N.md] --judge body--> [done]
[done] --verdict=passed--> exit 0 (silent stderr)
[done] --verdict=not_passed--> exit 0 (stderr ⚠️ codex review NOT passed)
[done] --verdict=timeout--> exit 0 (stderr ⚠️ codex review TIMEOUT)
[error-exit-1] --> exit 1 (stderr ❌ gh api repeated 5xx during poll; aborting)
```

### 异常文案

| 场景 | stderr | exit code |
|---|---|---|
| `gh pr comment` 失败 | `❌ failed to post @codex review comment: <gh error>` | 1 |
| 连续 3 次 5xx | `❌ gh api repeated 5xx during poll; aborting` | 1 |
| 429 限流 | 直接走 verdict=timeout（不重试），stderr 含 `⚠️ codex review TIMEOUT` | 0 |
| verdict=not_passed | `⚠️ codex review NOT passed ...` | 0 |
| verdict=timeout | `⚠️ codex review TIMEOUT ...` | 0 |

### round-N.md 落地路径

`requirements/<req_id>/artifacts/codex-reviews/round-N.md`

round 号 = 已有 `round-*.md` 数 + 1；timeout 时 frontmatter 仅 `round / triggered_at / verdict` 三字段必填，其他可省。

实现入口：`scripts/lib/submit_codex.py:submit_with_codex`。
