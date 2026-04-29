# Hook 自指系统的 import 死锁

**沉淀原因**：跨需求高频（REQ-2026-002 F-003 + F-004 round-4 各踩一次同款）、AI 反复犯（默认假设 hook 失败应阻断）、跨会话需保留。

## 问题

`PreToolUse` hook 内部 `import` 一段会被 hook 自身门禁约束的代码（典型：runner / plugin / registry）。一旦那段代码因 merge 冲突 marker / 半成品 commit / 未捕获 import 异常 / registry 损坏等原因 syntax/import 不通过，hook 自身崩溃 → exit 2 阻断 → 任何 Bash/Edit/Write 工具调用都被拦 → 死锁，无法用任何工具修复。

实战：F-003 H5 改造时半成品 plugin commit 锁工具链；F-004 round-4 git merge 冲突在 run.py 留 marker 锁工具链。两次都只能用户在终端 escape（`rm` / `git restore` / `git merge --abort`）。

## 根因

hook 是"看门人"，runner/plugin 是"被看的代码"。但当 hook 把 runner 当 enforcement 工具调用时，runner 同时也是 hook 自身的依赖——自指系统失稳。叠加 hook 协议把 `rc != 0` 一刀切翻译为阻断（exit 2），基础设施级故障与业务级 fail 走同退出码，没有 fail-open 出口。

## 解法

1. **hook 加 syntax pre-check**：调 runner 前先 `python3 -m py_compile <runner>.py`，syntax 错就 fail-open
2. **退出码翻译矩阵区分语义**：runner `rc=1` = 业务 fail（阻断 exit 2）；`rc=2` 或其他 = 自身异常（fail-open exit 0 + WARNING）
3. **hook 自指系统设计约束**：禁止 hook 直接 import 当前 working tree 中"会被自己门禁的"代码，必要时用快照副本

完整规范见 [`context/team/engineering-spec/design-guidance/hook-fail-open.md`](../engineering-spec/design-guidance/hook-fail-open.md)。

## 验证方法

- 故意改坏 runner（加 `<<<<<<<` marker / 删 import）→ 跑任意 Bash → 看到 WARNING 但工具调用照常通过
- 单测：`tests/gates/test_pre_tool_use_trigger.py::test_pre_tool_use_fails_open_on_run_py_syntax_error`

## 引用来源

- `requirements/REQ-2026-002/notes.md:18-44`（F-003 H5 死锁两次）
- `requirements/REQ-2026-002/notes.md` 末段 + process.txt 2026-04-29 14:30~14:43（F-004 round-4 merge 死锁）
- 落实：`scripts/gates/triggers/pre_tool_use.sh:63-90`
