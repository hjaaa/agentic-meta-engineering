# AgenticMetaEngineering

基于 Claude Code 的团队级 Agentic Engineering 工程骨架。`git clone` 即具备全部能力。

一个把"上下文质量"工程化的仓库：Commands 封装入口，Skills 封装方法，Agents 做专项，Hooks 和校验脚本守底。AI 承担需求研发主体，人类做方向引导和验证。

## 两条协作路径（先选再做）

| 场景 | 路径 | 入口 |
|---|---|---|
| 单文件改动 / bug 修复 / 工具补丁 / 文档润色 | **直通分支** | `git checkout -b feat/xxx` → 改 → `/code-review` → `gh pr create` |
| 跨文件 / 新功能 / 架构影响 / 需跨会话恢复 / 需追溯链 | **完整需求** | `/requirement:new <标题>` → 8 阶段推进 → `/requirement:submit` |

三问判断：**需要跨会话恢复 / 正式设计评审 / 需求-设计-代码-测试追溯链**？任一 yes → 完整需求；全 no → 直通分支。

详见 `context/team/onboarding/agentic-engineer-guide.md`。

## 当前能力

- **需求全生命周期**：8 阶段状态机 + 强制门禁（`/requirement:*` 共 8 个命令）
- **多 Agent 代码审查**：8 专项 checker（security / complexity / concurrency / error-handling / performance / design-consistency / history-context / auxiliary-spec）→ `review-critic` 对抗验证 → `code-quality-reviewer` Judge 综合裁决
- **团队知识沉淀**：`/knowledge:*` 五件套（extract-experience / generate-sop / generate-checklist / optimize-doc / organize-index）
- **两条硬规则的工程化**：`check-sourcing.sh` 执行"刨根问底"，`post-dev-verify.sh` 做 feature done 总门禁
- **自动机制（Hook）**：
  - `protect-branch` — `main/master/develop` 上直接写会被阻断
  - `auto-progress-log` — `process.txt` 由 Hook 自动追加
  - `stop-session-save` — 会话结束打 `SESSION_END` 标记，支撑 `/requirement:continue`
- **MCP 模板**：`.mcp.json.example`，默认不启用，`cp` 后生效

能力数字和缺口快照见 `context/team/engineering-spec/roadmap.md`（以目录实际内容为唯一事实源）。

## 和 AI 协作的两条硬规则

1. **刨根问底**：每条关键信息必须有引用、或标记"待确认"（由 `check-sourcing.sh` 校验）
2. **渐进式披露**：先输出 3-5 条关键点，用户确认后再出完整文档

详见 `context/team/ai-collaboration.md`。

## 快速开始

**新人（3 小时摸清体系）**
1. `git clone <repo-url>`
2. 读 30 秒版：`context/team/onboarding/agentic-engineer-guide.md`
3. 跟 learning-path 走：`context/team/onboarding/learning-path/01-environment.md` → `08-custom-skill.md`
4. 卡住就 `/agentic:help`

**老手（5 分钟开干）**
- 小改动 → `git checkout -b feat/xxx` → `/code-review`
- 完整需求 → `/requirement:new <标题>`
- 忘了命令 → `/agentic:help`

## 目录结构

```
.claude/           — Claude Code 扩展（Commands / Skills / Agents / Hooks）
context/
├── INDEX.md       — 根索引（渐进式检索第一跳）
├── team/          — 团队通用（协作规范 / Git / 工具链 / onboarding / 经验沉淀 / engineering-spec）
└── project/<X>/   — 项目 X 专属（按需创建）
requirements/      — 单个需求的全周期产出（meta / artifacts / notes / process）
scripts/           — 工程自检脚本（check-meta / check-index / check-sourcing / post-dev-verify）
```

## 设计与规范入口

- 路线图与能力快照：`context/team/engineering-spec/roadmap.md`
- 迭代 SOP：`context/team/engineering-spec/iteration-sop.md`
- 设计指导原则（四层架构 / 上下文工程 / 复利工程）：`context/team/engineering-spec/design-guidance/`
- 工具设计规范（Command / Skill / Subagent）：`context/team/engineering-spec/tool-design-spec/`
- 早期设计留档：`context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md`
