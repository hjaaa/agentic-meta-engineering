---
name: tech-research
node_id: tech-feasibility-assess
version: 1.0.0
---

# 技术预研阶段（tech-research）

阶段 3：tech-research

本阶段包含以下节点：
- `tech-feasibility-assess`（agent）：技术可行性评估，产出 `tech-feasibility.md`
- `tech-research-artifact-check`（artifact）：校验 tech-feasibility.md 必填章节
- `tech-research-signoff`（approval）：人工确认技术预研结论
- `phase-to-outline-design`（bash）：写 phase + affected_modules 字段

评估维度：
1. 现有技术栈能否实现（列出涉及模块/组件）
2. 风险识别（技术风险 / 集成风险 / 性能风险 / 安全风险）
3. 工作量估算（人天，按 feature 拆分粒度）
4. 替代方案对比（如有）

本阶段所有 AI 工作节点均为 agent 引用，prompt 由 Agent 定义文件管理。
此文件为阶段占位 prompt，标识本阶段的语义边界。
