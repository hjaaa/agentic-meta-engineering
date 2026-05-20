# Context 知识利用率统计机制设计

日期：2026-05-19
状态：待审阅
范围：agentic-meta-engineering 仓库内 `context/` 知识文件、经验文件、INDEX、需求产物、知识治理报告

## 背景

当前仓库已经通过 `context/` 目录沉淀团队规范、项目知识和跨项目经验。`context/team/experience/` 下的经验文件持续增长，说明团队已经能把需求过程中的踩坑、修复和规则抽取为长期记忆。

现有体系主要解决三个问题：

- 知识放在哪里：`context/team/` 存团队通用知识，`context/project/<project>/` 存项目级知识。
- 知识如何被发现：`INDEX.md` 作为渐进式披露入口。
- 经验如何沉淀：`/knowledge:extract-experience` 从需求笔记中提取经验，并更新对应 INDEX。

缺口在于：仓库目前只能看到“沉淀了哪些知识”，不能系统回答“哪些知识被后续需求发现、引用、应用，哪些知识长期没有使用证据”。经验文件数量继续增长后，缺少利用率统计会带来三类问题：

- 低价值或重复经验长期堆积，INDEX 变重，降低 Agent 检索效率。
- 高价值经验没有被识别出来，无法升级为 checklist、SOP、测试或门禁。
- 孤岛文件、断链文件和过时文件只能靠人工偶然发现。

本设计引入一套轻量、可验证、可渐进增强的 Context 知识利用率统计机制。

## 目标

1. 为 `context/` 下知识文件建立可解释的利用率统计口径。
2. 区分“可发现”“被引用”“被应用”三类不同强度的使用信号。
3. 生成 Markdown 与 JSON 报告，支持人工治理和后续自动化。
4. 先用离线扫描落地 MVP，不改变现有需求流、review 流和 archive 流。
5. 复用当前“Markdown 即记忆、位置即语义、INDEX 先行、渐进式披露”的设计原则。
6. 为未来接入统一检索打点、弱门禁和趋势分析预留扩展点。

## 非目标

1. 不统计模型隐式参考了哪些文件；没有证据的使用不计入利用率。
2. 不把文件读取次数作为核心指标；读过不代表真正应用。
3. 不引入向量数据库、外部分析服务或独立后端。
4. 不自动删除、归档或重写低利用率知识文件。
5. MVP 不要求所有 Agent 必须通过统一 context 检索入口。
6. MVP 不阻断提交、archive 或 phase transition。

## 设计原则

- 证据优先：所有统计结果都必须能追溯到文件路径和行号，避免凭感觉治理。
- 分层统计：可发现、引用、应用分开统计，避免一个分数掩盖问题。
- 低侵入：第一版只读仓库文件并生成报告，不改业务文件和流程状态。
- 保守分类：应用信号宁可漏判，不要把普通引用误判成真实应用。
- 不制造指标压力：报告用于治理，不作为强 KPI；低利用率不等于无价值。
- 路径承载语义：统计对象和分类优先从路径推导，不给每份文档增加元数据负担。

## 统计范围

### 纳入范围

默认统计以下 Markdown 文件：

- `context/team/**/*.md`
- `context/project/**/*.md`

重点关注经验目录：

- `context/team/experience/*.md`
- `context/project/<project>/experience/*.md`

### 排除范围

默认排除：

- `INDEX.md`
- 自动生成的利用率报告
- 临时草稿
- 配置文件中声明忽略的路径

`INDEX.md` 不作为被统计的知识文件，但会作为可发现性的数据来源。

## 核心概念

### 可发现

文件存在且能通过 `INDEX.md` 链接被逐步发现。

可发现信号包括：

- 文件被同级或上级 `INDEX.md` 链接。
- INDEX 链接目标存在。
- 目标文件不在忽略列表中。

不可发现信号包括：

- 文件存在但没有任何 INDEX 链接。
- INDEX 链接断裂。
- 文件位于应有 INDEX 管辖范围内但未列出。

### 被引用

文件路径出现在后续需求产物或文档中，并能定位到引用位置。

引用信号包括：

- Markdown 链接：`[说明](context/team/experience/x.md)`。
- 直接路径：`context/team/experience/x.md`。
- 来源标记：`来源：context/team/experience/x.md`。
- JSON / YAML 字段中记录的 context 路径。

INDEX 导航链接不计为引用，只计为可发现。

### 被应用

文件内容影响了后续决策、实现、验证、review 或流程规则。

应用信号包括：

- 引用出现在 `Decision`、`决策`、`应对`、`风险`、`验证` 等上下文附近。
- 经验被写入 `plan.md` 的风险应对或实施策略。
- 经验出现在 review 修复说明中。
- 经验被升级为 checklist、SOP、测试、gate 或 hook。
- 测试报告中明确说明某验证项来自该经验。

普通资料引用、相关阅读列表、全文搜索命中不计为应用。

## 指标模型

每个知识文件生成一条 `KnowledgeUsageSummary`。

```json
{
  "path": "context/team/experience/test-assets-must-be-wired-into-ci.md",
  "kind": "team_experience",
  "indexed": true,
  "index_paths": ["context/team/experience/INDEX.md"],
  "reference_count": 3,
  "applied_signal_count": 1,
  "first_referenced_at": "2026-05-06",
  "last_referenced_at": "2026-05-17",
  "last_modified_at": "2026-05-06",
  "status": "active",
  "score": 23
}
```

### 文件类型

`kind` 从路径推导：

- `team_experience`：`context/team/experience/*.md`
- `project_experience`：`context/project/<project>/experience/*.md`
- `team_spec`：`context/team/engineering-spec/**/*.md`
- `team_onboarding`：`context/team/onboarding/**/*.md`
- `project_knowledge`：`context/project/<project>/**/*.md`
- `other_context`：其他 context Markdown

### 状态分类

| 状态 | 含义 |
|---|---|
| `active` | 已挂 INDEX，且有引用或应用证据 |
| `high_value` | 多次被引用，或至少有一次强应用证据 |
| `visible_unused` | 已挂 INDEX，但暂未发现引用证据 |
| `orphan` | 文件存在，但未被 INDEX 挂载 |
| `stale_candidate` | 长期无引用且近期无修改，建议人工复核 |
| `needs_review` | 存在断链、引用异常或疑似过时问题 |

### 排序分数

分数用于报告排序，不用于自动处置。

```text
usage_score =
  indexed_score
  + reference_score
  + applied_score
  + recency_score
```

建议初始权重：

- `indexed_score`：被 INDEX 挂载得 2 分。
- `reference_score`：每次显式引用得 3 分，上限 30 分。
- `applied_score`：每次应用信号得 8 分，上限 40 分。
- `recency_score`：最近 30 天被引用得 10 分，90 天内被引用得 5 分。

低分只表示缺少近期使用证据，不表示文件应被删除。

## 数据来源

### Context 文件清单

扫描 `context/` 获取知识文件 inventory：

- 路径
- 类型
- 所属层级
- 是否经验文件
- 最近修改时间

最近修改时间优先来自 git 历史，无法获取时回退到文件系统时间。

### INDEX 图

扫描 `context/**/INDEX.md` 中的 Markdown 链接，建立 INDEX 到知识文件的有向图。

用途：

- 判断文件是否可发现。
- 识别断链。
- 识别孤岛文件。
- 识别同目录或子目录内未被列出的 Markdown 文件。

该能力应复用或对齐现有 `scripts/lib/check_index.py` 的解析规则，避免两套 INDEX 语义漂移。

### 需求产物

扫描 `requirements/**` 中的过程和产物文件：

- `plan.md`
- `notes.md`
- `process.txt`
- `artifacts/*.md`
- `reviews/*.json`
- `artifacts/test-report.md`
- `artifacts/outline-design.md`
- `artifacts/detailed-design.md`

用途：

- 识别显式引用。
- 识别应用信号。
- 关联引用发生在哪个需求、哪个产物。

### Git 历史

通过 git 获取辅助信息：

- 文件首次出现 commit。
- 最近修改 commit。
- 最近 N 天是否被修改。

Git 历史不作为使用证据，只辅助判断新旧和排序。

### 未来事件日志

后续可在统一 context 检索入口记录事件：

```json
{
  "type": "context_selected",
  "source": "context/team/experience/x.md",
  "req_id": "REQ-2026-014",
  "phase": "outline-design",
  "created_at": "2026-05-19T10:00:00+08:00"
}
```

MVP 不依赖该事件，避免先修改 Agent 工作流。

## 架构设计

新增一个离线报告脚本：

```text
scripts/lib/context_usage_report.py
```

脚本只读仓库文件，默认输出：

```text
reports/context-usage.md
reports/context-usage.json
```

### 模块划分

#### ContextInventory

职责：

- 扫描 `context/` 下的 Markdown 文件。
- 排除 `INDEX.md` 和忽略路径。
- 根据路径推导 `kind`。
- 读取 git 修改时间。

输出：`KnowledgeFile` 列表。

#### IndexGraph

职责：

- 解析 `context/**/INDEX.md` 中的 Markdown 链接。
- 解析相对路径、绝对路径和 anchor。
- 记录每个知识文件被哪些 INDEX 链接。
- 识别断链和孤岛。

输出：`IndexReference` 列表和 INDEX 健康问题。

#### EvidenceScanner

职责：

- 扫描 `requirements/` 和其他指定文档目录。
- 识别 context 路径引用。
- 记录引用文件、行号、片段和需求 ID。

输出：`UsageEvidence` 列表。

#### AppliedSignalClassifier

职责：

- 基于引用位置和上下文判断是否为应用信号。
- 将普通 `reference` 升级为 `applied`。
- 保留原始证据，避免黑盒判断。

输出：带信号类型的 `UsageEvidence`。

#### UsageAggregator

职责：

- 汇总每个知识文件的可发现、引用、应用数据。
- 计算状态和排序分数。
- 生成总览统计。

输出：`KnowledgeUsageSummary` 列表。

#### ReportRenderer

职责：

- 输出 Markdown 报告。
- 输出 JSON 报告。
- 保证报告中每条问题都有证据路径和行号。

## 数据结构

### KnowledgeFile

```json
{
  "path": "context/team/experience/x.md",
  "kind": "team_experience",
  "is_experience": true,
  "last_modified_at": "2026-05-06",
  "ignored": false
}
```

### IndexReference

```json
{
  "index_path": "context/team/experience/INDEX.md",
  "line": 12,
  "target_path": "context/team/experience/x.md",
  "exists": true
}
```

### UsageEvidence

```json
{
  "source_file": "requirements/REQ-2026-012/plan.md",
  "line": 35,
  "target_file": "context/team/experience/x.md",
  "req_id": "REQ-2026-012",
  "signal": "applied",
  "excerpt": "本需求测试资产必须接入 CI，来源：context/team/experience/x.md"
}
```

### KnowledgeUsageSummary

```json
{
  "path": "context/team/experience/x.md",
  "kind": "team_experience",
  "indexed": true,
  "reference_count": 3,
  "applied_signal_count": 1,
  "status": "high_value",
  "score": 23,
  "evidence": []
}
```

## 报告格式

### 总览

```markdown
# Context 知识利用率报告

生成时间：2026-05-19 10:00:00 Asia/Shanghai

## 总览

- 知识文件总数：42
- 已被 INDEX 挂载：39
- 未挂载孤岛：3
- 有引用证据：18
- 有应用证据：7
- 90 天无引用：11
```

### 高价值知识

```markdown
## 高价值知识

| 文件 | 引用次数 | 应用信号 | 最近引用 | 说明 |
|---|---:|---:|---|---|
| context/team/experience/test-assets-must-be-wired-into-ci.md | 4 | 2 | 2026-05-12 | 已影响 CI 测试策略 |
```

### 待治理知识

```markdown
## 待治理知识

| 文件 | 状态 | 问题 | 建议 |
|---|---|---|---|
| context/team/experience/foo.md | orphan | 未被 INDEX 挂载 | 补充到 INDEX 或确认归档 |
| context/team/experience/bar.md | stale_candidate | 180 天无引用 | 人工复核是否过时、合并或保留 |
```

### 引用明细

```markdown
## 引用明细

### context/team/experience/x.md

- 状态：high_value
- INDEX：context/team/experience/INDEX.md
- 引用次数：2
- 应用信号：1

证据：

- requirements/REQ-2026-012/plan.md:35 — applied
- requirements/REQ-2026-012/artifacts/test-report.md:130 — reference
```

## 命令设计

默认命令：

```bash
python3 scripts/lib/context_usage_report.py
```

可选参数：

```bash
python3 scripts/lib/context_usage_report.py \
  --context-dir context \
  --requirements-dir requirements \
  --output reports/context-usage.md \
  --json-output reports/context-usage.json
```

过滤参数：

```bash
--since 2026-01-01
--project agentic-meta-engineering
--only-experience
--format md
--format json
```

治理参数：

```bash
--fail-on-broken-index
--fail-on-orphan
```

MVP 默认不启用 fail 参数。

## 治理策略

### 强校验候选

以下问题适合后续接入门禁：

- 新增 `context/**/*.md` 后未更新对应 `INDEX.md`。
- INDEX 链接目标不存在。
- 需求产物引用的 `context/...` 路径不存在。

这些属于结构完整性问题，阻断风险可控。

### 弱提醒候选

以下问题只生成报告，不阻断流程：

- 长期未引用。
- 低利用率。
- 疑似重复经验。
- 经验正文过长。
- 多个经验描述相似问题。

### 人工处置动作

报告只给建议，处置由人确认：

- 保留：仍有长期参考价值。
- 合并：与其他经验重复。
- 升级：转为 checklist、SOP、gate 或测试。
- 归档：过时但保留历史。
- 删除：确认无价值且可通过 git 找回。

## 与现有体系的关系

### 与 INDEX 校验

现有 `check_index.py` 关注 INDEX 健康：

```text
文件是否能被发现
```

本机制关注利用率：

```text
文件是否被引用和应用
```

两者应共享 Markdown 链接解析和忽略规则，避免语义漂移。

### 与知识沉淀

`/knowledge:extract-experience` 负责把需求笔记转化为长期经验。本机制反向评估沉淀后的经验是否被复用。

后续可以形成闭环：

```text
notes.md -> extract-experience -> context/experience -> usage-report -> checklist/SOP/gate
```

### 与需求生命周期

MVP 建议手动运行报告，不接入需求流。

后续可在以下时机增加弱提醒：

- archive 前。
- release 前。
- 定期知识治理。
- 新增大量经验文件后。

## 分阶段落地

### Phase 1：离线报告 MVP

范围：

- 扫描 `context/` 知识文件。
- 扫描 INDEX 链接。
- 扫描 `requirements/` 显式引用。
- 输出 Markdown 和 JSON 报告。

验证：

- 人工抽查 5 个经验文件。
- 确认引用证据行准确。
- 确认孤岛文件识别准确。
- 确认脚本不修改仓库文件，除报告输出外无副作用。

### Phase 2：应用信号增强

范围：

- 增加 `plan.md`、review、test-report 的应用信号识别。
- 输出 `high_value` 和 `stale_candidate` 分类。
- 增加保守的上下文窗口判断。

验证：

- 已知被应用的经验进入高价值列表。
- 仅被 INDEX 导航的文件不被误判为应用。
- 应用证据能追溯到具体文件和行号。

### Phase 3：治理入口

范围：

- 增加 `/knowledge:usage-report` 或等价命令入口。
- 在 archive 或 submit 前给出弱提醒。
- 允许使用 `--fail-on-broken-index` 检查结构性问题。

验证：

- 默认不阻断正常需求流。
- 强校验只覆盖断链、孤岛等结构问题。
- 低利用率只报告，不失败。

### Phase 4：检索事件打点

范围：

- 在统一 context 检索入口记录 `context_selected` 事件。
- 区分“被检索命中”和“被最终应用”。
- 支持按需求、阶段、项目生成趋势。

验证：

- 检索事件能关联到需求 ID 和阶段。
- 未被最终引用的检索事件不会被计为应用。
- 事件缺失不影响离线扫描报告。

## 测试策略

### 单元测试

覆盖：

- Markdown 链接解析。
- 相对路径和绝对路径解析。
- INDEX 链接断裂识别。
- 孤岛文件识别。
- `requirements/` 中 context 路径引用识别。
- 应用信号保守分类。
- 状态和分数计算。

### Fixture 测试

构造小型仓库 fixture：

```text
context/
  INDEX.md
  team/
    INDEX.md
    experience/
      INDEX.md
      used.md
      unused.md
      orphan.md
requirements/
  REQ-2026-001/
    plan.md
    artifacts/test-report.md
```

验证：

- `used.md` 被识别为 active。
- `unused.md` 被识别为 visible_unused。
- `orphan.md` 被识别为 orphan。
- `plan.md` 中的决策引用被识别为 applied。

### 回归测试

使用当前仓库真实数据跑报告，检查：

- 脚本退出码为 0。
- JSON 可解析。
- Markdown 报告包含总览、高价值知识、待治理知识、引用明细。
- 不修改除报告输出外的其他文件。

## 风险与缓解

### 误把引用当应用

风险：普通资料引用被算成真实应用，导致高价值列表失真。

缓解：应用信号采用保守规则，保留证据行，后续人工复核。

### 漏统计隐式使用

风险：Agent 读了经验但没有写来源，报告无法统计。

缓解：MVP 接受漏统计；后续通过检索事件打点补强。

### 指标诱导机械引用

风险：为了提高利用率，Agent 在文档中堆砌 context 引用。

缓解：报告不作为 KPI；应用信号要求有决策、风险、验证等上下文。

### 与 INDEX 规则漂移

风险：利用率脚本和 `check_index.py` 对 Markdown 链接解析不一致。

缓解：优先复用 `check_index.py` 的解析逻辑，或把共享解析函数抽到公共模块。

### 过早门禁化

风险：低利用率提醒阻断正常需求推进。

缓解：MVP 只报告；后续只对结构性错误启用 fail 参数。

## 开放问题

1. 报告输出目录是否固定为 `reports/`，还是放到 `requirements/<REQ-ID>/artifacts/` 作为某次治理需求的产物。
2. `stale_candidate` 的默认时间窗口采用 90 天还是 180 天。
3. 项目级知识和团队级知识是否使用同一评分权重。
4. 是否需要新增 `/knowledge:usage-report` 命令，还是先只提供 Python 脚本。

## 成功标准

MVP 完成后应满足：

1. 能列出所有纳入范围的 `context/` 知识文件。
2. 能判断每个文件是否被 INDEX 挂载。
3. 能识别 INDEX 断链和孤岛文件。
4. 能统计每个文件在 `requirements/` 中的显式引用次数。
5. 能保守识别应用信号。
6. 能输出 Markdown 和 JSON 报告。
7. 报告中的引用和应用证据都有文件路径与行号。
8. 默认运行不阻断流程，不修改除报告文件外的仓库内容。

长期完成后应满足：

1. 团队可以定期发现孤岛知识、重复经验和高价值经验。
2. 高价值经验可以被升级为 checklist、SOP、gate 或测试。
3. 新增经验文件不会长期脱离 INDEX。
4. 知识沉淀从“写进去”升级为“能复用、能验证、能治理”。

## 推荐结论

第一版应采用离线扫描报告方案，优先建立可解释的事实基础：

```text
context 文件清单 + INDEX 图 + 需求产物引用 + 保守应用分类 -> 利用率报告
```

该方案对现有流程侵入最小，能快速暴露孤岛文件、低复用经验和高价值经验。等报告稳定后，再逐步增加 `/knowledge:usage-report` 命令、结构性弱门禁和统一检索事件打点。
