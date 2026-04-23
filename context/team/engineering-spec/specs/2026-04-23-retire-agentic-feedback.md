# 下线 /agentic:feedback 命令

> 日期：2026-04-23
> 类型：系统瘦身（工具层删除）
> 分支：feature/retire-agentic-feedback

## 决策

删除 `/agentic:feedback` 命令及其写入目标 `context/team/feedback-log.yaml`。

## 原因

系统瘦身。该命令的实际使用频率极低，且反馈收集的需求可通过直接沟通（PR 评论、口头、文字）覆盖，无需专用命令 + YAML 文件。维护一个几乎为空的 `feedback-log.yaml` 反而增加认知负担。

对照 `iteration-sop.md` 的工具化六条判断：
- 条件 ③（高频重复 > 每周）：**不满足**，实际从未被写入
- 条件 ① ②（强制约束 / 易错）：**不适用**
- 结论：不具备保留价值，删除

## 变更范围

| 文件 | 操作 |
|---|---|
| `.claude/commands/agentic/feedback.md` | 删除 |
| `context/team/feedback-log.yaml` | 删除 |
| `README.md` | 删除 `## 反馈` 整节 |
| `context/team/INDEX.md` | 删除 `## 运行态` 及 `feedback-log.yaml` 条目 |
| `context/team/engineering-spec/iteration-sop.md` | 删除表格中"用户反馈建议 → 读 feedback-log.yaml"行 |
| `context/team/onboarding/agentic-engineer-guide.md` | 删除"哪里遇到问题"列表最后一条 `/agentic:feedback` |
| `.claude/commands/agentic/help.md` | 删除默认输出中 `/agentic:feedback` 提示行 |
| `context/team/engineering-spec/roadmap.md` | 更新命令数 16 → 15，标注本次下线 |

## 历史文件处理

`context/team/engineering-spec/plans/history/` 及 `specs/` 下的历史设计快照保持原样——历史文件记录"当时的决定是什么"，不应回溯修改。
