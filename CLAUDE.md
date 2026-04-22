# 项目级 Claude Code 指令

本仓库是 Agentic Engineering 工程骨架。克隆即具备骨架能力，按 `context/team/onboarding/agentic-engineer-guide.md` 上手。

## 仓库布局

- `.claude/` — Commands / Skills / Agents / Hooks 定义（工具层）
- `context/team/` — 团队通用知识（规范、协作准则、onboarding）
- `context/project/<X>/` — 项目 X 专属知识（按需创建）
- `requirements/<REQ-ID>/` — 单个需求的全周期产出（meta / artifacts / notes）

## 常用入口

| 想做什么 | 用什么 |
|---|---|
| 开一个新需求 | `/requirement:new <标题>` |
| 恢复之前的需求 | `/requirement:continue` |
| 看当前阶段/进度 | `/requirement:status` |
| 做代码审查 | `/code-review` |
| 提 PR | `/requirement:submit` |
| 卡住了/不确定 | `/agentic:help` |

全量命令见 `.claude/commands/`；详细 SOP 见 `context/team/onboarding/agentic-engineer-guide.md`。需求按 8 阶段推进（初始化 → 需求定义 → 技术预研 → 概要设计 → 详细设计 → 任务规划 → 开发实施 → 测试验收），`/requirement:next` 逐阶段切换并触发门禁。

## 自动机制（Hook）

- `protect-branch` — 在 `main/master/develop` 上直接做 Edit/Write/Bash 写操作会被阻断；改代码前先切 feature 分支
- `auto-progress-log` — 当前需求的 `process.txt` 由 Hook 自动追加，不要手工维护
- `stop-session-save` — 会话结束自动打 `SESSION_END` 标记，支撑 `/requirement:continue` 跨会话恢复

## 四条硬原则

1. **文档即记忆**：人和 AI 读同一份 Markdown
2. **位置即语义**：路径承载分类信息，不依赖元数据
3. **渐进式披露**：入口轻量，按需检索。禁止盲目 glob 全部 `context/`
4. **工具封装知识，不封装流程**

详见 @context/team/engineering-spec/design-guidance/context-engineering.md

## 和 AI 协作的基本法

@context/team/ai-collaboration.md

## 团队规范

- Git：@context/team/git-workflow.md
- 工具链：@context/team/tool-chain.md

## 体系自身

- 知识库根索引：`context/INDEX.md`（渐进式检索的第一跳）
- 设计指导：`context/team/engineering-spec/design-guidance/`（四层架构 / 上下文工程 / 复利工程）
- 工具规范：`context/team/engineering-spec/tool-design-spec/`（Command / Skill / Subagent）
- 迭代 SOP：`context/team/engineering-spec/iteration-sop.md`
