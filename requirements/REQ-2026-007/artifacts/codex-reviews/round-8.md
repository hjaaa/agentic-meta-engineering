---
round: 8
triggered_at: "2026-05-05T18:40:43.073777+08:00"
triggered_commit: "a98d1e1"
review_id: "4227267461"
reviewer: "chatgpt-codex-connector[bot]"
submitted_at: "2026-05-05T10:45:01Z"
verdict: not_passed
state: COMMENTED
---


### 💡 Codex Review

Here are some automated review suggestions for this pull request.

**Reviewed commit:** `a98d1e129f`
    

<details> <summary>ℹ️ About Codex in GitHub</summary>
<br/>

[Your team has set up Codex to review pull requests in this repo](https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you
- Open a pull request for review
- Mark a draft as ready
- Comment "@codex review".

If Codex has suggestions, it will comment; otherwise it will react with 👍.




Codex can also answer questions or update the PR. Try commenting "@codex address that feedback".
            
</details>

---

## 自举价值 + 修复落地（手工补注，2026-05-05 18:50）

| Finding | Severity | 文件:行 | 问题 | 修复 |
|---|---|---|---|---|
| F-14 | P2 | `ahead_of_origin.py:125` | `head={owner}:{branch}` 直接字符串插值，branch 名含 `&`/`#`/`+` 等保留字符破坏 query string | 引入 `urllib.parse.quote(..., safe="")` 对 `owner:branch` 做 percent-encoding（`:` → %3A，`/` → %2F，`&` → %26，`+` → %2B） |
| F-15 | P2 | `ahead_of_origin.py:128` owner 缺失退化路径 | `head={branch}` 不符合 GitHub API 文档的 `user:ref-name`/`org:ref-name` 格式，结果不可靠 | owner 缺失 → 直接返 None（不 skip）让主路径处理；语义保守，宁可不 skip 也不假命中 |

新增 2 条回归 pytest（保留 round-7 的 2 条 + 改造 round-7 的 1 条 → 共 5 条）：

- `test_pr_lookup_uses_gh_api_with_owner_scoped_head`（改写）：断言 endpoint 必须含 URL-encoded `head=owner%3Abranch`
- `test_pr_lookup_returns_none_when_owner_unknown`：owner 缺失时不 skip + 不调 gh api
- `test_pr_lookup_url_encodes_special_chars_in_branch`：分支名含 `&`/`+`/`/` 必须编码为 %26/%2B/%2F

全量回归 **596 passed / 0 failed / 8 skipped**。

**累计 round-1..8 自举闭环：15 finding（8 P1 + 7 P2）全 fix + 20 条净新增回归 pytest**。

观察：F-13/F-14/F-15 都聚焦在同一段 `_pr_open_for_branch` 的 GitHub API 调用上，演化到 round-8 后这段代码已经收敛到「URL-encoded gh api + paginate + owner-scoped head + 空响应处理」这一稳态。下一轮期望转向其他文件的 finding（或终于通过）。

