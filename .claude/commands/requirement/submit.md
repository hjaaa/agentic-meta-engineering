---
description: 提交当前需求的 PR——自动门禁、推分支、拼正文、开 PR、回写 meta.yaml（默认含 codex review-loop）
argument-hint: [--draft] [--target <branch>] [--skip-rebase] [--reviewer <user>]... [--force-with-blockers] [--no-codex]
---

> [DEPRECATION] /requirement:submit 已纳入 3 月兼容期（截至 2026-08-08）。
> 请改用：新引擎语义由 standard-8phase yaml 末端 pr-submit 节点承载（F-003）。
> 本次仍执行旧实现以保证兼容；Plan 6 自举验证通过 + 兼容期到期后将物理删除。
> 详见：context/team/engineering-spec/migration/2026-XX-runs-rename.md
>
> **例外保留说明（不转发到 /workflow:submit）**：保留旧实现 + flag 直传到旧 submit Skill；新引擎语义由 standard-8phase yaml 末端 pr-submit 节点承载。

## 用途

在 `development` 或 `testing` 阶段内部执行一次"推分支 + 开 PR"动作：

- 自动从 `meta.yaml` / `features.json` / 审查报告拼装 PR 正文
- 自动推断 PR base（develop 优先，兜底 main）
- PR 成功后回写 `meta.yaml.pr_url` / `pr_number`
- **不改变 phase**（PR 合并不代表测试完成）

## 预检（硬门禁，任一失败即终止）

1. 当前分支 = `meta.yaml.branch`
2. 当前 phase ∈ {`development`, `testing`}
3. `git status --porcelain` 为空
4. 本地有领先 origin 的 commit
5. `artifacts/review-*.md` 至少一份报告（由 `/code-review` 命令产出），无 `severity: blocker`（除非 `--force-with-blockers`）
6. `gh auth status` 成功
7. base 分支在远端可用

预检细则见 `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md`。

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--draft` | false | 开草稿 PR |
| `--target <branch>` | 自动 | 覆盖 PR base（优先级：参数 > `meta.yaml.base_branch` > develop > main） |
| `--skip-rebase` | false | 跳过 `git rebase origin/<base>`（冲突时手工处理后重跑 submit） |
| `--reviewer <user>` | — | 可多次，追加 reviewer |
| `--force-with-blockers` | false | 有 blocker 级审查问题时仍放行，正文顶部会加 ⚠️ 标记 |
| `--no-ci-wait` | false | 跳过 PR 开启后的 CI 等待（默认会等所有 check 完成才进入 codex / 收尾） |
| `--ci-poll-interval` | 15 | CI 状态轮询间隔秒数 |
| `--ci-timeout` | 600 | CI 等待总超时秒数（超时不阻塞退出，但禁止进入 codex review-loop） |
| `--codex` | **true（默认开启）** | 启用 codex 单轮 review-loop（开 PR → CI 绿 → @codex review → 轮询 → verdict 写 process.txt；review 全文仅留存于 GitHub PR comments，不在本地落盘）。**底层 `submit_codex.py` CLI 默认仍是 opt-in；包装层默认会追加 `--codex` 到底层调用**，除非用户在 `/requirement:submit` 命令行显式传 `--no-codex`。 |
| `--no-codex` | false | 跳过 codex review-loop（兼容快速迭代 / 已有外部 review 流程的场景）。包装层不会向底层调用追加 `--codex`。 |
| `--codex-poll-interval` | 10 | 轮询间隔秒数（仅 codex 开启时生效；底层调用仍需 `--codex` 同传作为合法性校验） |
| `--codex-timeout` | 600 | 整轮超时秒数（同上） |

**参数互斥**：
- `--codex` 与 `--no-codex` 不能同传，否则报错（互斥）
- 显式传 `--codex-poll-interval` / `--codex-timeout` 但同时传 `--no-codex` → 视为 `--no-codex` 主导（warning + 忽略 codex 参数）

**为何默认开 codex**：实践中 codex review-loop 是发现合并前 critical 缺陷的关键防线，多次需求闭环表明
"忘记 --codex" 是引入 main 后回归的常见根因。默认开启降低人为遗漏成本；走快速迭代或本地拒绝 codex 时用
`--no-codex` 显式关闭。

**`--codex` 异常文案**：

- step 11 CI 等待失败 / 超时 → 跳过 codex（不发 @codex review 评论），见 `reference/submit-rules.md §11`
- CI 绿后 `gh pr comment` 失败 → exit 1，stderr `❌ failed to post @codex review comment: <gh error>`
- `gh api` 连续 3 次 5xx → exit 1，stderr `❌ gh api repeated 5xx during poll; aborting`
- 429 限流 → 直接 verdict=timeout（不重试），exit 0

详细状态机与三常量定义见 `reference/submit-rules.md §7.5`；CI 等待与判定见 `§11`。

## PR 成功后的 worktree 保留

PR 开启成功后，当前开发分支所关联的 worktree（若存在）将被保留在 `.worktrees/` 目录下。

在 PR feedback 阶段，你仍可在该 worktree 内继续迭代代码。完成后用 `/requirement:archive` 触发自动清理（owner=workflow 的 worktree 才会被清理）；worktree retained at <meta.worktree.path>; use /requirement:archive to clean up.

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **submit** 流程，按 `reference/submit-rules.md` 执行：

1. 解析 base → 2. 门禁 → 3. rebase → 4. push → 5. 渲染 `templates/pr-body.md.tmpl` → 6. 推断标题 → 7. `gh pr create` 或 `gh pr edit`（幂等）→ 8. 回写 meta.yaml → 9. 追加 process.txt → 10. 中间反馈 → **11. CI 等待与判定**（默认开启；失败阻断 codex；详见 `reference/submit-rules.md §11`）→ 12. 终端汇报（含 CI 状态）

## 幂等性

同分支已有 open 状态的 PR 时，改用 `gh pr edit` 更新正文，不重复开新 PR。这意味着 `/requirement:submit` 可以**随时重跑**以刷新 PR 内容。

## 失败处理

- rebase 冲突：提示文件清单 + `git rebase --continue` / `--abort`，退出 1，**不**写 meta.yaml
- `gh` 未登录：提示 `gh auth login`，退出 1
- push 被远端保护规则拒绝：原样打印远端 error，不 swallow
- 同分支 PR 已合并：阻止（无法推新 commit）

完整失败矩阵见 `reference/submit-rules.md`。
