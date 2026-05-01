# 改 hook 链文件时 Edit 顺序错会自锁工具链

**沉淀原因**：跨需求会重复（任何修改 hook 链上文件的工作都可能踩）、AI 反复犯（默认从"用法"先写、再写"定义"是常见思路）、跨会话需保留。

> 与 `hook-self-import-deadlock.md` 同一系列：那篇讲"hook import 半成品代码"导致死锁，本篇讲"Edit 顺序错"导致死锁——根因不同但症状相同。

## 问题

我在 `scripts/gates/run.py` 里**先加了 `_validate_phase_args(args)` 的调用**，打算下一步再加函数定义。但中间任何 Edit / Write / Bash 都会触发 PreToolUse hook → hook 跑 run.py → `NameError: _validate_phase_args is not defined` → rc=1 → hook 拦死全部后续工具。最终需要用户手动 `! sed -i '' '428,434d' scripts/gates/run.py` 删掉坏调用才解锁。

## 根因

PreToolUse hook 的 syntax pre-check（`py_compile`）只检语法不检 NameError；NameError 发生在**模块加载时**而非 syntax check 时。fail-open 兜底路径（rc=2 = self-error）也不生效，因为 `NameError` 走 rc=1（业务 fail）。Edit 工具的"先调用后定义"半成品状态对 hook 来说是"业务级失败"，不是"基础设施异常"。

## 解法

改 hook 链上的关键文件（`scripts/gates/run.py` / `scripts/lib/check_reviews.py` / `scripts/lib/save_review.py` / `scripts/gates/plugins/*.py` 等）时遵守两条之一：

1. **先加函数定义，再加调用**——保证任意中间状态文件可加载
2. **用 try/except 临时包住调用**：
   ```python
   try:
       _validate_phase_args(args)
   except NameError:
       pass  # TODO: 待函数定义到位后去掉 try
   ```
   等定义到位再去掉 try

## 验证方法

- 改 hook 链文件后，用 `python3 -c "import scripts.gates.run"` 试加载，确认无 NameError
- 改完一处定义/调用后立即 `python3 scripts/gates/run.py --help` 触发完整加载

## 引用来源

- `requirements/REQ-2026-003/notes.md:12-22`
- 同系列：`context/team/experience/hook-self-import-deadlock.md`（hook 自指系统设计约束）
