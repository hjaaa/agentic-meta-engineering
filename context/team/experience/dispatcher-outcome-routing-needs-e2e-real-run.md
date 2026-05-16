# dispatcher → router 路由表必须有 E2E 真跑覆盖；单测 mock 看不出"缺分支"

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

> 与 [`event-driven-completion-must-write-on-outcome.md`](event-driven-completion-must-write-on-outcome.md) 互补——
> 前者讲"完成状态由 outcome 触发写入"；本条聚焦"dispatcher 返回的 outcome 在 router 端必须有对应分支，否则会落到 unknown 兜底误判 failed"。

## 问题

REQ-2026-011 F-002 / F-013 落地 `awaiting_claude_action` outcome（agent / skill / prompt 节点写 `node_ready` 后暂停等 Claude `save_node_result.py` 推进）。`workflow_dispatcher._dispatch_agent_node` / `_dispatch_skill_node` / `_dispatch_prompt_node` 三处都返回 `DispatchResult(outcome="awaiting_claude_action")`。但 `workflow_outcome_router._route_outcome` 没有对应 `elif` 分支：

```
completed / loop_continue / loop_done / sub_workflow_done / approval_pending / sub_workflow_pending / failed → 显式分支
awaiting_claude_action → 落到 else 兜底 → 写 workflow_failed + state=failed
```

实际跑任何含 agent / skill / prompt 节点的 yaml 会被立刻误判 workflow_failed。

但整个内部审查链全没抓到：

- 13 个 feature 各 1~2 轮 code-review，全部 `looks_clean` + signoff approved
- detail-design 16 轮迭代评审 looks_clean(92)
- traceability-consistency-checker PASS（需求 → 设计 → 代码 → 测试 4 层全过，含 interface_signature_match + test_branch_coverage 检查）
- pytest 1524 passed / 0 failed / 8 skipped

submit 后 codex round-1 **一句话**抓出 P1：
> `_route_outcome` does not have a branch for `awaiting_claude_action`, so it falls into the unknown-outcome fallback and writes `workflow_failed`.

## 根因

`workflow_dispatcher` 单测验证「`_dispatch_skill_node` 返回 `outcome="awaiting_claude_action"`」（断言返回值符合契约）。`workflow_outcome_router` 单测验证「`_route_outcome` 在每个**已实现**分支的行为符合预期」。两边视野各自完备，但**没有任何一个测试横跨「dispatcher 真实返回 → router 真实路由」**。

router 单测里所有 `outcome` 都是测试代码硬编码 `DispatchResult(outcome="approval_pending")` 之类，要测哪个分支就构造哪个值——所以**router 缺分支这种 bug，router 单测永远抓不到**。

dispatcher 单测对返回值的契约断言也帮不上忙——它只验证「返回 awaiting_claude_action」，不验证「router 能消化 awaiting_claude_action」。

E2E 真跑（用真实 dispatcher + 真实 router 跑一个 agent yaml）才会暴露：jsonl 末位是 `workflow_failed` 而不是预期的 `node_ready` + 暂停。

## 解法

**outcome routing 完备性必须靠"穷举枚举 + E2E 真跑"双轨保护**：

1. **枚举校验**：写一个集成测试遍历 `dispatch_node` 所有返回值（grep `return DispatchResult\(outcome=` 取 set），断言 `_route_outcome` 对每个 outcome 都不写 `workflow_failed`（除非该 outcome 本身就是 `failed`）。位置：`tests/lib/test_route_outcome_completeness.py`。

2. **E2E 真跑覆盖**：每种节点类型（bash / skill / agent / prompt / artifact / approval / loop / sub_workflow）至少有一个 e2e fixture 跑真实 dispatcher + 真实 router，**用 jsonl 末位事件类型断言而不是 mock 返回值断言**。

3. **submit 默认带 codex review-loop**（已 memory 锁定）—— codex 的 P1 finding 通常就是这种"覆盖率高但路径覆盖不全"的盲区，参见 [`external-ai-reviewer-finds-internal-blindspots.md`](external-ai-reviewer-finds-internal-blindspots.md)。

## 验证方法

- **测试 A**：grep `return DispatchResult(outcome=` 扫出全集 → 对每个 outcome 调用 `_route_outcome`，断言不落 unknown 兜底
- **测试 B**：agent / skill / prompt 三类节点各一个 e2e fixture，跑真实 main loop → 断言 jsonl 末位 = `node_ready`（state=awaiting_claude_action），**不**是 `workflow_failed`
- 在 reviewer prompt 中显式列「outcome routing 完备性」作为审查 checkpoint

## 引用来源

- `requirements/REQ-2026-011/artifacts/codex-reviews/round-1.md`（codex 抓 P1+P2 真 bug）
- `requirements/REQ-2026-011/artifacts/codex-reviews/round-2.md`（fix 后 passed）
- `scripts/lib/workflow_outcome_router.py:296`（F-014 补的 `awaiting_claude_action` 分支）
- `tests/skills/test_workflow_continue_awaiting_skip_fixes.py`（F-014 回归测试 TC-F14-1）
- merge commit `11e6cb7` (PR #72)
