# 多阶段流程的顺序约束必须以累积清单显式记录

**沉淀原因**：满足「跨需求复用 / AI 反复错 / 跨会话需保留」三条。

## 问题

`archive_requirement` 的流程顺序在 REQ-2026-014 期间经历 5 轮 codex review 调整（F-1/F-3/F-4/F-5/F-6），每修一条新约束就引入新的违反：

1. 第 1 轮把 `_cleanup_worktree` 挪到 bookkeeping 后 → 又遇到 module-level REPO_ROOT 未 rebind 问题；
2. 第 2 轮加 `_rebind_to_main_repo` 在入口最早 → 破坏 `_precheck_dirty` 在 worktree 上的检查（rebind 切到 clean 主仓）；
3. 第 3 轮把 dirty 挪到 rebind 前 → `_load_meta` 仍在 rebind 前读 worktree 副本，后续 write_meta 用 stale dict 覆盖主仓；
4. 第 4 轮把 load_meta 挪到 rebind 后 → 又漏了从主仓启动时 dirty 仅检查主仓不看 owned worktree（F-4 的对称场景）。

根本原因：每轮修复只看「上轮 finding 描述的单点约束」，没有把所有累积约束的依赖关系列出来一起核对。

## 根因

多阶段流程（precheck → mutation → cleanup → bookkeeping）的步骤间有**多条交叉约束**：

- 谁先于谁
- 谁依赖 module-level 全局状态被某步骤更新过
- 谁在何种 cwd / 工作区下生效

代码读者只能从函数调用顺序推断，看不到「这个顺序为什么是这个」。新加约束时容易破坏旧约束。

## 解法

**在流程主入口处（或对应 step 注释段）以「累积约束清单」格式显式注释**，每条约束包含：

1. 来源（哪轮 finding / 哪个 commit / 哪个 PR comment）
2. 文字描述
3. 与其他约束的依赖关系（"必须在 X 之前 / 之后"）

模板（来自 `scripts/lib/archive_runner.py:765-783`）：

```python
# —— 关键顺序约束（codex P1 round-1~5 F-1 / F-3 / F-4 / F-5 / F-6 累积修复）——
#
# 1. _rebind_to_main_repo 必须在 _load_meta / dirty / cleanup / write_meta 之前：
#    确保 path helper 一律解析到主仓（F-1 / F-3）。
# 2. _load_meta 必须在 rebind 之后：从主仓加载 meta dict，避免 worktree stale
#    副本覆盖主仓较新 metadata（F-5）。
# 3. _precheck_dirty 必须在 cleanup 之前 且 同时检查主仓 + owned worktree
#    （F-4 / F-6）。
#
# 综合顺序：
#   rebind → load_meta (main) → dirty (both) → 其他 precheck → cleanup → write_meta
```

新加约束时**必须**先在注释里追加一条 + 列依赖关系，再改代码。改完后回头核对所有约束是否仍满足。

## 验证方法

- 修改有顺序敏感性的流程时，PR description 必含「列出累积约束」段，逐条解释为何调整位置不违反任何一条。
- 新增 task / step 时，检查是否影响 module-level 全局状态、是否依赖前置步骤的副作用——若是，在主入口注释里加一条。
- 回归测试：每条约束至少一个对应的 unit test 覆盖（如 `test_archive_dirty_worktree_fails_before_rebind` / `test_archive_loads_meta_from_main_repo_after_rebind` / `test_archive_from_main_repo_dirty_worktree_fails_fast`）。

## 关联

- `requirements/REQ-2026-014/process.txt`（codex round-1~5 修复链）
- PR #80（commit `ca2ddc9` / `aead5d9` / `dfb1441` / `3656769`）
- `scripts/lib/archive_runner.py:archive_requirement`
