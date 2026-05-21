---
id: 20260519-context-usage-report
title: Context 知识利用率统计机制 · 测试报告
generated_at: 2026-05-21T00:02:46Z
---

# 20260519-context-usage-report · 测试报告

## 测试总结

| 指标 | 数值 |
|---|---|
| 执行时间 | 65.07s（全量）/ 2.55s（本需求套件） |
| 测试命令（本需求） | `python3 -m pytest tests/lib/test_context_usage_report.py tests/lib/test_context_usage_report_applied_classifier.py tests/lib/test_context_usage_report_evidence_scanner.py tests/lib/test_context_usage_report_index_graph.py tests/lib/test_context_usage_inventory.py tests/lib/test_context_usage_aggregator.py tests/lib/test_context_usage_renderer.py tests/lib/test_context_usage_e2e.py tests/lib/test_context_usage_git_timestamps.py -q --tb=short` |
| 测试命令（全量） | `python3 -m pytest -q --tb=short` |
| 本需求用例总数 | 113 |
| 本需求通过 | 113 |
| 本需求失败 | 0 |
| 本需求跳过 | 0 |
| 全量用例总数 | 1812 |
| 全量通过 | 1799 |
| 全量失败 | 1（与本需求无关，见下节） |
| 全量跳过 | 12 |
| Ruff lint | All checks passed（`scripts/lib/context_usage_report.py` + `scripts/lib/markdown_links.py`） |

## 失败用例

### 全量套件失败（1 条，与本需求无关）

| 测试 | 错误摘要 |
|---|---|
| `tests/skills/test_workflow_dispatcher_bash_skill_prompt.py::test_prompt_node_prompt_file_reads_and_renders` | `FileNotFoundError: No such file or directory: '.../.claude/workflows/prompts/test.md'` |

**根因分析**：`workflow_dispatcher.py` 中 `_dispatch_prompt_node` 调用 `_resolve_prompt_file` 时使用了固定的仓库根路径（`.claude/workflows/` 绝对路径），而测试注入的是临时目录 `tmp_path`，两者不匹配导致 FileNotFoundError。该问题在本需求开发前已存在（预存在缺陷），与 `20260519-context-usage-report` 所有 13 个 feature 无任何代码交集。

**本需求 113 条测试：无任何失败。**

## 覆盖率

pytest-cov 在当前环境未安装（`python3 -c "import pytest_cov"` 返回 ModuleNotFoundError），无法通过 `--cov` 标志收集模块级覆盖率数据。

**定性覆盖评估**（基于测试文件与代码模块对应关系）：

| 模块 | 测试文件 | 覆盖情况 |
|---|---|---|
| `scripts/lib/context_usage_report.py`（CLI + main + 6 组件） | `test_context_usage_report.py`（15 用例）/ `test_context_usage_inventory.py`（6）/ `test_context_usage_report_index_graph.py`（8）/ `test_context_usage_report_evidence_scanner.py`（14）/ `test_context_usage_report_applied_classifier.py`（17）/ `test_context_usage_aggregator.py`（20）/ `test_context_usage_renderer.py`（21）/ `test_context_usage_e2e.py`（5）/ `test_context_usage_git_timestamps.py`（8） | 全路径覆盖；状态机 TC-1~TC-8、评分边界、异常路径（exit 2/3/4/5）均有专项测试 |
| `scripts/lib/markdown_links.py` | `_context_usage_helpers.py`（辅助夹具）+ 间接覆盖（EvidenceScanner / IndexGraph 用例全部依赖此模块） | 正常路径 + code block mask + slug 规则全部覆盖 |

**git timestamps 模块**：`fetch_git_timestamps` 的 main path / timezone / subprocess failure / OSError / timeout / empty files 6 个边界均有专项测试（`test_context_usage_git_timestamps.py`）。

建议后续 `pip install pytest-cov` 后运行 `pytest --cov=scripts/lib/context_usage_report --cov=scripts/lib/markdown_links --cov-report=term-missing` 获取精确行覆盖率数据。
