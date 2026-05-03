# plugin 多触发路径必须共享命名约定

**沉淀原因**：跨需求重复（任何 plugin 加新触发路径都涉及）、AI 反复错（写新分支时假设单一调用路径）、跨会话保留（需固化为 helper / schema 约束）。

## 问题

REQ-2026-005 F-001 给 `GATE-REVIEWS-CONSISTENCY` 加 `ci` 全量扫描路径时，假设 `reviews/{latest}.json` 直接用 latest 字段值（如 `REV-REQ-2026-005-definition-002`）查文件。但 `save_review.py:257` 实际写盘用**短名**（去掉 `REV-{REQ-ID}-` 前缀，即 `definition-002.json`）。

本地 `pre-commit` 路径走 `staged` 列表绕开了这个分支（不读 latest），开发期单元测试也覆盖不到 → CI 全量扫描第一次跑就 9 条 `R-REVIEWS-INCONSISTENT` FAIL。

## 根因

plugin 在新增触发路径时，**默认沿用既有命名假设**而不去对齐"下游产物的实际写入约定"。命名规则散落在 `save_review.py` / plugin / runner 三处，没有共享 helper。pre-commit 路径只看 staged diff 不解析文件名，掩盖了不一致；ci 全量扫描首次穿透抽象层才暴露。

## 解法

**新增触发路径前必查 3 件事**：

1. 该路径调用的下游产物（文件 / 字段 / 命令行参数）的实际命名规则，源头在哪个文件
2. 既有路径是否绕开了这个解析（如只看 staged diff、只看字段名）
3. 把命名转换抽成**共享 helper**（如 `_resolve_short_stem(latest, req_id)`），让多触发路径强制共用

**Plugin 编写规约**：跨触发路径的字段解析必须用 helper / schema，不允许各路径分散假设。

## 验证方法

- 新增 trigger 时单测必须覆盖**所有现存触发路径**对该字段的访问（不能只测新增路径）
- `tests/gates/test_reviews_consistency_plugin.py::test_ci_full_scan_resolves_short_filename_when_latest_has_full_id_prefix`（REQ-2026-005 实测回归）
- 同 `_resolve_short_stem` helper 也被 `pre-commit` 路径复用 → 双路径同源

## 引用来源

- `scripts/gates/plugins/reviews_consistency.py`（CI 路径 `_run_ci_full_scan`）
- `scripts/lib/save_review.py:257`（短名写盘约定）
- commit `adfffaa`（REQ-2026-005 修复）
- `requirements/REQ-2026-005/notes.md` PR CI 修复复盘 #1
