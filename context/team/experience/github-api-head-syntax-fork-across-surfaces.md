# GitHub API 同概念跨 surface 的语法分裂——`gh pr list --head` ≠ `gh api .../pulls?head=`

**沉淀原因**：跨需求会重复（A）+ AI 反复犯同类错（B）

## 问题

REQ-2026-007 修 F-11（跨 fork 同名分支让 ahead-of-origin gate 假命中）时直觉地把 `gh pr list --head` 改成 `OWNER:BRANCH`（这是 `gh pr create --head` 的语法）。codex round-6 揪出这是 **P1 真实回归**：

```
gh pr list --head <branch>     # OK
gh pr list --head OWNER:BRANCH # ❌ manual 明确「":" syntax not supported」
                                #   实测 gh 把 `:` 当成分支名一部分，命中永远空
```

后果：`_pr_open_for_branch` 永远返 None → precheck 不再 skip → 同分支已有 open PR 的 submit 重跑被错误拦下 `R-NOTHING-TO-PUSH`。

回退到按分支名查 + Python 后过滤 owner 后，round-7 又揪 P2：`gh pr list --limit 30` 是「最多取 30 条」，fork 多的 repo 里本 owner PR 可能落在结果之外。最终 round-8 切到：

```bash
gh api "repos/{owner}/{repo}/pulls?state=open&head=OWNER%3ABRANCH&per_page=100" --paginate
```

GitHub REST API **原生支持** `head=user:ref-name`（与 `gh pr list --head` 不同），文档：[List PRs](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests)。

## 根因

`gh` CLI 各子命令是**独立设计的薄包装**，对参数语义并不强求"同一含义同一语法"：

| Surface | `--head` 语法 | 内部映射 |
|---|---|---|
| `gh pr create` | `[<owner>:]<branch>` | PR 创建参数（fork PR 必须 owner） |
| `gh pr list` | `<branch>` only | `head_ref_name` 单字段查询，无法表达 owner |
| `gh api repos/.../pulls?head=` | `user:ref-name` 原生支持 | 直传 GitHub REST API 查询参数 |

同概念在不同 surface 下的语法分歧是**客观存在的实现细节**，不是 bug——是 GitHub Web UI / REST API / `gh` CLI 三个抽象层各自演化的结果。

## 解法

- **每个 `gh <cmd>` 的关键参数都必须看一次 `gh <cmd> --help`**——不能从 `pr create` 推到 `pr list`，不能从一年前的记忆推到当前版本
- 涉及 **owner-scoped / 跨 fork 过滤** 的查询，**优先用 `gh api ...` 直查 GitHub REST API**——表达力最强，参数语义文档化最清晰，不存在 `gh` CLI 的 limit cap / 语法糖差异
- 调用点把 manual 关键约束**作为注释钉住**，后人改时一眼看到：

```python
# gh pr list --head: ":" syntax not supported（manual 明确，不是笔误）
# 跨 fork 过滤改用 gh api repos/.../pulls?head=owner:branch
```

- 跨 surface 的语法分歧值得**回归 pytest 显式断言**，例如：

```python
api_cmd = next(c for c in captured if c[:2] == ["gh", "api"])
endpoint = api_cmd[2]
assert "head=hjaaa%3Afeat%2Ftest-branch" in endpoint  # URL-encoded owner:branch
```

防止下次「修一个引一个」的回归（F-11 → F-12 → F-13 三轮才稳态）。

## 验证方法

修改 `gh` CLI 调用前：

```bash
gh <cmd> --help | grep -A 3 <flag>     # 看 manual 关键约束
gh <cmd> --help | grep -i "limit\|per_page\|paginate"  # 看是否有 cap
```

改完跑沙盒 PR 走 fork / 无 fork / >30 PR 三场景 → 期望命中行为与文档一致。

## 引用来源

- REQ-2026-007 codex round-5/6/7/8 演化路径：F-11 → F-12 → F-13 → F-14/F-15
- 终态实现 commit `1cb8417`：`scripts/gates/plugins/ahead_of_origin.py::_pr_open_for_branch` 切 `gh api` + URL-encode + paginate
- 回归 pytest：`tests/gates/test_ahead_of_origin.py::test_pr_lookup_uses_gh_api_with_owner_scoped_head`
- 关联经验：`refactor-grep-old-symbols-and-cli-flags.md`（重构核心模块要 grep 全仓 stale 调用）
