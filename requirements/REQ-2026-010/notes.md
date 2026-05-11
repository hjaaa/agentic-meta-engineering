# REQ-2026-010 · 过程笔记

## 起手说明

本需求是 REQ-2026-009（自定义工作流改造）在 PR-68 hotfix 后的 Window B 落地。
PR-68 完成了 Window A 紧急修复（keyword_matcher 兼容性、workflow_rollback_cmd 健壮性等），
Window B 的 main loop 完整化与 bootstrap 流程补全延至本需求实施。

## F-001 review follow-up（rev2 looks_clean 后接受的非阻断项，待后续 feature 顺手清扫或独立 PR）

- **G-1（error-handling minor，建议本轮顺手修）**：`scripts/lib/workflow_run.py:106` `current_max = max(nums) if nums else 998` 的 `else 998` 死分支。改 `current_max = max(nums)` 即可，5 秒
- **G-6（aux minor，建议本轮顺手修）**：`tests/skills/test_workflow_commands.py:873` `# TC-F1-3：` 全角冒号 → 半角 `:`
- **G-2（complexity follow-up）**：`tests/skills/test_workflow_commands.py` 902 行近 1000 硬阈值；F-005/F-008 启动前评估按 TestClass 拆分（test_workflow_run_id.py / test_workflow_commands_core.py 等）
- **G-5（security follow-up）**：`scripts/lib/workflow_run.py:95` `os.scandir` 异常路径未 WorkflowError 包装；需与 `_generate_run_id` line 51 同步重构（独立议题）
- **G-7/G-8（aux follow-up）**：测试文件 5+ 处方法内 `import workflow_run as wr` / `from datetime import ...` 风格统一上提（独立 PR 重构）
- **G-9（concurrency info）**：TC-F1-2 `barrier.wait()` 防御性包入 try（实践不可触发）
- **F-7 / F-11（rev1 旧 follow-up 延续）**：`results.append` GIL 依赖 / `except Exception` 过宽（与 TC-F5-G8 同款）
- **F-1（history-context info）**：`tests/skills/test_workflow_commands.py` 30 天内 2 次 hotfix（7ffc8ad / ff16de2），关注后续是否仍频繁改并发逻辑
