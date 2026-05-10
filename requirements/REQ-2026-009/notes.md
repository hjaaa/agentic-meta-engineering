# REQ-2026-009 · 自定义工作流改造 — 笔记


## 会话经验（2026-05-08 23:37）

_本轮无新经验_

## Follow-up 追踪表（rev4 后更新）

| ID | 性质 | 文件 | 状态 |
|---|---|---|---|
| F-4 | TC-F8-3 三路径断言增强（fail/continue/skip 父侧行为差异）| test_sub_workflow_lifecycle.py | open / 属 F-009/F-010 范围 |
| F-7 | poll_started_event 注入点 + TC-F8-1/TC-F8-5 竞态修复 | test_sub_workflow_lifecycle.py / test_sub_workflow_cancel_advanced.py | **closed** / rev4 已修（MockSubAgent.run() 入口 set + 测试 wait poll_started_event） |
| F-12 | TC-F8-1~4 全量读 jsonl / 生产需改增量 tail 读 | test_sub_workflow_lifecycle.py:99-100 | open / 属 F-009/F-010 范围（生产协调器落地时改） |
| F-15 | TC-F8-4 _ParentCancelCoordinator.request_cancel_and_wait 用 time.sleep（已迁入 e2e_helpers.py）| e2e_helpers.py:218 | open / follow-up（F-009/F-010 续跑机制落地时改） |
| F-16 / G-9 | _poll_parent_cancel nesting=5 架构性嵌套 | sub_workflow_mock.py | open / 重构需拆 _parse_jsonl_line |
| F-20 | TC-F8-5 join 后无 is_alive 检查 | test_sub_workflow_cancel_advanced.py | open / 长跑场景才暴露 |
| F-29 | TC-F8-4 父崩重启续跑仅文件读取无 API | test_sub_workflow_lifecycle.py | open / 属 F-009/F-010 |
| F-32 | datetime 延迟 import | sub_workflow_mock.py | open / 风格小问题 |
