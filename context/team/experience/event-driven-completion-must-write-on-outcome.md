# 事件型完成状态必须由 outcome 触发写入，不能凭 in-memory 推断

**沉淀原因**：AI 反复错（同一坑 codex 3 轮 review 才纠正到位）+ 跨项目重复

## 问题

main loop 末节点跑完，`current_node` 在内存被置 None，`while running and current_node` 退出。设计者凭 "loop 退出后 state==running ∧ current_node is None" 判定"自然完成"补写 `workflow_completed`。但 `RunState.rebuild` 在看到 `node_completed` 事件后也会把 `current_node` 置 None——crash 在 advance 与 finalize 之间的窗口，rebuild 出来的 state 与"自然完成"形态完全相同，无法区分 → 自然 / crash 两种场景都被误判为完成 → run 被静默截断。

## 根因

"完成"是事件型语义，不是状态型推断。`current_node is None` 只是中间状态投影，与"是否完成"不等价。靠投影推断会因为 rebuild 复现同样投影而失效。

## 解法

工作流终结事件（`workflow_completed` / `workflow_failed`）**只能**由触发它的 outcome 处理函数显式写入：

- 在 `_route_outcome(completed | loop_done | sub_workflow_done)` 内推进 current_node 后立刻检查"是否拓扑末节点"，是则 append `workflow_completed` + 翻 state
- main loop 入口可加补救分支处理"advance 已发生但 finalize 事件 crash 前未写"的窄窗口：扫 jsonl 最后一条 `node_completed` 对应节点在拓扑是否有 next，只有"无 next"才补写
- 禁止在 main loop 自然退出后凭 `current_node is None` 一概补写——区分不了 crash mid-stream

## 验证方法

- 测试 A：rebuild 出 current_node=None 但最后 completed 节点仍有 next → 断言 state 保持 running（crash mid-stream 不误判）
- 测试 B：rebuild 出 current_node=None 且最后 completed 节点无 next → 断言入口补救翻 state=completed
- 测试 C：自然跑完末节点 → 断言 `workflow_completed` 事件被 outcome 路径写入而非退出后

## 引用来源

- `requirements/REQ-2026-010/artifacts/codex-reviews/round-3.md` ~ `round-5.md`（P1-c 从凭状态推断 → outcome 触发 → 入口补救，3 轮迭代）
- `scripts/lib/workflow_continue.py:_route_outcome` + `_finalize_after_rebuild_if_last_topology_node`
- 相关：[[in-memory-state-without-jsonl-event-breaks-rebuild]]
