# 删除老代码破坏档案需求 archival 引用

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

REQ-2026-006/F-002 删除 `.claude/hooks/protect-branch.sh` / `scripts/gates/plugins/protect_branch.py` / `scripts/gates/triggers/pre_tool_use.sh` / `scripts/gates/plugins/bash_write_protect.py` 4 个文件。本 PR 自身一切正常，但 PR CI 跑 `GATE-SOURCING --strict` 时扫了**全部 requirements/** artifacts，老 completed 需求（REQ-2026-001/002/005）的 6 份文档里 10 处 `（来源：.claude/hooks/protect-branch.sh:1）` / `（来源：scripts/gates/plugins/protect_branch.py:27）` 全部 E002 不存在 → CI red。

老需求都是 `phase=completed / outcome=shipped`，artifacts 是档案，文档内容反映"撰写时刻"的代码状态，路径已经永久消失。

## 根因

CI 全量 sourcing checker 默认对所有 `requirements/*/artifacts/**/*.md` 扫描，没有"档案需求引用是冻结的，不应被后续删除回归"这一边界意识。"completed = shipped = frozen at write-time" 是设计共识但没在 checker 实现里体现。

更深层：任何「全量扫描类」checker（sourcing / link-check / api-stability / SDK-version-pin）只要范围覆盖档案区，遇到删除就会把"对未来的约束"反向施加到"已封存的过去"上，与档案语义冲突。

## 解法

**Checker 边界规则**：
- 全量扫描类 checker 在 `requirements/*/artifacts/**/*.md`、`docs/changelog/`、`*.archive/` 等档案区，必须按档案需求/文档元数据（如 `meta.yaml.phase == "completed"`、changelog 中的 SemVer tag）跳过
- 显式 `--paths`/`sourcing_paths` 注入路径仍扫（开发期主动检查不豁免）
- 单需求模式（`--req=<id>`）不豁免——新需求自己的引用还得校对

**实现模板**：在 `_resolve_targets` 的兜底全量分支加：
```python
for p in sorted(req_root.glob("*/artifacts/**/*.md")):
    if _is_completed_req(p, req_root):  # 读 meta.yaml.phase
        continue
    results.append(p)
```

**回归测试**：包含 `phase=completed` 与 `phase=testing` 两种 fixture，断言只 active 进 results。

## 验证方法

```bash
# 模拟：删除被档案引用的文件，跑 CI sourcing
rm scripts/lib/foo.py
python3 scripts/gates/run.py --trigger=ci --strict
# EXIT=0（completed 需求被豁免；active 需求没引用）
```

## 引用来源

- `requirements/REQ-2026-006/process.txt`（PR #54 round-1 CI fail）
- `scripts/gates/plugins/sourcing.py::_resolve_targets`（修复后）
- `tests/gates/test_sourcing_plugin.py::test_resolve_targets_skips_completed_reqs_in_ci`
- PR #54（squash merge commit `1152ca8`）— `_is_completed_req` 豁免逻辑
