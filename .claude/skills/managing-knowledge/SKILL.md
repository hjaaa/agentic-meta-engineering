---
name: managing-knowledge
description: 知识管理伞形 Skill，5 个 /knowledge:* 命令共用。根据子意图（extract-experience / generate-sop / generate-checklist / optimize-doc / organize-index）分发到对应 reference/ 文件的规则执行。
---

## 什么时候用

用户触发 5 个 `/knowledge:*` 命令之一，或口头说"提炼经验 / 生成 SOP / 生成检查清单 / 优化文档 / 整理索引"时。

## 核心流程

1. **识别子意图**（5 选 1）
2. **加载对应规则**：`reference/<sub>.md`
3. **执行规则**：每个 sub 的流程不同，见对应 reference
4. **输出候选产物**（渐进式：先给结构+几条样例，等用户确认再出完整内容）
5. **确认后落盘**：写入 `context/project/` 或 `context/team/experience/`

## 硬约束

- ❌ 禁止跳过"渐进式确认"直接写文件
- ❌ 禁止沉淀不满足"三必要条件"的内容（见 `compounding.md`）
- ✅ 每次沉淀都要问：跨需求重复？AI 反复错？跨会话需保留？— 至少满足一条
- ✅ 新写的文件必须更新对应 `INDEX.md`

## 参考资源（按子命令）

- [`reference/extract-experience.md`](reference/extract-experience.md) — 从 notes.md 提取经验
- [`reference/generate-sop.md`](reference/generate-sop.md) — 从实践生成 SOP
- [`reference/generate-checklist.md`](reference/generate-checklist.md) — 生成检查清单
- [`reference/optimize-doc.md`](reference/optimize-doc.md) — 优化已有文档
- [`reference/organize-index.md`](reference/organize-index.md) — 整理目录索引
