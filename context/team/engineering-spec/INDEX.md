# 体系自身规范索引

本目录是 Agentic Engineering 骨架的"元"知识——关于体系本身如何设计、如何迭代。

## 设计指导（不可随意修改，改动需全员评审）

- [`design-guidance/four-layer-hierarchy.md`](design-guidance/four-layer-hierarchy.md) — 四层设计层级与自主权边界
- [`design-guidance/context-engineering.md`](design-guidance/context-engineering.md) — 上下文工程原则
- [`design-guidance/compounding.md`](design-guidance/compounding.md) — 复利工程原则
- [`design-guidance/hook-fail-open.md`](design-guidance/hook-fail-open.md) — Hook 必须区分业务 fail 与基础设施故障；后者 fail-open 防止反向 brick 工具链
- [`design-guidance/gate-system-architecture.md`](design-guidance/gate-system-architecture.md) — 门禁系统架构：热路径 / 低频路径分离、CLAUDE_GATES_GLOBAL_BYPASS 全局逃生、异步 audit（兼 A+B 重构 spec，待实施）

## 工具设计规范

- [`tool-design-spec/command-spec.md`](tool-design-spec/command-spec.md) — Command 硬约束（< 100 行）
- [`tool-design-spec/skill-spec.md`](tool-design-spec/skill-spec.md) — Skill 硬约束（SKILL.md < 2k token）
- [`tool-design-spec/subagent-spec.md`](tool-design-spec/subagent-spec.md) — Subagent 硬约束（返回 < 2k token，禁止嵌套）

## 数据格式约定

- [`time-format.md`](time-format.md) — 写入时间戳统一格式（`YYYY-MM-DD HH:MM:SS` / Asia/Shanghai）+ 向后兼容规则
- [`meta-schema.yaml`](meta-schema.yaml) — `requirements/<id>/meta.yaml` 的字段 schema / 枚举 / 条件必填
- [`review-schema.yaml`](review-schema.yaml) — `requirements/<id>/reviews/*.json` 的字段 schema / 枚举 / CR 规则
- [`receipt-schema.yaml`](receipt-schema.yaml) — `requirements/<id>/artifacts/tasks/<F-xxx>.receipt.json` 的字段 schema / 枚举 / 条件必填（F-001 新增）
- [`features-schema.yaml`](features-schema.yaml) — `requirements/<id>/artifacts/features.json` 的字段 schema / 枚举 / 必填规则（F-002 新增；status 字段不在此 schema，见 detailed-design §2.1.1）

## 迭代方式

- [`iteration-sop.md`](iteration-sop.md) — 项目迭代 SOP
- [`roadmap.md`](roadmap.md) — 骨架当前能力快照 + 未实现缺口
- [`plans/INDEX.md`](plans/INDEX.md) — 实施计划目录（活计划 + 历史归档）

## 历史设计文档

- [`specs/`](specs/) — 所有重要设计决定的存档
