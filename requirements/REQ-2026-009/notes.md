# REQ-2026-009 · 自定义工作流改造 — 笔记


## 会话经验（2026-05-08 23:37）

_本轮无新经验_

## Follow-up 追踪表（rev3 后）

| ID | 性质 | 文件 | 状态 |
|---|---|---|---|
| F-4 | TC-F8-3 三路径断言增强（fail/continue/skip 父侧行为差异）| test_sub_workflow_lifecycle.py | open / 属 F-009/F-010 范围 |
| F-7 | TC-F8-6 时延断言写法（mock sleep 后断言验证 "同步比 11s 快"）| test_sub_workflow_cancel_advanced.py | open / minor |
| F-16 / G-9 | _poll_parent_cancel nesting=5 架构性嵌套 | sub_workflow_mock.py:131 | open / 重构需拆 _parse_jsonl_line |
| F-20 | TC-F8-5 join 后无 is_alive 检查 | test_sub_workflow_cancel_advanced.py | open / 长跑场景才暴露 |
| F-29 | TC-F8-4 父崩重启续跑仅文件读取无 API | test_sub_workflow_lifecycle.py | open / 属 F-009/F-010 |
| F-32 | datetime 延迟 import | sub_workflow_mock.py:212 | open / 风格小问题 |
