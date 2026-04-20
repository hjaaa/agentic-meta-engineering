# 跨项目经验索引

初始为空。随团队开发经验积累，每条沉淀为一个 Markdown 文件。

## 什么值得沉淀

仅当以下条件至少一条成立时创建经验文档：

- 跨项目重复出现的知识
- AI 反复犯同类错误的场景
- 跨会话/跨人需要保留的状态

## 反面：不要沉淀的

- 偶发问题（只踩过一次）
- 简单自然对话就能传递的信息
- 只对单个需求有价值的细节（留在该需求的 `notes.md`）

## 格式约定

每份文件：
- 文件名 `kebab-case.md`，描述具体场景（如 `mysql-lock-wait-timeout-in-long-transaction.md`）
- 正文不超过 200 字
- 必须包含：问题、根因、解法、验证方法

## 已有经验文档

| 文件 | 场景 | 沉淀时间 |
|---|---|---|
| `markdown-section-iteration.md` | 用 awk 遍历 Markdown 同级 section 的首尾边界问题 | 2026-04-20 |
| `phase-4-deferred-issues.md` | Phase 4 集成验收中未立即修复的 2 个观察项（G-02 Agent Task tool 调用、G-06 .review-scope.json gitignore） | 2026-04-20 |
