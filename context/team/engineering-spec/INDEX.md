# 体系自身规范索引

本目录是 Agentic Engineering 骨架的"元"知识——关于体系本身如何设计、如何迭代。

## 设计指导（不可随意修改，改动需全员评审）

- [`design-guidance/four-layer-hierarchy.md`](design-guidance/four-layer-hierarchy.md) — 四层设计层级与自主权边界
- [`design-guidance/context-engineering.md`](design-guidance/context-engineering.md) — 上下文工程原则
- [`design-guidance/compounding.md`](design-guidance/compounding.md) — 复利工程原则

## 工具设计规范

- [`tool-design-spec/command-spec.md`](tool-design-spec/command-spec.md) — Command 硬约束（< 100 行）
- [`tool-design-spec/skill-spec.md`](tool-design-spec/skill-spec.md) — Skill 硬约束（SKILL.md < 2k token）
- [`tool-design-spec/subagent-spec.md`](tool-design-spec/subagent-spec.md) — Subagent 硬约束（返回 < 2k token，禁止嵌套）

## 数据格式约定

- [`time-format.md`](time-format.md) — 写入时间戳统一格式（`YYYY-MM-DD HH:MM:SS` / Asia/Shanghai）+ 向后兼容规则
- [`meta-schema.yaml`](meta-schema.yaml) — `requirements/<id>/meta.yaml` 的字段 schema / 枚举 / 条件必填

## 迭代方式

- [`iteration-sop.md`](iteration-sop.md) — 项目迭代 SOP
- [`roadmap.md`](roadmap.md) — 骨架当前能力快照 + 未实现缺口
- [`plans/README.md`](plans/README.md) — 实施计划目录（活计划 + 历史归档）

## 历史设计文档

- [`specs/`](specs/) — 所有重要设计决定的存档
