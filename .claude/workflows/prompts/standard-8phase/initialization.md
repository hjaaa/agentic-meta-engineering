---
name: initialization
node_id: bootstrap-validate
version: 1.0.0
---

# 初始化阶段（initialization）

阶段 1：bootstrap-validate

本阶段由引擎在加载 yaml 之前完成 bootstrap 实操（建目录、生成 REQ-ID、切分支、写 meta.yaml 骨架），
workflow 内的 `bootstrap-validate` 节点只做校验：确认 meta.yaml 与 plan.md 已存在且 schema 合法。

本阶段无需 AI 生成内容，校验通过即进入阶段 2（需求定义）。
