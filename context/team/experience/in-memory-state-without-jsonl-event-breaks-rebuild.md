# in-memory 状态变化不写 jsonl 事件 → crash 恢复后重放出错

**沉淀原因**：跨项目重复（任何 in-memory state + jsonl rebuild 架构都会踩）+ AI 反复错

## 问题

模块在内存修改状态字段（如 `loop_counters[node_id] += 1`）但不写对应 jsonl 事件持久化。crash 后 `RunState.rebuild` 反扫 jsonl 重建状态，看不到那次修改 → 状态比运行时少 1 → 下次派发时重派同一轮，出现"crash 恢复后重复执行"或"completed 状态丢失"等语义错乱。

## 根因

把内存对象当 "single source of truth" 用，没意识到对 dataclass field 的赋值不会被 jsonl reader 看到。这是事件溯源（event sourcing）架构的核心约束：**state 是 events 的派生量，不是反过来**。

## 解法

任何对持久化字段的修改**必须**同时 append 对应 jsonl 事件。流程：

1. 列出 RunState 里所有"持久化字段"（rebuild 时会消费 jsonl 还原的）
2. 对每个字段，每处 in-memory 修改都对应一条 `*_advanced` / `*_updated` 事件
3. 在 rebuild 里加分支消费这些事件
4. 测试：mock 一段 jsonl + crash + rebuild，断言 state 还原至 crash 前

警示信号：写出 `state.foo[bar] += 1` / `state.foo = new` 后**必须**问"这次修改 crash 后 rebuild 看得到吗"。看不到则补事件。

## 验证方法

- 单测：构造"in-memory 改一次 + 不写事件 + rebuild" → 断言新 state == initial state（证明未持久化）
- 单测：构造"in-memory 改一次 + 写事件 + rebuild" → 断言 state 完整还原
- crash 恢复 e2e：跑到中间 kill 进程，re-run 后断言不重复执行同一步

## 引用来源

- `requirements/REQ-2026-010/notes.md:91-114`（F-011 rev2 loop_counters 内存递增 + crash 恢复重派 iteration bug，commit 48ac57e 走方向 a 修）
- 相关：[[event-driven-completion-must-write-on-outcome]]
