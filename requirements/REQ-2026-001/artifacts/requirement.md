---
id: REQ-2026-001
title: 会话结束经验提取 Hook
created_at: "2026-04-26 09:30:00"
refs-requirement: true
---

# REQ-2026-001 · 会话结束经验提取 Hook

## 背景

本骨架对照源文章《认知重建之后，步入 Agentic Engineering 的工程革命》（参考文章，无项目内引用）做了能力对照：现有骨架已具备「文档即记忆」「位置即语义」「渐进式披露」「禁止盲目搜索」「刨根问底」等原则的工具落地，但 **Hook 维度只有 `protect-branch` 一例**（来源：.claude/settings.json:30），缺少把会话价值沉淀回 `requirements/<id>/notes.md` 的自动化机制。

历史上曾存在 Hook 写 `[SESSION_END]` 进 `process.txt` 的方案，已被显式废弃（来源：.claude/skills/requirement-progress-logger/SKILL.md:60）。本需求采用**完全不同的方向**：不再写 `process.txt`，而是把"经验/坑点/决策"以人类可读的小节形式追加到 `notes.md`，与现有 `/note` 命令、`/knowledge:extract-experience` 形成闭环。

> 假设：「复盘流于形式」是真实痛点，AI 协作场景下的经验流失主要发生在"会话结束-记忆消散"瞬间 [待补充]
> - 内容：约 70%+ 的可沉淀经验在用户主动 `/note` 之前就被遗忘
> - 依据：源文章「AI slop」论述 + 团队对 `notes.md` 实际填充率的观察（无量化数据）
> - 风险：若实际沉淀率不低，则本 Hook 价值有限，沦为噪声
> - 验证时机：上线后 2 周观察 `notes.md` 增量字数 / 经验条目数

## 目标

- 主目标：在 Claude Code `SessionEnd` 时**自动**抽取本轮对话中的经验/坑点/决策，追加到当前需求的 `requirements/<id>/notes.md`，**对用户透明、不阻塞退出**（来源：requirements/REQ-2026-001/plan.md:3）
- 次要目标：
  - 仅对"需求开发会话"生效，不污染非需求会话
  - 失败/超时静默降级，绝不影响用户正常退出
  - 产物格式可被未来的 `/knowledge:extract-experience` 解析并 promote 到 `context/team/experience/`

## 用户场景

### 场景 1：正常需求会话结束 ✅
- **角色**：需求开发工程师
- **前置**：当前分支 `feat/req-<ID>`，对应 `requirements/<ID>/meta.yaml` 存在；环境变量 `SKIP_EXPERIENCE_HOOK` 未设为 `1`
- **主流程**：用户 `/clear` 或关闭 Claude Code → SessionEnd 触发 → Hook 在后台 fire-and-forget 调 `claude -p` 起小 Agent 分析最近对话 → 30 秒内完成则把抽取结果以 `## 会话经验（YYYY-MM-DD HH:MM）` 小节追加到 `notes.md`
- **期望结果**：用户感知不到 Hook 运行；下次 `/requirement:continue` 时可在 `notes.md` 看到上次会话的沉淀

### 场景 2：非需求分支会话结束（不应触发） ✅
- **角色**：工程师在 `develop` / `hotfix/*` / 其它非 `feat/req-*` 分支
- **主流程**：SessionEnd 触发 → Hook 检测当前分支不匹配正则 → 静默 exit 0
- **期望结果**：无文件写入，无报错

### 场景 3：分支匹配但 meta.yaml 缺失（防御性退出） ✅
- **角色**：工程师在临时建的 `feat/req-XXX` 分支，但还没走 `/requirement:new`
- **主流程**：分支匹配 → 检查 `requirements/<id>/meta.yaml` → 不存在 → 静默 exit 0
- **期望结果**：无文件写入，无报错

### 场景 4：claude -p 失败 / 超时 ✅
- **角色**：用户网络不可用 / API 限流 / 调用超过 30 秒
- **主流程**：Hook 子进程超时被杀 / 非零退出 → 父进程 catch 住 → 在 `notes.md` 追加一行 `## 会话经验（YYYY-MM-DD HH:MM）\n_[hook-skipped: <reason>]_` → 不向用户报错
- **期望结果**：用户退出无延迟；后续翻 notes.md 能看到一条审计痕迹（便于排查 Hook 失效）

### 场景 5：opt-out 通过环境变量 ✅
- **角色**：用户当次会话不希望被记录（敏感信息 / 调试态）
- **前置**：启动 Claude Code 前 `export SKIP_EXPERIENCE_HOOK=1`
- **主流程**：SessionEnd 触发 → Hook 第一行检测变量 → 静默 exit 0
- **期望结果**：与场景 2 相同，无任何写入

## 功能需求

- **FR-1 触发器**：在 `.claude/settings.json` 的 `hooks.SessionEnd` 注册 `.claude/hooks/extract-experience.sh`（结构参考 `protect-branch` 的 PreToolUse 配置：来源：.claude/settings.json:27）
- **FR-2 守门条件**（按顺序短路退出）：
  1. `SKIP_EXPERIENCE_HOOK=1` → exit 0
  2. 当前分支不匹配 `^feat/req-` → exit 0
  3. 推断的 `requirements/<id>/meta.yaml` 不存在 → exit 0
- **FR-3 抽取调用**：`nohup claude -p "<extract-prompt>" --output-format text </dev/null >notes.tmp 2>&1 &`，30 秒后 `kill -9` 兜底
- **FR-4 写入策略**：成功 → 在 `notes.md` 末尾追加 `\n\n## 会话经验（YYYY-MM-DD HH:MM）\n<抽取内容>`；失败 → 追加同样的标题但正文为 `_[hook-skipped: <reason>]_`
- **FR-5 抽取 Prompt 模板**：写入 `.claude/hooks/extract-experience.prompt.md`，包含「目标 / 输出格式 / 截断说明」三段，便于团队调优
- **FR-6 transcript 截断**：`claude -p` 入参中只保留**最近 30 轮 or 40K token，谁先到截断**（保守起步，上线后按效果调整）
- **FR-7 completed 状态短路**：守门第 4 步——若 `meta.yaml.phase` == `completed`，静默 exit 0（需求已结束，新增 notes 价值低）
- **FR-8 process.txt 不参与**：本 Hook 不写 `process.txt`，避免事件白名单膨胀；审计依赖 `notes.md` 的 `## 会话经验` 小节本身

## 非功能需求

- **NFR-1 性能**：从 SessionEnd 触发到 Hook 子进程后台运行起来，**主进程阻塞 ≤ 100ms**（fire-and-forget 设计，来源：requirements/REQ-2026-001/plan.md:35）
- **NFR-2 可靠性**：claude -p 任何方式的失败都不能让用户感知到错误；超时上限 **30 秒**
- **NFR-3 兼容性**：仅依赖 Claude Code 内置 `SessionEnd` 事件 + `claude` CLI；不引入新依赖
- **NFR-4 可观测性**：失败时 `notes.md` 追加 `[hook-skipped: <reason>]`；成功时无额外日志（避免污染）；是否额外写 `process.txt` 见待澄清 OQ-3
- **NFR-5 安全**：Hook 脚本不读取 `.env` / 凭据文件；`claude -p` 不开 MCP/网络写权限（仅做文本抽取）

## 范围

- **包含**：
  - `.claude/settings.json` 的 SessionEnd hook 注册
  - `.claude/hooks/extract-experience.sh`（守门 + 调度脚本）
  - `.claude/hooks/extract-experience.prompt.md`（抽取 Prompt）
  - 单元/集成验证：用人造 transcript fixture 跑端到端
  - 文档更新：`context/team/onboarding/agentic-engineer-guide.md` 增"自动经验提取"小节（仅说明，不承诺指标）
- **不包含**（来源：requirements/REQ-2026-001/plan.md:15）：
  - 自动 promote 到 `context/team/experience/`（仍走人工 `/knowledge:extract-experience`）
  - 推送企微 / IM 消息
  - 对 `Stop` 事件（每轮 Agent 结束）做提取
  - 对非需求会话生效

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 触发事件 | Stop / SessionEnd / 两者 | **SessionEnd** | 用户首轮决策；Stop 太频繁会噪声化 |
| 生效范围 | 所有会话 / 仅需求会话 | **仅需求会话** | 用户首轮决策；非需求会话写需求 notes.md 没有意义 |
| 写入目标 | notes.md / experience/ / 双写 | **仅 notes.md** | 用户首轮决策；跨项目沉淀走人工 promote |
| 实现方式 | claude -p / 规则 grep / 下次会话提取 | **claude -p 小 Agent** | 用户首轮决策；规则 grep 无法捕捉决策类经验 |
| 写入格式 | 末尾纯文本 / 带标题小节 | **带 `## 会话经验（YYYY-MM-DD HH:MM）` 小节** | Q1=A；便于 `/knowledge:extract-experience` 解析 |
| 运行模式 | 同步等结果 / fire-and-forget / 无超时 | **fire-and-forget + 30s 超时** | Q2=A；最不打扰用户 |
| opt-out 载体 | 不要 / 环境变量 / meta.yaml 字段 | **环境变量 `SKIP_EXPERIENCE_HOOK=1`** | Q3=B；不污染 meta.yaml schema |
| 截断边界 | 30 轮/40K / 50 轮/60K / 按文件大小 | **30 轮 or 40K token（谁先到）** | OQ-1；保守起步，看效果再放宽 |
| completed 状态行为 | 仍提取 / 静默退出 | **静默退出** | OQ-2；需求已结束，新增 notes 价值低 |
| process.txt 审计事件 | 加 `[experience-extracted]` / 不加 | **不加** | OQ-3；避免白名单膨胀，审计看 notes.md 自身 |

## 风险与对策

| 风险 | 对策 |
|---|---|
| Hook 阻塞用户退出 | fire-and-forget 异步 + 100ms 主进程阻塞上限（NFR-1）|
| `claude -p` 调用失败 / 限流 | catch 非零退出 → 追加 `[hook-skipped: <reason>]`，不向用户报错（场景 4）|
| 污染非需求会话 notes.md | FR-2 三层守门（env / branch / meta.yaml）|
| transcript 过长爆上下文 | FR-6 截断策略（待初值确认）|
| 抽取内容质量低 / 噪声多 | Prompt 模板独立文件（FR-5），便于迭代调优；上线 2 周后回看 |
| 与已废弃的 `[SESSION_END]` Hook 概念混淆 | requirement.md 明确写"不写 process.txt"（来源：.claude/skills/requirement-progress-logger/SKILL.md:60）|

## 待澄清清单

截至 2026-04-26，原 OQ-1 / OQ-2 / OQ-3 已在主对话中拍板，结论已落入「关键决策记录」表。

仍需关注的事项：

1. 「背景」段中关于"复盘流于形式是真实痛点"的假设——已含完整四要素，验证时机为上线后 2 周回看 `requirements/*/notes.md` 的 `## 会话经验` 小节增量与质量。

无新增需要用户进一步确认的事项。

## 引用与来源

- `.claude/settings.json:27,30` — 现有 `protect-branch` Hook 注册位置，作为 SessionEnd Hook 注册的同构参考
- `.claude/skills/requirement-progress-logger/SKILL.md:49,60` — 事件标签白名单与已废弃 `[SESSION_END]` 标签
- `requirements/REQ-2026-001/plan.md:3,15,33-38` — 本需求的目标 / 范围 / 风险初稿
- `context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md` — 骨架设计原始 spec（背景对照）
- 公众号文章《认知重建之后，步入 Agentic Engineering 的工程革命》— 思想来源（外部，无项目内引用）
