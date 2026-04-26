# 跨项目经验索引

随团队开发经验积累，每条沉淀为一个 Markdown 文件。

## 已沉淀

- [`squash-merge-archive-needs-second-pr.md`](squash-merge-archive-needs-second-pr.md) — PR squash merge 后归档信息（phase=completed / completed_at）必须开二次 chore PR，因为 mergedAt 只能合并后取
- [`traceability-gate-error-code-tc-coverage.md`](traceability-gate-error-code-tc-coverage.md) — `development → testing` 门禁易暴露错误码 TC 缺口；开发期同步加 TC 是主防线，门禁是兜底
- [`spec-drift-consumer-aligns-with-producer.md`](spec-drift-consumer-aligns-with-producer.md) — 规范说 X 在路径 P 但工具写到 Q 时，改消费方对齐产出方，不反向搬位置
- [`ai-skips-realtime-notes-during-flow.md`](ai-skips-realtime-notes-during-flow.md) — auto mode 下 AI 推进流程时易漏 `/note`，process.txt 流水给假阳性安心感；需流程嵌入 / hook 强校验 / SessionEnd 兜底

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
