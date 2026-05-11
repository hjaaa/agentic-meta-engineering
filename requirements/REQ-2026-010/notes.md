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

## F-002 review follow-up（rev2 looks_clean 后接受的非阻断项）

### rev2 keep minor（建议后续 feature 顺手清扫）

- **G-3（complexity minor）**：`scripts/lib/workflow_bootstrap.py:243` `_bootstrap_requirement` 51 代码行 / 6 步骤，可抽 `_write_bootstrap_artifacts(req_dir, req_id, title, base_branch)` 合并 3 次 `_write_artifact_file` 调用，使主函数专注协调
- **S-1（aux minor）**：`tests/skills/test_workflow_bootstrap.py:37` 同分组内 `from run_state import read_events` 出现在 `import workflow_bootstrap as wb` 之前，移行后符合 PEP8 isort 惯例
- **S-3（aux minor）**：`scripts/lib/workflow_bootstrap.py:56` `BootstrapError.__init__` 无 docstring（类级 docstring 已说明语义），可选补 1 行 init docstring
- **S-4（aux minor）**：`scripts/lib/workflow_bootstrap.py:94` `logging.debug("git rev-parse HEAD 失败 ...")` 行长 104 字符，拆 2 行或缩短变量名

### rev2 keep info（不强求修）

- **G-5（complexity info）**：`scripts/lib/workflow_run.py:99` `_generate_req_id` 伪嵌套深度 5（多行字符串折行触发，实际控制流深度 4），静态分析边界误报
- **H-1（history-context info）**：`test_workflow_commands.py` 90 天 7 commits 热点；rev2 已拆 `test_workflow_bootstrap.py`，热点会自然降温
- **S-2（aux info，downgraded）**：`tests/skills/test_workflow_bootstrap.py:432` 方法体内 `from common import WorkflowError` 内联导入；测试常见模式，可在大规模重构时统一上提
- **复杂度压线提醒（info）**：`scripts/lib/workflow_bootstrap.py:320` `_bootstrap_rollback` CC=10 / depth=4 / 66 代码行三指标 ==阈值未越界；后续触碰时拆 `_rollback_git_checkout` + `_rollback_git_branch` 两个 helper

### rev1 已 critic-rejected（drop，不再 follow-up）

- **F-6 / F-7**：notes.md 创建 / git add+commit ——detailed-design §1.2 + tasks/F-002.md acceptance 均不要求，bootstrapper.md 旧 subagent spec 已被 Python 实现替代
- **F-18**：`_generate_run_id` iterdir vs scandir 不一致 ——已在 F-001 G-5 同款 follow-up 备案
- **F-21**：previous_branch `--` 前缀 git arg injection ——git check-ref-format 强约束，攻击不可达

### rev2 引入的 EH-1/EH-2/EH-3（rejected, out-of-scope）

`workflow_run.py:268 / 309 / 348` 三处 print stderr 无 logging.error——属 F-001/F-005 既有代码，**不在 F-002 rev2 diff 范围**。如需统一治理日志可观察性，建议作为独立小 PR 收敛全仓 `print(file=sys.stderr)` 调用（按 F-008 / F-009 落地经验拓展）。
