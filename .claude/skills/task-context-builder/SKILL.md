---
name: task-context-builder
description: 阶段 7 开发实施时，为单个 feature_id 构建精准的开发上下文——从 features.json、detailed-design.md、相关代码中按规则提取关键信息，避免把整份设计塞给 AI 导致走神。
---

## 什么时候用

阶段 7（开发实施）中，开发者开始做某个 feature_id 时。

## 核心流程

1. **读取输入**：feature_id（来自 features.json 或用户指定）
2. **三源提取**（按 `reference/extract-rules.md` 规则）：
   - `artifacts/features.json` → 该 feature 的 title、description、接口清单
   - `artifacts/detailed-design.md` → 匹配 feature_id 的设计段落（用 `@feature:id` 锚点或标题匹配）
   - 代码库 → 该 feature 可能触及的文件（通过 grep 接口名/数据结构）
3. **输出精简上下文**：
   - 目标：Agent 开发该 feature 所需的所有信息
   - 非目标：整份设计文档、整个代码库结构
   - **必须在"基本信息"段透出**：`complexity`、`interfaces_frozen`、`touches`、`depends_on_features`（与其 status）——这四项是 `feature-lifecycle-manager` 派发 subagent 时选模型档位、判前置依赖、约束触及范围的机读入口，缺一不可

## 硬约束

- ❌ 禁止提取与当前 feature_id 无关的内容（会浪费上下文）
- ❌ 禁止直接把大文件整段拉进主对话
- ✅ 摘要总长 < 3000 token（主 Agent 主对话预算的一部分）
- ✅ 所有引用带文件路径+行号，方便 Agent 按需深入
- ✅ 输出里必须显式写出"建议模型档位"（由 `complexity` 按映射推导），即使 `complexity` 缺失也要写 "medium（缺省）→ sonnet"

## 参考资源

- [`reference/extract-rules.md`](reference/extract-rules.md) — 提取规则与示例
