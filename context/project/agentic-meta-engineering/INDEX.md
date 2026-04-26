# 项目知识索引 · agentic-meta-engineering

本仓库即项目本体（骨架元仓库）。下面是骨架自身相关的项目级知识入口。

## 文件清单

- [areas.yaml](areas.yaml) — 骨架功能区白名单（驱动 `meta.yaml.feature_area` 校验）

## 备注

- 骨架本身是「面向开发流程」的项目，没有业务域（auth/payment 等）；`areas.yaml` 列的是骨架自身的功能区（hooks / commands / skills / agents 等）
- 当 fork 此骨架到具体业务项目时，应在 `context/project/<新项目名>/` 下重建 `areas.yaml`，列业务域而不是功能区
