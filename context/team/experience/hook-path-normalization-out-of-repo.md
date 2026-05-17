# touches_guard 等仓库内 hook 需 normalize 仓库外路径

**沉淀原因**：跨需求重复（任何主 Agent 在 dispatch lock 上锁期间 Write `/tmp/*` 准备文件、调试都会撞）、AI 反复错（本需求 F-003 触发 2 次 /tmp violation）、跨会话需保留（涉及 hook 链 critical path 实现，未来 hotfix 设计者需快速复用上下文）。

## 问题

REQ-2026-012 F-003 派发期间，主 Agent（dispatch-state.json `current_feature=F-003`）用 Write 工具写 `/tmp/F-003-verdict.json` 准备 reviewer verdict 文件。`touches_guard.py` PreToolUse 拦截，把 `/tmp/...` 路径软记入 `requirements/REQ-2026-012/artifacts/tasks/F-003.receipt.json.touches_violations[]`。这 2 条 violation 非真实越界（/tmp 在仓库外，与 F-003 设计无关），但 `GATE-TOUCHES-VIOLATION` 不区分仓库内外 → 阻断 phase-transition / submit。

## 根因

`touches_guard.py` 的 path 校验只比对 `task.md.touches[]` 数组成员是否覆盖目标路径，没在 normalize 阶段过滤"非仓库相对路径"。任何绝对路径（`/tmp` / `/var` / `~/...`）在仓库根维度都不可能属于 task touches 集合 → 必报 violation，但这些路径与 feature 设计无关，本就不该进 violation 统计。

## 解法

**触发点**：`.claude/hooks/touches_guard.py` PreToolUse 收到 `file_path` 时：

1. 用 `Path(file_path).resolve()` 规范化绝对路径
2. 取仓库根 `git rev-parse --show-toplevel`
3. 若规范化后的路径**不在仓库根之下**（`relative_to` 抛 ValueError）→ **直接返回 exit 0**（不记 violation，不阻断）；只对仓库内文件做 touches 校验

附配套：`scripts/lib/historical_touches_violations.py` 等清零工具同步排除非仓库路径，避免历史 receipt.json `touches_violations[]` 残留 `/tmp` 类条目。

## 验证方法

- bats 新增 case：`Write /tmp/<random>.json` 触发 PreToolUse → exit 0 + receipt.json 无新增 violation
- 集成测试：在 dispatch lock 上锁状态下写 `/tmp/`、`/var/`、`~/.cache/` 三类路径 → `tasks/<fid>.receipt.json.touches_violations[]` 不增长
- 跨需求验证：未来任何主 Agent dispatch lock 期 write /tmp 不再触发 `GATE-TOUCHES-VIOLATION` 假阳性

## 引用来源

- `requirements/REQ-2026-012/notes.md:19-24` — 原 follow-up 候选 D-011
- 手动清空 violation 操作：F-003 receipt.json edit 记录
- 邻居：`historical-touches-violations-clear-template.md`（流程性产物清零模板；本经验对仓库外路径 source-side normalize，是同议题的预防性改造）
