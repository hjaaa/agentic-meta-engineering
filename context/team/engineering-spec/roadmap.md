# 骨架路线图

> 最近更新：2026-04-27

项目当前能力快照 + 尚未实现的缺口 + 随规模演进的计划。给贡献者看，不是 AI 运行时上下文。

## 当前能力清单

Phase 1-4 已完成（截至 2026-04-21，REQ-2026-001 端到端验收通过）。

- Commands：15 个（`.claude/commands/`，含 `requirement:* / knowledge:* / agentic:* / code-review / note`；已下线 `/agentic:feedback`，见 `specs/2026-04-23-retire-agentic-feedback.md`）
- Skills：10 个（`.claude/skills/`）
- Agents：21 个（`.claude/agents/`）
- Hooks：3 个（`protect-branch` / `auto-progress-log` / `stop-session-save`）
- MCP：见 `.mcp.json.example`（候选：context7、chrome-devtools；默认不启用，按需 `cp` 为 `.mcp.json`）

> 数字以目录实际内容为准。本清单是快照，腐化时以目录为唯一事实源。

## 未实现清单（骨架留白）

以下是文章原版有、本骨架**暂不实现**的能力。

### Command 缺口（11 个）

全为文章原版中对应内部业务的命令，本骨架未迁移。`/requirement:submit` 已于 2026-04-21 落地，不在缺口之列。

### Skill 缺口（17 个）

- 业务配置生成类（如 `config-gen-engine`）
- `managing-code-review`（伞形） — 当 `/code-review` 逻辑超 100 行时加
- `mcp-setup-guide`
- `ai-collaboration-primer`
- 其余按"真问题驱动才加"原则

### Agent 缺口（2 个）

文章 5.1 图表之外的阶段级 Agent。本骨架的 21 个已覆盖所有明确图表中的 Agent（含 Phase 4 新增 `history-context-checker`）。

### MCP 缺口

- Jira / 飞书 / DingTalk 替换：未开箱
- 内部 TAPD / iWiki / 企微：无法外部重建

---

## 规模演进规划（知识检索）

项目采用 **agentic search** 路线（Agent 主动读 INDEX + 精读 md，不用 RAG / 向量库）。这套机制在当前规模跑得好，但规模上升会遇到瓶颈。本节记录分档计划，**只在对应规模信号出现时启动**，避免过早复杂化。

### 规模档位

| 档位 | Markdown | requirements | 典型瓶颈 | 应做的事 |
|---|---|---|---|---|
| **S1 当前** | < 100 | < 10 | 几乎没有 | 维持现状 |
| **S2 起步** | 100-300 | 10-50 | INDEX 腐化、命名歧义 | 索引自动化校验 CI + meta.yaml 字段扩展 |
| **S3 规模化** | 300-800 | 50-200 | grep 粗、第一跳难 | 标题级索引 + 反向索引 + 强制经验抽取 |
| **S4 大规模** | 800-2000 | 200-500 | 跨需求复用失效 | lessons-learned 按主题归并 + 术语表 |
| **S5 失控前夜** | 2000+ | 500+ | agentic search 本身贵 | 分层 Agent + 静态索引，**可选**引入 hybrid 检索做粗筛 |

### 四个主要瓶颈与应对

| 瓶颈 | 出现档位 | 应对 |
|---|---|---|
| INDEX.md 人肉维护失效（遗漏、腐化、链接失效） | S2 | CI 自动校验（只报告不自动改）。详见 [specs/2026-04-22-index-meta-validation-design.md](specs/2026-04-22-index-meta-validation-design.md) |
| 需求 meta.yaml 缺语义标签，跨需求查找只能扫 title | S2-S3 | meta.yaml 扩展 `feature_area / change_type / affected_modules / outcome` 等字段。详见同上 spec |
| grep 粗、同义词不召回、标题层级被忽略 | S3-S4 | 抽取标题/符号表做结构化索引（对齐 Cursor 的 tree-sitter 思路），维护术语表 |
| 经验无法跨需求复用、同一个坑踩多次 | S3-S4 | `done` 前强制 `/knowledge:extract-experience`，结果按主题归并到 `context/team/engineering-spec/lessons-learned/<topic>.md` |

### Hybrid 检索的定位（S5 才考虑）

**不是默认方案，是规模逼到不得不做时的妥协。** 引入前提：纯 agentic search 已显著不够用（Agent 10+ 轮仍难命中 / 跨 500+ REQ 模糊查询频繁）。

副作用清单（任一重到无法接受就不做）：
- 违反"文档即记忆"第一原则（引入向量库即引入版本漂移）
- 可解释性急剧下降（cosine 分数取代精确命中）
- 基础设施复杂度（embedding 管道、同步机制、rerank）
- 成本与 API 依赖（项目当前零外部依赖）
- Agent 主动导航能力退化

如果真到了 S5 且必须做，遵守"最小代价路径"：
1. 只对 `requirements/` 做，不对 `context/` 做
2. 每份 REQ 只存一个摘要向量，不切 chunk
3. 只做"候选召回"，召回结果永远不直接进主上下文
4. 封装成 subagent，Agent 按需调用而非默认路径

### 触发信号

不要按规模数字盲目演进，看实际痛点信号（满足任一即启动对应档位的工作）：

- PR review 连续 3 次发现 INDEX 未同步 → S2
- `context/**/*.md` 超过 100 份 → S2
- `requirements/` 超过 30 个 → S2-S3
- 同一个坑被不同 REQ 踩 2 次以上 → S3
- Agent 读 10+ 份 md 仍未命中目标 → S3-S4
- 单次知识检索任务 token 超 50k → S5
- grep 关键词结果 > 100 条 → S4-S5

### 当前档位评估（2026-04-22）

**位于 S1**，但 **S2 工具链已主动前置落地**（用户主动触发，非信号驱动）。详见 [specs/2026-04-22-index-meta-validation-design.md](specs/2026-04-22-index-meta-validation-design.md)。

已落地能力：
- `scripts/check-meta.sh` — 依据 `meta-schema.yaml` 校验 `requirements/*/meta.yaml`
- `scripts/check-index.sh` — 检测 INDEX 腐化 / 遗漏 / 孤岛 / 超长
- `scripts/git-hooks/pre-commit` — 本地 commit 时自动跑上述两个校验
- `.github/workflows/quality-check.yml` — CI 兜底
- `meta.yaml` schema 扩展：新增 `feature_area / change_type / affected_modules / tags / outcome / completed_at / lessons_extracted` 共 7 个字段

首轮存量 12 条 warning 已治理清零（新建 learning-path 白名单 + onboarding/common-pitfalls 和 plans/README 挂回父 INDEX），CI 已切 `--strict`——新增 warning 会直接红 CI，防止 INDEX 腐化增量复发。

### 守住的底线

无论演进到哪一档，下列四条必须不动（否则体系就换人设了）：
1. **文档即记忆**：任何索引都是派生物，可从 md 重建，不是独立真相
2. **位置即语义**：目录结构承担分类，不靠外部系统
3. **渐进式披露**：入口永远轻，深入靠 Agent 主动探索
4. **工具封装知识**：skill / agent 说"做什么"，不说"第一步…第二步"

---

## 门禁体系缺陷与演进（2026-04-27 盘点）

> 现状盘点见对话记录；本节只列"待办缺口 + 优先级"，不展开方案。具体方案进 `specs/` 或 `plans/`。

### 现状门禁层（已实现）

- Hook 层：`protect-branch`（PreToolUse 阻断主干写）
- CI 层：`check-meta` / `check-index` / `check-sourcing`（`--strict` 阻断式）
- 阶段切换层：`gate-checklist.md` 7 段（纯文本，靠 LLM 自觉执行）
- 评审层：4 个 reviewer Agent（`requirement / outline-design / detail-design / code-quality`，verdict 仅落主对话）
- 追溯链层：`traceability-gate-checker`（`development → testing` 触发）
- PR 提交层：`/requirement:submit` 内置 7 项校验

### 已识别缺陷（按优先级）

| # | 缺陷 | 影响 | 状态 |
|---|---|---|---|
| G1 | CI 缺 build / test / lint 兜底，`/code-review` 的 approved 全凭 LLM 自评 | 高——可能放过编译/语法错 | 待规划 |
| G2 | `check-*` strict 校验只在 CI 跑，本地 commit 不拦，绕一圈 PR 才发现 | 中——浪费迭代 | 待规划 |
| G3 | **Reviewer verdict 仅在主对话，未持久化为机器可读结构；阶段切换"verdict ≠ rejected"靠 LLM 自觉** | 高——评审形同虚设 | **brainstorming 中** |
| G4 | `testing → completed` 仅校验 test-report.md 存在，不校验测试是否真的通过 | 高——可伪造完成 | 待规划 |
| G5 | 逃生口（`--force-with-blockers` 等）无统一审计，谁绕过、绕了什么不可追溯 | 中——治理盲区 | 待规划 |
| G6 | GitHub branch protection 与 `protect-branch` hook 是否对齐未声明，存在 Bash/远端绕过路径 | 中——hook 可被绕 | 待核查 |

### 次级缺陷（先记下，不一定做）

- 4 个 design reviewer 无 critic 对抗（仅 `/code-review` 有 review-critic）
- `gates_passed[]` 只记 pass，不记 fail 次数 / 原因 / 谁触发
- `traceability-consistency-checker` 的"接口签名一致性"跨语言实现路径未明
- 阶段 1→2 / 3→4 / 6→7 的门禁覆盖偏弱
- `settings.local.json` 旁路无团队层告警

### 推进原则

- 不一次性大改，按 G1~G6 分别拆 PR
- 任何门禁强化必须先在 non-strict / warning 模式跑 1~2 周，再升 strict
- 历史需求采用 `legacy: true` 标记跳过新校验，不强制回填
