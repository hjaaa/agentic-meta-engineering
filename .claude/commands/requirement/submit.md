---
description: 提交当前需求的 PR——自动门禁、推分支、拼正文、开 PR、回写 meta.yaml
argument-hint: [--draft] [--target <branch>] [--skip-rebase] [--reviewer <user>]... [--force-with-blockers]
---

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
5. `artifacts/code-review-reports/` 存在至少一份报告，无 `severity: blocker`（除非 `--force-with-blockers`）
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

## 委托

调用 Skill `managing-requirement-lifecycle` 的 **submit** 流程，按 `reference/submit-rules.md` 执行：

1. 解析 base → 2. 门禁 → 3. rebase → 4. push → 5. 渲染 `templates/pr-body.md.tmpl` → 6. 推断标题 → 7. `gh pr create` 或 `gh pr edit`（幂等）→ 8. 回写 meta.yaml → 9. 追加 process.txt → 10. 终端汇报

## 幂等性

同分支已有 open 状态的 PR 时，改用 `gh pr edit` 更新正文，不重复开新 PR。这意味着 `/requirement:submit` 可以**随时重跑**以刷新 PR 内容。

## 失败处理

- rebase 冲突：提示文件清单 + `git rebase --continue` / `--abort`，退出 1，**不**写 meta.yaml
- `gh` 未登录：提示 `gh auth login`，退出 1
- push 被远端保护规则拒绝：原样打印远端 error，不 swallow
- 同分支 PR 已合并：阻止（无法推新 commit）

完整失败矩阵见 `reference/submit-rules.md`。
