---
round: 9
triggered_at: "2026-05-05T18:48:50.670558+08:00"
triggered_commit: "1cb8417"
review_id: "4378572117"
reviewer: "chatgpt-codex-connector[bot]"
submitted_at: "2026-05-05T10:53:52Z"
verdict: passed
state: COMMENTED
revised: true
revised_at: "2026-05-05T19:05:00+08:00"
revised_reason: "submit_codex.py F-16 bug——只查 PR reviews 端点，漏掉 codex 在「无 finding」时发的 issue comment（含 pass phrase）。人工核对 gh api issues/57/comments 后改为 passed"
---

## 修订说明

第一轮 round-9 跑 `submit_codex.py` 报 `verdict=timeout`，但实际 codex 在窗口期内（10:53:52Z = 18:53:52 +08:00，距 triggered_at 仅 5 分钟）已回评「Codex Review: Didn't find any major issues. Already looking forward to the next diff.」——这是 **review-loop 的真实 pass 信号**。

漏判的根因恰好是 codex 自己的 round-9 P1 finding F-16：

> Codex 在「无 finding」时不发 PR review，而是发 issue comment 带 pass phrase。
> 旧 `_poll_codex` 只查 `repos/.../pulls/{n}/reviews` 端点，会错过 issue
> comment → 假阴 verdict=timeout。

## 真实 codex 回评摘要（issue comment id 4378572117）

```
Codex Review: Didn't find any major issues. Already looking forward to the next diff.

[Your team has set up Codex to review pull requests in this repo](https://chatgpt.com/codex/cloud/settings/general).
Reviews are triggered when you
- Open a pull request for review
- Mark a draft as ready
- Comment "@codex review".

If Codex has suggestions, it will comment; otherwise it will react with 👍.
...
```

注意 codex info 文案与实测行为不一致——「otherwise it will react with 👍」实际是「发一条 issue comment」。我们的 `_is_passed` 子串匹配把 `Didn't find any major issues.` 命中即可视为 pass。

## 修复落地（F-16）

| 项 | 实现 |
|---|---|
| 新增 `_gh_pr_issue_comments(pr_number)` | 拉 `repos/{owner}/{repo}/issues/{n}/comments`，异常体系与 `_gh_pr_reviews` 同源（5xx → GhApi5xx，429 → GhApi429） |
| 新增 `_normalize_issue_comment_to_review(comment)` | 把 issue comment 的 `created_at` 复制到 `submitted_at`、塞 `_kind=comment`，与 review 同 dict shape，下游统一处理 |
| `_poll_codex` 改造 | 双端点同时查询 + 合并 candidates；`_pick_latest_review` 在 reviews + comments 上一起按 `submitted_at` 取最新，`_is_passed` 判定不变 |

## 累计闭环 + review-loop 终止

|  | 数量 |
|---|---|
| Codex round-1..9 总 finding | **16** (9 P1 + 7 P2) |
| 全部 fix | ✅ |
| 净新增回归 pytest | **25** |
| 全量 pytest | **601 passed / 0 failed / 8 skipped** |

按用户原始需求 §10 终止条件「review-loop 持续到 codex 不再提出新的 bug 之后才能结束」——**round-9 codex 回评 pass phrase = 终止信号**，本 PR 的 review-loop 正式收敛。

下一步：进 completed 阶段（按 phase-rules：testing → completed）。
