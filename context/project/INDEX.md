# 项目级知识索引

## 已入库项目

- [agentic-meta-engineering](agentic-meta-engineering/INDEX.md) — 骨架元仓库自身（含 `areas.yaml`）

## 说明

业务项目的第一个需求开发过程中，Agent 会自动向 `context/project/<项目名>/` 沉淀架构、业务规则、接口约定等。

## 如何创建新项目

1. 用 `/requirement:new` 创建第一个需求时，在 `meta.yaml` 的 `project` 字段指定项目名
2. 开发过程中 Agent 将自动在 `context/project/<项目名>/` 下创建 INDEX.md 和初始知识文件
3. 首次建 `context/project/<项目名>/` 时，**必须同时创建 `areas.yaml`**（业务域白名单），模板见 `.claude/skills/managing-requirement-lifecycle/templates/areas.yaml.tmpl`
4. 需求验收后通过 `/knowledge:extract-experience` 把关键知识从 `requirements/<id>/notes.md` 转化为长期记忆

## 为什么每个项目要有 `areas.yaml`

- 驱动 `meta.yaml.feature_area` 字段的合法值校验（团队级 schema 见 `context/team/engineering-spec/meta-schema.yaml`）
- 业务域是项目维度的事，团队级不应该知道具体业务 —— 对齐"位置即语义"原则
- 为未来的反向索引（`by-area.json`）留锚点，详见 `context/team/engineering-spec/specs/2026-04-22-index-meta-validation-design.md`
