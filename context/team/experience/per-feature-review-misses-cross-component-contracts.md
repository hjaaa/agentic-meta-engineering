# per-feature code review 看不到跨组件契约的盲区

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

20260519-context-usage-report PR #84 的 13 个 per-feature code review（F-001 ~ F-013）全部 looks_clean（含 2 轮 review、design_consistency 维度全部 90+）。submit 后 codex round=1 一次 review 抓到 2 条 P1，**两条同根**：

- `scripts/lib/context_usage_report.py:200` —— `_build_file_cache` 用 `requirements_dir / evidence.source` 拼路径
- `scripts/lib/context_usage_report.py:280` —— `_build_all_files_for_git` 同模式拼路径

`EvidenceScanner` 的输出契约里，`ReferenceEvidence.source` 是 repo-root-relative POSIX 路径（如 `requirements/REQ-X/plan.md`，参 `context_usage_evidence.py:263` `file_path.resolve().relative_to(self._repo_root)`）。但调用方用 `requirements_dir`（已经含 `requirements/` 前缀）拼接 → 结果是 `<repo>/requirements/requirements/REQ-X/plan.md` 双前缀，**所有文件 miss**。后果：

- `_build_file_cache` 永远空 → `AppliedSignalClassifier` 取不到 source 正文 → applied_signal 整批 0 → high_value 分类静默错误
- `_build_all_files_for_git` 缺 reference source → git_timestamps 缺失 → `last_referenced_at=None` → recency 评分 + stale 检测整批失效

## 根因

per-feature code review 的 reviewer 视野结构性局限：

- F-006 reviewer 看 `EvidenceScanner` 实现 + F-006.md，关心"输出对不对、有没有 mask、有没有过滤"
- F-007/F-009 reviewer 看 `AppliedSignalClassifier` / `UsageAggregator` 实现 + 各自 task.md，关心"评分逻辑、状态分类、覆盖率"
- F-011 reviewer 看 CLI 装配，关心"argparse、exit code、退出语义"

**没有任何一个 reviewer 的视野同时包含"组件 A 输出契约 + 组件 B 消费方式"**。design_consistency 维度的 reviewer 即使打 95+，也只能从单 feature 维度判"实现 vs task.md 一致"，看不到组件间的契约不一致。

这是与 `external-ai-reviewer-finds-internal-blindspots.md` 互补的具体化经验：那条说"外部 reviewer 补内部 checker 链盲区"是抽象规则，本条揭示**per-feature review 的盲区结构 = 跨组件契约（path / schema / 命名格式）的拼接一致性**——这种 bug 是 silent 的（不抛异常，只让指标静默归零）。

## 解法

**短期（每个需求）**：

- 多组件需求在 testing 阶段必须跑一次 codex review-loop（已落 `/requirement:submit` 默认 --codex 翻转）
- per-feature review 完成后、submit 前，主 Agent 自己应该至少做一次"跨组件契约 trace"：每个 ReferenceEvidence-like 数据对象，trace 从产出方到所有消费方，确认路径前缀 / 字段命名 / schema 版本对齐

**中期（reviewer 设计反哺）**：

- 加 `cross-component-contract-checker` 专项 checker（list 所有 data class 的产出方 + 消费方，断言路径/类型/schema 一致）
- 或在 `design-consistency-checker` 检查清单加一条"跨组件 path concatenation 一致性"

**Round-trip 节奏**：codex round=1 揭示 P1 后必须**修 + push + 再触发 codex round=2** 验证修复有效，不能修完就 merge（codex 没复评）。

## 验证方法

- 测试侧：每条 ReferenceEvidence-like 契约必须有 e2e 回归 case 显式断言 path 拼接结构（参 `tests/lib/test_context_usage_e2e.py::test_bug23_*` / `test_bug24_*`，构造 repo_root-relative source + 验证 cache hit）
- 流程侧：codex round=N+1 verdict=passed 才算 "no major issues" 闭环

## 引用来源

- `requirements/20260519-context-usage-report/notes.md` Bug-23 / Bug-24
- PR #84 codex round=1 P1 finding：https://github.com/hjaaa/agentic-meta-engineering/pull/84
- `requirements/20260519-context-usage-report/process.txt`（2026-05-21 [codex-review-received] verdict=not_passed → fix → verdict=passed 两轮迭代）
- 关联经验：
  - `external-ai-reviewer-finds-internal-blindspots.md`（抽象规则——本条是其具体化）
  - `cross-language-pipeline-path-anchor.md`（同款"路径拼接漂移"，跨语言版）
