# 上下文工程原则

整个体系是围绕一个简单公式设计的：

```
AI 输出质量 = AI 能力 × 上下文质量
```

AI 能力由模型决定，我们能控制的是**上下文质量**。

## 四条核心原则

### 1. 文档即记忆

人和 AI 读**同一份** Markdown。不维护双轨（给人的 Wiki + 给 AI 的向量库）。原因：

- 避免版本漂移（改了一份忘另一份）
- 高频使用对抗腐化：文档过时 → AI 出错 → 立刻被发现并修正
- 团队协作的知识对齐零成本：`git clone` 即获得完整记忆

### 2. 位置即语义

文件放在哪个目录，Agent 就知道它是什么：

- `context/team/` — 团队通用
- `context/project/<X>/` — 项目 X 专属
- `context/team/engineering-spec/` — 体系自身
- `requirements/<id>/artifacts/` — 单个需求的全周期产出

不使用元数据标签、不使用外部索引数据库。路径本身承载分类信息。

### 3. 渐进式披露（Agentic Search）

入口轻量，按需深入。

- `CLAUDE.md` < 200 行（根索引）
- `SKILL.md` < 2k token（技能入口）
- 详细知识放 `reference/`，真需要才读

目的：**主对话上下文是稀缺资源**，任何预加载的信息都在消耗认知带宽。

### 4. 工具封装知识，不封装流程

Skill 给 Agent 的是"做什么 + 注意什么"，不是"第一步…第二步…"。

- ❌ "1. 读 requirement.md → 2. 找 services 字段 → 3. 对每个 service 运行 git diff"
- ✅ "定义 ReviewScope：它包含哪些字段、每个字段的语义、禁止遗漏的约束"

把 Agent 当有判断力的同事，不是 shell 脚本。

## 禁止盲目搜索

`universal-context-collector` 这个 Agent 的硬规则：**先读 INDEX.md，决定读什么，再读**。不允许 glob 一口气拉进来所有 `context/**/*.md`。

## 检索优先级

```
1. context/project/<当前项目>/*
2. context/project/<当前项目>/INDEX.md（先索引后深入）
3. context/team/engineering-spec/（体系规范）
4. context/team/*（团队通用）
5. 历史 requirements/*/artifacts/（类似需求参考）
6. 外部 WebSearch / WebFetch（最后手段，设计阶段禁用）
```
