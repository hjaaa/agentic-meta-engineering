# Squash-merged 分支再开 PR 必须用 merge，不能 rebase

**沉淀原因**：团队 git workflow 共性问题（squash-merge 是默认策略），AI 默认尝试 `git rebase origin/<base>` 必撞冲突，跨人会重复。

## 问题

feature 分支已通过 squash-merge 合入 develop（PR-A），分支保留并继续在上面开发新提交，准备开第二个 PR（PR-B）。`/requirement:submit` 默认在 push 前 `git rebase origin/develop` → 第 1/N commit 起就疯狂冲突，所有"已 squash 的旧 commit"被重新当作待 rebase 的源 commit，与 squash 后的单 commit 在同一文件上"add/add"或"modify/modify"对撞。

实战：REQ-2026-002 F-003+F-004 准备开 PR #45 时 rebase 87 个 commit，前 1 个就在 .gitignore 撞冲突；甚至 abort 后 `git merge` 也炸 ~10 个文件冲突。

## 根因

squash-merge 把多个 commit 压缩成一个新 commit（new sha），原 commit 在 develop 上不存在。git 的 rebase 算法不知道"old commits == new squash commit"的语义等价，逐个 cherry-pick 时必然撞同一文件改动。

## 解法

1. **首选 `--skip-rebase` 直接 push**：GitHub 算 PR diff 时按 head sha vs base 取增量，不看 commit 数；Files changed 干净显示新工作
2. **次选 `git merge origin/<base>`**：产生明确 merge commit，冲突逐个解（典型："modify/delete"取删除方，"add/add"取 ours = 新版）
3. **避免 `git rebase`**：除非分支在 squash-merge 之前就已 reset/重置过

`/requirement:submit` 默认行为可考虑加 detection：检测 base 分支上有 squash-merge 历史（mergedAt 字段）就 skip rebase。

## 验证方法

- `git log --oneline origin/develop..HEAD` 看分支 ahead 数；如果 > 该需求实际 commit 数，多出来的就是已被 squash 的旧 commit
- 改用 merge 后 `gh pr create`，看 PR Files changed 是否只显示真实增量

## 引用来源

- `requirements/REQ-2026-002/process.txt` 2026-04-29 14:34~14:43 段
- 反例：尝试 `git rebase origin/develop` → CONFLICT 1/87 .gitignore → abort
- 正解：`git merge --abort` + `--skip-rebase push` → PR #45 创建成功
