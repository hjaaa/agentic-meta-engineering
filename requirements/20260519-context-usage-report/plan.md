# 20260519-context-usage-report · Context 知识利用率统计机制

## 目标

构建一套可重复运行的 Context 知识利用率统计工具：自动扫描 context/** + requirements/** 的 Markdown 知识库，按文件维度产出"高价值 / 待治理 / 孤岛 / 断链"四象限分类报告，让团队定期识别该删 / 该升级 / 该补的知识条目。

## 范围

- 包含：
  - scripts/lib/context_usage_report.py CLI 工具（6 个子组件：Inventory / IndexGraph / EvidenceScanner / AppliedSignalClassifier / GitTimestamp / UsageAggregator / ReportRenderer）
  - scripts/lib/markdown_links.py 公共抽取模块（从 check_index.py 平移共享）
  - 报告产出：reports/context-usage.md + reports/context-usage.json（两格式同步）
  - tests/lib/test_context_usage_*.py 8 个测试文件 + fixture 仓回归（CI < 5s 守门）
- 不包含：
  - 自动治理动作（删 / 升级 / 补）—— 本期仅出报告，治理决策交给人/后续 Phase 3
  - 历史趋势分析 / 时序对比 —— 当前只快照单次，趋势分析挂账 Phase 3
  - 向量检索 / 语义相似度 —— MVP 仅做 reference graph 统计，不引入向量服务
  - 治理动作 webhook / Slack 通知 —— 报告纯文件输出，集成留给 Phase 3

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | 2026-05-19 |
| tech-research | 2026-05-19 |
| outline-design | 2026-05-19 |
| detail-design | 2026-05-19 |
| task-planning | 2026-05-19 |
| development | 2026-05-20 |
| testing | 2026-05-20 |

## 风险

- **R-1**：评分模型阈值（HIGH_VALUE_REFERENCE_MIN=3 / APPLIED_SCORE_CAP=40）需后续调参验证 / 应对：详细设计标 [待用户确认]，testing 阶段真机回归数据校准
- **R-2**：CI 性能 5s 守门可能在大仓库扩展时退化 / 应对：F-013 加 fixture 仓 1000 文件回归 + benchmark 守门，超时自动 fail
- **R-3**：W002/W003 sourcing 规则与 design spec 文档兼容性（修复时反复触发）/ 应对：本期 fix Bug-22（review-F-NNN 命名豁免）+ 在 design spec 中规范使用「来源：path:line」格式

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 <决策标题>
- **Context**：做决策时的背景 / 约束
- **Decision**：选了什么，没选什么
- **Consequences**：好的后果、不好的后果
- **时间**：YYYY-MM-DD HH:MM:SS
- **Supersedes**：D-NNN（废弃前一决策时才有）
