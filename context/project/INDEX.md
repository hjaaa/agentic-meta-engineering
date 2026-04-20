# 项目级知识索引

当前无任何业务项目知识入库。新项目的第一个需求开发过程中，Agent 会自动向 `context/project/<项目名>/` 沉淀架构、业务规则、接口约定等。

## 如何创建新项目

1. 用 `/requirement:new` 创建第一个需求时，在 `meta.yaml` 的 `project` 字段指定项目名
2. 开发过程中 Agent 将自动在 `context/project/<项目名>/` 下创建 INDEX.md 和初始知识文件
3. 需求验收后通过 `/knowledge:extract-experience` 把关键知识从 `requirements/<id>/notes.md` 转化为长期记忆
