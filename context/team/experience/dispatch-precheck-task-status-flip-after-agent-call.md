# 派 subagent 时翻 task.md status 必须在调 Agent 工具之后

## 问题

主 Agent 派 implementer subagent 时，按 `subagent-dispatch.md` 4 步排版顺序读，容易在调 Agent 工具**之前**就把 `tasks/F-xxx.md.status` 从 `pending` 翻成 `in-progress`。结果 PreToolUse hook `dispatch_precheck.py` B-1 校验读到 status != pending → exit 2 + `BLOCKED: F-xxx 状态为 in-progress，期望 pending`。必须 git checkout 还原 task.md + 删 dispatch-state.json 残留才能重派。本仓库历史上 AI 反复踩此坑（用户反馈"之前经常出现"）。

## 根因

派发链的契约是「调 Agent 工具那一刻 task.md.status == pending」——hook 在 PreToolUse 阶段读 task.md 作 source of truth；hook 自己在 flock 内写 dispatch-state.json (current_feature=fid)，但**不翻 task.md status**。两份 SOP 文档对"翻 status"位置描述不一致：`SKILL.md` 顺序正确（派 Agent → 翻 status），但 `subagent-dispatch.md` 把"状态流转"作为派发前置校验列表的步骤 4 排在 context 构造之后，没显式说"调 Agent 在更前面"，AI 默认按列表顺序执行就提前翻。

## 解法

固定派发顺序（与 `SKILL.md:29-41` 一致）：

1. 读 task.md 校验 status == pending（**仅读不写**）
2. 校验 depends_on 全 done
3. 调 task-context-builder 构造 context
4. **调 Agent 工具派 subagent**（task.md.status 仍 pending → hook B-1 通过 → hook 写 dispatch lock）
5. 派发**返回后**主 Agent 翻 task.md status: pending → in-progress + updated_at + 写 `process.txt [development] F-xxx 开始（派 subagent: <model>）`
6. 等回执 → 处理 DONE/DONE_WITH_CONCERNS → 转 done + 调 `dispatch_state_cleanup.py` 释放 lock

口诀：**hook 把锁交给你之后你才有资格写 task.md**。

## 验证方法

- 派发前 `git diff requirements/<id>/artifacts/tasks/<fid>.md` 应该为空（无任何改动）
- 派发后才看到 `status: pending → in-progress` 的 commit/diff
- 命中此坑的恢复操作：`git checkout requirements/<id>/artifacts/tasks/<fid>.md`（还原 status）+ `rm -f requirements/<id>/.dispatch-state.json`（如有残留）→ 重新按正确顺序派
- 跨需求观察：未来 dev 阶段派发首次成功率，无 BLOCKED B-1 反复触发即视为习惯固化

## 关联

- `.claude/hooks/dispatch_precheck.py:344-356`（B-1 契约 source）
- `.claude/skills/feature-lifecycle-manager/SKILL.md:29-41`（正确顺序）
- `.claude/skills/feature-lifecycle-manager/reference/subagent-dispatch.md:30-41`（已修订消除歧义）
- `edit-order-locks-hook-chain.md`（同类「hook + 文件顺序」陷阱：先定义后调用）
