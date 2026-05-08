---
name: definition
node_id: req-quality-review
version: 1.0.0
---

# 需求定义阶段（definition）

阶段 2：requirement-definition

本阶段包含以下节点：
- `req-input-normalize`（skill）：规范化用户输入的原始需求标题/描述
- `req-draft`（skill）：生成结构化需求文档 `requirement.md`
- `req-quality-review`（agent）：六维评审（完整性/一致性/可追溯性/清晰度/可测性/业务合理性）
- `req-artifact-check`（artifact）：校验 requirement.md 必填章节与来源标注
- `req-signoff`（approval）：人工确认需求文档
- `phase-to-tech-research`（bash）：写 phase 字段，触发阶段迁移

本阶段所有 AI 工作节点均为 skill/agent 引用，prompt 由各 Skill/Agent 定义文件管理。
此文件为阶段占位 prompt，标识本阶段的语义边界。
