# AI bot 行为契约 vs 文档承诺不一致——pass 信号常落在文档外的 channel

**沉淀原因**：跨需求会重复（A）+ AI 反复忽略（B）+ 跨会话需保留（C）

## 问题

REQ-2026-007 的 codex review-loop round-9：脚本报 `verdict=timeout`，但实际 codex 在窗口期内已通过——只是回执发到了**文档没承诺的 channel**。

codex info 文本明确说：

> If Codex has suggestions, it will comment; otherwise it will react with 👍.

实测 round-9：codex 既没 react 👍，也没发 PR review，而是发了一条 issue comment（body：`Codex Review: Didn't find any major issues. Already looking forward to the next diff.`）。

我们的 `_poll_codex` 只查 `repos/.../pulls/{n}/reviews` 端点 → 漏掉 issue comment → verdict 假阴 timeout → review-loop 错误地继续。直到人工核对 `gh api repos/.../pulls/57/comments` 才发现真实 pass 信号。

## 根因

AI bot 的回执机制在迭代过程中会扩展（review / inline comment / issue comment / reaction / 文档外的新机制），而 info 文本是**某个版本的快照**。集成层基于"文档承诺的单一 channel"实现就会错过其他 channel。

这不是 bot 的 bug，是 **bot 对集成方的"行为契约漂移"**——文档说有 `{review, reaction}` 两条，实际 channel 集是 `{review, inline_comment, issue_comment, reaction, ...}` 的超集。

## 解法

**不能信 bot 自我描述的 channel 列表**——必须 dogfooding 实测每条 channel：

- pass 信号的轮询用 **多端点 OR 语义**：reviews ∪ issue_comments ∪ reactions，任一命中即视为通过
- bot 的输出 schema 也可能漂移（字段名 / 时区格式 / `created_at` vs `submitted_at`），把判定逻辑 helper 化（如 `_is_passed`、`_normalize_issue_comment_to_review`），便于以后改一行
- 集成层把多 channel candidates 合并后按 `submitted_at` 取最新，避免锁定到旧 channel 的过时结论

**接入清单**——每次新接入 AI bot 集成时，先开测试 PR 走完三场景并记录 channel 实际位置：

| 场景 | 期望 channel | 实测 channel | body 字段 |
|---|---|---|---|
| has-finding（review） | PR review | ✓ | `state=COMMENTED` + `body` + inline comments |
| no-finding（pass） | reaction 👍 / review | ⚠️ 实际是 issue comment | `body` 含特定 phrase |
| timeout | （无） | （无） | — |

每条 channel 至少 1 条断言型测试覆盖。

## 验证方法

整合 AI bot 后，在沙盒 PR 上手工触发三场景：

```bash
# has-finding
gh pr comment <pr> --body "@codex review"  # 触发，等 codex 回 review
# no-finding
git push <fix>; gh pr comment <pr> --body "@codex review"  # 等 codex 回 issue comment
# 记录每种实际 channel + body 格式
gh api repos/{owner}/{repo}/pulls/<pr>/reviews
gh api repos/{owner}/{repo}/issues/<pr>/comments
```

把实测结果写入 implementation 注释 + 至少 1 条断言型测试覆盖每条 channel。

## 引用来源

- `requirements/REQ-2026-007/artifacts/codex-reviews/round-9.md`（verdict 修订 timeout → passed）
- F-16 fix commit `abdd3a9`：`_gh_pr_issue_comments` + `_normalize_issue_comment_to_review` + 双端点 poll
- 关联经验：`external-ai-reviewer-finds-internal-blindspots.md`（codex 互补价值）
