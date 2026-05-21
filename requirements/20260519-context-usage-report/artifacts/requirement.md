---
id: 20260519-context-usage-report
title: Context 知识利用率统计机制
created_at: 2026-05-19T15:30:00+08:00
refs-requirement: true
---

# 20260519-context-usage-report · Context 知识利用率统计机制

## 背景

当前 agentic-meta-engineering 仓库通过 `context/` 目录沉淀团队规范、项目知识和跨项目经验，`context/team/experience/` 下经验文件持续增长（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:9）。现有体系已经解决了三件事：知识放在哪里（`context/team/` 与 `context/project/<X>/` 的位置语义）、知识如何被发现（`INDEX.md` 渐进式披露）、经验如何沉淀（`/knowledge:extract-experience` 从 notes 抽取经验并更新 INDEX）（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:11）。

缺口在于：仓库目前只能看到「沉淀了哪些知识」，不能系统回答「哪些知识被后续需求发现、引用、应用，哪些知识长期没有使用证据」（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:17）。

经验文件数量继续增长会带来三类问题（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:17）：

1. 低价值或重复经验长期堆积，INDEX 变重，降低 Agent 检索效率。
2. 高价值经验没有被识别出来，无法升级为 checklist / SOP / 测试或门禁。
3. 孤岛文件、断链文件和过时文件只能靠人工偶然发现。

本需求引入一套轻量、可验证、可渐进增强的 Context 知识利用率统计机制（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:23）。

## 目标

- **主目标**：为 `context/` 下知识文件建立可解释的利用率统计口径，区分「可发现 / 被引用 / 被应用」三类强度的使用信号，生成 Markdown 与 JSON 报告，支持人工治理（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:25）。
- **次要目标**：
  - 先用离线扫描落地 MVP，不改变现有需求流、review 流和 archive 流（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:30）。
  - 复用「Markdown 即记忆、位置即语义、INDEX 先行、渐进式披露」原则，与 `scripts/lib/check_index.py` 共享解析规则避免语义漂移（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:31）。
  - 为后续接入统一检索打点、弱门禁和趋势分析预留扩展点（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:32）。

## 角色与场景

### 角色

- **知识治理人员**（团队 lead / engineering 维护者）：定期跑报告，治理孤岛 / 高价值 / 低利用率知识（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:543）。
- **Agent / AI 开发者**：希望在新需求里引用 context 时能命中已有高价值经验（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:18）。
- **仓库 maintainer**：希望新增 context 文件不会长期脱离 INDEX，保持知识可发现性（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:719）。

### 场景 1：治理决策（手动跑报告）

- 角色：知识治理人员
- 前置：仓库当前 `context/` 已经积累若干经验文件；`requirements/` 已经累积若干历史需求。
- 主流程：
  1. 知识治理人员在仓库根执行 `python3 scripts/lib/context_usage_report.py`（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:449）。
  2. 脚本扫描 `context/` 文件清单、`context/**/INDEX.md` 链接图、`requirements/**` 显式引用、git 历史（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:186）。
  3. 输出 `reports/context-usage.md` 与 `reports/context-usage.json`（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:267）。
- 期望结果：Markdown 报告含「总览 / 高价值知识 / 待治理知识 / 引用明细」四章；治理人员据此决定哪些经验合并、升级、归档或保留（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:389）。

### 场景 2：孤岛检测（INDEX 健康）

- 角色：仓库 maintainer
- 前置：开发者新增了 `context/team/experience/foo.md` 但忘记把它挂到对应的 `INDEX.md`。
- 主流程：
  1. 下次跑利用率报告。
  2. 报告检测到 `foo.md` 没有被任何 INDEX 链接（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:89）。
- 期望结果：`foo.md` 被识别为 `orphan` 状态，列入「待治理知识」表，建议「补充到 INDEX 或确认归档」（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:419）。

### 场景 3：高价值经验升级

- 角色：知识治理人员
- 前置：某条经验文件 `context/team/experience/x.md` 已被多个需求 `plan.md` 引用。
- 主流程：
  1. 跑利用率报告。
  2. 脚本统计该文件 `reference_count >= 3` 且至少一次出现在 `Decision / 决策 / 应对 / 风险 / 验证` 等上下文窗口附近（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:113）。
- 期望结果：该文件状态分类为 `high_value`，提示治理人员评估升级为 checklist / SOP / gate / 测试（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:155）。

## 非功能需求

- **性能**：脚本端到端运行时间 < 5 秒（仓库规模 < 1000 个 md 文件 + 1000 个需求产物文件时）。spec 原文未给具体阈值，本需求收敛为 5 秒，AC-11 回归测试用 `time` 命令守门。
- **兼容性**：Markdown 链接解析必须复用或与 `scripts/lib/check_index.py` 对齐，避免两套 INDEX 语义漂移（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:210）。
- **安全 / 合规**：MVP 仅扫描仓库文件并写报告输出文件，不修改任何现有 `context/` / `requirements/` 文件，不引入向量数据库或外部分析服务（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:30）。
- **可追溯**：报告中每条问题与每个引用 / 应用证据必须能追溯到文件路径与行号（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:45）。

## 范围

### 包含（MVP / Phase 1）

- 扫描 `context/team/**/*.md`、`context/project/**/*.md` 知识文件（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:56）。
- 扫描 `context/**/INDEX.md` 构建 INDEX 图，识别可发现性、断链、孤岛（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:199）。
- 扫描 `requirements/**` 中 `plan.md / notes.md / process.txt / artifacts/*.md / reviews/*.json / artifacts/test-report.md / artifacts/outline-design.md / artifacts/detailed-design.md` 的显式引用（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:213）。
- 计算 `KnowledgeUsageSummary`（路径 / kind / indexed / index_paths / reference_count / applied_signal_count / first_referenced_at / last_referenced_at / last_modified_at / status / score）（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:124）。
- 生成 `reports/context-usage.md` 与 `reports/context-usage.json`（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:267）。
- Phase 2 应用信号增强（保守识别 `applied`）一并落地，因为高价值列表强依赖应用信号（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:108）。

### 不包含

- 不统计模型隐式参考的文件（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:36）。
- 不把"文件读取次数"算作核心指标（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:37）。
- 不引入向量数据库 / 外部分析服务 / 独立后端（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:38）。
- 不自动删除、归档或重写低利用率知识文件（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:39）。
- MVP 不要求所有 Agent 必须通过统一 context 检索入口（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:40）。
- MVP 不阻断提交 / archive / phase transition（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:41）。
- Phase 3 治理入口（`/knowledge:usage-report` slash command、archive/submit 前弱提醒、`--fail-on-broken-index` 等结构性 fail 参数）推后实现（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:585）。
- Phase 4 统一检索事件打点推后实现（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:599）。

## 验收标准

> 与 spec §「成功标准」对齐（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:702）。每条验收都对应一个或多个可执行测试。

### AC-01 文件清单准确

脚本能列出所有纳入范围（`context/team/**`、`context/project/**`）的 md 文件，剔除 `INDEX.md` 与配置忽略路径（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:54）。

### AC-02 INDEX 挂载判断正确

对每个知识文件能判断是否被同级或上级 `INDEX.md` 链接挂载（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:79）。

### AC-03 断链与孤岛识别

能识别 INDEX 链接断裂（目标文件不存在）与孤岛文件（存在但无 INDEX 引用）（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:200）。

### AC-04 显式引用统计

能统计每个文件在 `requirements/**` 中的显式引用次数，引用形式覆盖：Markdown 链接、直接路径、`来源：` 标记、JSON / YAML 字段中的 context 路径（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:97）。

### AC-05 保守应用信号识别（基于 requirements/** 文本判定）

**MVP 扫描范围**：仅扫描 `requirements/**` 下的文档（`plan.md / notes.md / process.txt / artifacts/*.md / reviews/*.json` 等，见 AC-04），**不实际扫描 `tests/` / `scripts/gates/` / `.claude/` / `context/team/**`** 等落点目录。spec 第 113-120 行列出的「升级为 checklist / SOP / 测试 / gate / hook」一类信号，MVP 仅在以下两种文本特征出现时计为 `applied`：

1. **上下文窗口命中**：引用所在的同一 `##` 二级小节（详细设计阶段可收敛为「前 5 行 + 后 10 行」窗口）内出现 `Decision / 决策 / 应对 / 风险 / 验证` 关键字（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:113）。
2. **显式升级声明**：requirements 内任何文本明确写出「升级为 checklist / SOP / 测试 / gate / hook」「来自该经验」「按该经验落 test」等句式（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:113）。

**不计为应用**：普通资料引用、相关阅读列表、全文搜索命中（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:120）。

**说明**：扫描 `tests/` 等真实落点的能力推后到 Phase 3 治理入口落地后再做（要求脚本输出与实际落点交叉校验），避免 MVP 范围漂移。AC-05 当前可稳定验证：只看 requirements/** 内文本即可重现判定。

### AC-06 报告产出

能输出 `reports/context-usage.md` 与 `reports/context-usage.json`；Markdown 报告含 `## 总览`、`## 高价值知识`、`## 待治理知识`、`## 引用明细` 四个章节；JSON 报告 schema 与 `KnowledgeUsageSummary` 一致（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:267）。

### AC-07 证据可追溯

报告中每条引用与每条应用证据都标注文件路径 + 行号（`requirements/REQ-2026-012/plan.md:35`）（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:359）。

### AC-08 不阻断不破坏

默认运行不阻断流程，不修改除报告文件（`reports/context-usage.md`、`reports/context-usage.json`）外的仓库内容（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:41）。

### AC-09 状态分类

每个知识文件能被归类为以下状态之一：`active / high_value / visible_unused / orphan / stale_candidate / needs_review`，分类规则来自 spec §「状态分类」（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:154）。`stale_candidate` 默认时间窗口 90 天 [本需求决策，spec 开放问题 2 二选一选 90 天]。

### AC-10 排序分数

`usage_score = indexed_score + reference_score + applied_score + recency_score`，权重：indexed 2 分 / 每次引用 3 分（上限 30）/ 每次应用信号 8 分（上限 40）/ 最近 30 天被引用 10 分、90 天内 5 分。分数仅用于报告排序，不用于自动处置；项目级与团队级知识使用同一套权重 [本需求决策，spec 开放问题 3 二选一选同一套]（权重定义来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:165-183）。

### AC-11 测试覆盖

覆盖单元测试（Markdown 链接解析 / 相对绝对路径 / 断链 / 孤岛 / 引用识别 / 应用信号保守分类 / 状态与分数计算）+ fixture 测试（构造小型仓库）+ 回归测试（当前仓库真实数据跑通且不修改非报告文件）（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:613）。

### AC-12 CLI 行为

默认命令为 `python3 scripts/lib/context_usage_report.py`；可选参数支持 `--context-dir / --requirements-dir / --output / --json-output / --since / --project / --only-experience / --format md / --format json`；治理参数 `--fail-on-broken-index / --fail-on-orphan` 留接口但 MVP 默认不启用（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:445）。

### AC-13 入口形态

MVP 只交付 Python 脚本入口；`/knowledge:usage-report` slash command 推后到后续 Phase 3 实现 [本需求决策，spec 开放问题 4 二选一选只交付脚本]（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:587）。

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 报告输出位置 | A. 固定 `reports/` 目录 / B. 进 `requirements/<REQ-ID>/artifacts/` | A. `reports/` | spec 开放问题 1（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:697）；MVP 不绑定单次治理需求，便于历次报告纵向对比 |
| `stale_candidate` 时间窗口 | A. 90 天 / B. 180 天 | A. 90 天 | spec 开放问题 2（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:698）；recency_score 已用 30/90 天窗口，90 天与之对齐 |
| 评分权重区分 | A. 项目级 / 团队级统一 / B. 各用一套 | A. 统一 | spec 开放问题 3（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:699）；MVP 避免引入额外配置维度 |
| 入口形态 | A. 仅 Python 脚本 / B. 立刻加 `/knowledge:usage-report` | A. 仅脚本 | spec 开放问题 4（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:700）；spec 自身建议 Phase 3 再加命令 |
| Phase 范围 | A. 只交付 Phase 1 / B. Phase 1 + Phase 2 应用信号 | B. Phase 1 + Phase 2 | spec §「高价值知识」需要 applied 信号才能落（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:570）；缺 applied 则 high_value 无法稳定分类 |
| 性能阈值 | A. 秒级（模糊） / B. < 5s / C. < 10s | B. < 5s | AC-11 需可执行守门，5s 给后续 200 文件 → 5000 文件留 10× 余量；CI 用 `time` 直接守 |
| `reports/` 入 git 策略 | A. 入 git / B. `.gitignore` 本地生成，治理人员择期 commit / C. 完全不入 git | B. `.gitignore` + 择期 commit | 报告随仓库状态变化频繁，入 git 会污染 PR diff；完全不入 git 又丢失历史。折中：默认本地生成 + `.gitignore`，治理需求触发时人工 commit 一份快照供溯源。AC-08「不修改除报告文件外的仓库内容」据此条件成立（`.gitignore` 内 `reports/` 一条由本需求自带，不算 AC-08 违例） |
| 应用信号上下文窗口 | A. 同 `##` 二级小节内 / B. 前 5 行 + 后 10 行 / C. 同段落 | A + B 复合（先 A 兜底，详细设计精化为 B） | spec 未指定；A 实现简单可先落地，B 在详细设计阶段精化为「同 `##` 二级小节内 ∧ 前 5 行 + 后 10 行」双约束，避免长小节误判 |
| Markdown 链接解析模块抽取 | A. 各自实现 / B. 抽 `scripts/lib/markdown_links.py` 公共模块 | B. 抽公共模块 | spec 第 686-687 行明确要求「优先复用 `check_index.py` 解析逻辑」；MVP 先抽公共模块 + 同步改 `check_index.py` 调用，避免两套实现漂移 |

## 待确认清单

> 文档中所有 `[待用户确认]` / `[待补充]` 标记的来源条目汇总；P1 评审已收敛 4 项进入「关键决策记录」表。本清单只保留**仍需用户人工确认**的条目。
>
> **说明（关于本章节与下方「待澄清清单」并存）**：当前工具链命名不一致——`standard-8phase.yaml` 的 `req-artifact-check` 要求 `## 待确认清单`，而 `scripts/lib/check_sourcing.py` 的 W001 / W003 检查只认 `## 待澄清清单`。本文档同时保留两节作为 workaround，详见 `notes.md` Bug-4。下方「待澄清清单」节内容与本节一致。

1. **meta.yaml 语义字段**：`feature_area` 取值需对照 `context/project/agentic-meta-engineering/areas.yaml` 白名单确定；本文档暂留 `[待用户确认]`。
2. **Phase 范围标注**：是否需要在 `meta.yaml.tags` 加 `phase-1+phase-2` 标记，留下后续 Phase 3 / Phase 4 追溯线索？本文档暂不强制要求。

> 历史决议（已并入「关键决策记录」表，不再作为待办）：
> - 性能阈值 → 决策为 < 5 秒（决策表 ↑）
> - `reports/` 是否入 git → 决策为 `.gitignore` + 治理人员择期 commit（决策表 ↑）
> - 应用信号上下文窗口大小 → 决策为「同 `##` 二级小节 ∧ 前 5 行 + 后 10 行」复合约束（决策表 ↑）
> - Markdown 链接解析模块抽取 → 决策为抽 `scripts/lib/markdown_links.py` 公共模块（决策表 ↑）

## 待澄清清单

> 与上方「待确认清单」语义等价；保留本节是为满足 `check_sourcing.py` W001 / W003 校验项（regex 只认 `待澄清清单`）。详见 `notes.md` Bug-4。

1. **meta.yaml 语义字段**：`feature_area` 取值需对照 `context/project/agentic-meta-engineering/areas.yaml` 白名单确定；本文档暂留 `[待用户确认]`。
2. **Phase 范围标注**：是否需要在 `meta.yaml.tags` 加 `phase-1+phase-2` 标记，留下后续 Phase 3 / Phase 4 追溯线索？本文档暂不强制要求。

## 元数据补齐提示

> 离开 `definition` 阶段前需在 `meta.yaml` 补齐语义字段（参考 `context/team/engineering-spec/meta-schema.yaml`）：
>
> - `feature_area`：建议填入与「知识治理 / context engineering」相关的 area（具体值需查 `context/project/agentic-meta-engineering/areas.yaml` 白名单，[待用户确认]）。
> - `change_type`：`feature`（新增脚本与报告产物）。
> - `affected_modules`：建议 `scripts/lib/context_usage_report.py`、`scripts/lib/check_index.py`（如需复用解析）、`reports/`、`tests/lib/test_context_usage_report.py`。
> - `tags`：可选，建议 `knowledge-governance` / `context-engineering`。
