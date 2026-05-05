---
round: 6
triggered_at: "2026-05-05T18:22:07.973248+08:00"
triggered_commit: "4555802"
review_id: "4227157500"
reviewer: "chatgpt-codex-connector[bot]"
submitted_at: "2026-05-05T10:26:00Z"
verdict: not_passed
state: COMMENTED
---


### 💡 Codex Review

Here are some automated review suggestions for this pull request.

**Reviewed commit:** `4555802056`
    

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

## 自举价值 + 修复落地（手工补注，2026-05-05 18:30）

本轮 codex 揪出我在 round-5 修 F-11 时引入的回归——典型「修一个引一个」反模式：

| Finding | Severity | 文件:行 | 问题 | 修复 |
|---|---|---|---|---|
| F-12 | **P1** | `ahead_of_origin.py:124` `_pr_open_for_branch` | round-5 把 `--head` 改成 `OWNER:BRANCH`，但 `gh pr list --head` 不支持该语法（manual 明确写 `":" syntax not supported`），实测命中永远空 → precheck 不再 skip → submit 重跑被错误拦下 R-NOTHING-TO-PUSH | `--head` 回退到分支名（gh-supported 语法）；同时 `--json` 加 `headRepositoryOwner`，结果用 owner 后过滤限定本仓库 |

新增 3 条回归 pytest 替换 round-5 的 2 条旧用例：

- `test_pr_lookup_uses_branch_only_head_and_filters_by_owner`：断言 `--head` 不含冒号 + `--json` 含 `headRepositoryOwner` + 本 owner PR 命中 skip + fork PR 被过滤
- `test_pr_lookup_no_skip_when_only_fork_has_open_pr`：fork 有 PR、本 owner 没有 → 不 skip（保 F-11 修复语义）
- `test_pr_lookup_falls_back_to_no_filter_when_owner_unknown`：owner 读不到时不过滤，保旧行为

全量回归 **595 passed / 0 failed / 8 skipped**。

**累计 round-1..6 自举闭环：12 finding（8 P1 + 4 P2）全 fix + 19 条净新增回归 pytest**。

**反思**：F-12 是修 F-11 时引入的真实回归，再次证明 review-loop 的边际价值——不仅能挖出新缺陷，还能护送修复本身的正确性。

