# Agentic 工程师入门指南

30 分钟读完；一周内跑通第一个需求。

## 一个认知转变

你的核心工作从"写代码"变成"引导上下文 + 验证结果"。

```
代码输出质量 = AI 能力 × 上下文质量
```

规范已预制在本仓库。你**不需要**告诉 AI "怎么做"——只需要告诉它"做什么"和"业务背景"。

## 一条最小行动路径（5 步）

1. **说出场景** — "我要开发一个新需求" / "继续之前的需求" / "帮我审查一下这段代码"
2. **提供业务上下文** — Jira/TAPD 链接、业务规则、关注的代码位置
3. **让 AI 按规范推进** — 它会自动阶段检查、更新状态
4. **验证与纠偏** — 看输出，有问题就**具体**反馈（不是"感觉不对"，要"在 X 文件 Y 行，期望 Z 但看到 W"）
5. **确认沉淀** — `notes.md` 和 `context/` 按需更新了吗

## 第一周目标

用这个流程完成 **1 个小需求**（< 1 人天）。不追求用上所有功能。

## 第一次跑起来（Phase 1 完成后可执行）

### 环境（5 分钟）

1. 安装 Claude Code（官方文档）
2. 克隆本仓库
3. 打开终端，进入仓库目录，运行 `claude`

### 验证

- 终端底部应有状态行显示 `[no-requirement] <branch>`
- 输入 `/agentic:help` 应看到帮助（Phase 2 后）

### 第一条练习

**Phase 1 阶段**：只能读文档。跟着 `learning-path/01-environment.md` 做。
**Phase 2 阶段后**：运行 `/requirement:new` 开始你的第一个小需求。

## 之后去哪

按顺序完成：

- [`learning-path/01-environment.md`](learning-path/01-environment.md) — 环境准备
- [`learning-path/02-first-conversation.md`](learning-path/02-first-conversation.md) — 和 AI 对话的基本法
- [`learning-path/03-command-skill-agent.md`](learning-path/03-command-skill-agent.md) — 三级工具区别
- [`learning-path/04-first-requirement.md`](learning-path/04-first-requirement.md) — 完整跑通 8 阶段（Phase 2/3 后）
- [`learning-path/05-code-review.md`](learning-path/05-code-review.md) — 代码审查（Phase 2/3 后）
- [`learning-path/06-knowledge-sinking.md`](learning-path/06-knowledge-sinking.md) — 知识沉淀（Phase 2/3 后）

前 6 阶段必修。走完即具备独立使用能力。

## 哪里遇到问题

1. 先运行 `/agentic:help` 看 FAQ
2. 读 `ai-collaboration.md`
3. 问有经验的同事
4. `/agentic:feedback` 把问题提给团队（会写入 `context/team/feedback-log.yaml`）
