# REQ-2026-003 · 代码审查人类必经卡点（路由确认 + 结论 sign-off）

## 目标

把 `/code-review` 的 fan-out 从硬编码 8 个 checker 改为路径规则推荐 + 人工 tty 确认，单次审查的 checker 调用数从固定 8 降至按需 0-8，同时让卡点 A 由代码强制（非 tty 退码 2，AI 不得绕过）、路由失败 fail-closed（退码 3/4 终止流程）。

## 范围

- 包含：
  - `.claude/code-review-routing.yaml` 路径规则库（must / suggest / trivial_whitelist 三段）
  - `scripts/lib/code_review_routing.py` 路由引擎 + tty 卡点 A
  - `commands/code-review.md` Step 2 fan-out 改读 `checker_route`
  - `code-review-prepare` SKILL.md 与 scope-schema.md 同步更新
  - 单元 / tty 集成 / 端到端三层测试
- 不包含：
  - 卡点 B sign-off 任何改动（已在 F-004b 实现）
  - 关键词扫描 / LLM router / features.json 声明等非路径判定信号
  - 路由失败 fallback 全集机制（明确 fail-closed）
  - 大改动自动升级 / 风险等级评分 / 抽查 audit
  - critic / judge / report 等下游 Agent 的核心逻辑改动（仅要求识别 `skipped=true` 短路）

## 里程碑

| 阶段 | 预期完成 |
|---|---|
| definition | |
| tech-research | |
| outline-design | |
| detail-design | |
| task-planning | |
| development | |
| testing | |

## 风险

- 风险 1：路径规则粒度过粗 / 过细，导致漏判（粗）或推荐基本等于全集（细）。
  - 应对：detail-design 阶段比对实际 services 目录结构定稿 must / suggest 列表；testing 阶段以"嵌入模式平均 checker 调用数 ≤ 3"作为验收指标；上线后 process.txt 的审计行支持事后统计、再调整 yaml。
- 风险 2：critic / judge / report 等下游 Agent 未识别 `skipped=true` 短路，trivial-skip 场景崩溃。
  - 应对：detail-design 阶段列出每个消费方的 skip 处理逻辑；testing 阶段端到端覆盖 trivial-only diff 场景；任何下游 Agent 改动需配套 contract test。
- 风险 3：tty 校验在某些终端模拟器（IDE 内嵌 / 远程 SSH）行为不一致。
  - 应对：tty 校验复用 `save_review.py` 已验证过的同源逻辑；testing 阶段在 macOS Terminal / iTerm / VS Code Terminal 至少三种环境下手测；写入"已知失败的终端清单"到 SKILL 引用。

---

## 决策记录

<!--
记录对本需求架构 / 契约 / 工期 / 依赖有影响的关键决策。
新决策 append 一个 ### D-NNN 小节（不回删旧条目）。
废弃旧决策时新开一条，Supersedes 指向被废弃的 D 号。
纯文档风格 / 目录命名 / 临时测试策略 不写 ADR。
-->

### D-001 路由失败 fail-closed（不降级到 8 路全集）

- **Context**：路由器有两类失败可能——yaml 加载/语法错（来源：requirements/REQ-2026-003/artifacts/requirement.md:67）、推荐集为空或全部命中校验失败（待 detail-design 阶段把退码 3 的具体触发场景定稿，来源：requirements/REQ-2026-003/artifacts/tech-feasibility.md:129）。备选是 fail-open——失败时静默回退到原有的 8 路 fan-out，开发体验最平滑但风险高。
- **Decision**：选 **fail-closed**——routing.py 加载/校验失败立刻 exit（yaml 异常→退码 4；规则集为空/无命中→退码 3，详见 detail-design），主 Agent 收到非零退码则终止 `/code-review` 并报错"路由器异常，请修复 .claude/code-review-routing.yaml"。**不**实现降级到全集的 fallback 路径（来源：requirements/REQ-2026-003/artifacts/requirement.md:97 范围段"不包含·路由失败 fallback 全集机制"）。
- **Consequences**：
    - 好：规则坏掉立刻可见，避免"温水煮青蛙"——长期降级跑全集却无人察觉（brainstorming 追问明确依据，来源：requirements/REQ-2026-003/artifacts/requirement.md:109 关键决策表第 5 行）。
    - 好：让"卡点 A 的有效性"成为可验证不变式——审计日志里看到任何 review 完成，就意味着路由器已通过；不存在"路由器跪了但 review 照跑"的灰色态。
    - 不好：开发者首次写 routing.yaml 写错时直接被阻断；缓解——routing.py 必须给清晰错误信息（包含错误行号 + fix-hint），detail-design 阶段定稿错误文案模板。
    - 不好：CI / 离线脚本场景默认非 tty 也会被退码 2 阻断；属于设计内行为（与卡点 B 同源约束，来源：context/team/ai-collaboration.md:38）。
- **时间**：2026-04-30 20:50:12

### D-002 tty 卡点 4 档热键 UX

- **Context**：人工介入需要在"低摩擦"和"出错可纠偏"间权衡。备选：[Y/n] 单按键（最低摩擦但不可调整子集）、4 档热键（默认快 + 可细调）、全自动跑 + 抽查（人不在回路违背卡点 A 初衷）、按风险等级分流（增模型复杂度，brainstorming Q2 已否决）。code-review-prepare SKILL.md:17-21 已预置 4 档形态草案（来源：.claude/skills/code-review-prepare/SKILL.md:17）。
- **Decision**：选 **4 档热键**：
    1. **enter**（默认）：接受路由器的推荐集（must + suggest 命中项）
    2. **a**：升级到全集（8 个 checker 全跑——保留人工"我不放心"的兜底）
    3. **q**：取消本次 review，写 process.txt `[code-review-aborted]` 审计行（来源：requirements/REQ-2026-003/artifacts/requirement.md:110）
    4. **数字逗号**（如 `1,3,5`）：从推荐集中自定义子集；must 项强制保留不可去掉（来源：requirements/REQ-2026-003/artifacts/requirement.md:25）

  连续 3 次无效输入触发 abort（与场景 1 主流程 step 3 配套）；阈值参考 ssh / sudo 默认（来源：requirements/REQ-2026-003/artifacts/requirement.md:118），testing 阶段以人工试用感受验收。
- **Consequences**：
    - 好：默认路径"回车一下"接近零摩擦，与"按需收紧 fan-out"主目标一致。
    - 好：a 档保留兜底心理安全感，避免"被路由器锁死"的抵触情绪。
    - 不好：4 档 + 数字逗号比单按键学习成本略高；缓解——首屏帮助一行直观、热键名采用语义记忆（a=all / q=quit）。
    - 不好：连续 3 次阈值是经验值，可能与个体习惯不匹配；testing 阶段保留可调空间。
- **时间**：2026-04-30 20:50:12

### D-003 纯路径规则（不引入关键词 / LLM / features.json 等异质信号）

- **Context**：判定一个 diff 该跑哪几个 checker，备选信号源：路径 glob、diff 内关键词扫描、LLM router 自然语言判断、features.json 增加 `review_profile` 字段声明式标注。brainstorming Q1 已对四类对比并否决后三种（来源：requirements/REQ-2026-003/artifacts/requirement.md:105 关键决策表第 1 行；来源：requirements/REQ-2026-003/artifacts/requirement.md:111 第 7 行明确"keywords in diff 不保留"）。
- **Decision**：路由判定**只**读 diff 涉及的文件路径，按 .claude/code-review-routing.yaml 三段（must / suggest / trivial_whitelist）做 path-glob 匹配。**不**引入：
    - 关键词扫描（哪怕作为弱加权信号——会破坏"纯路径规则"承诺，YAGNI）
    - LLM router（违反 brainstorming Q1 "零 token、可解释" 选型理由）
    - features.json `review_profile` 字段（已 brainstorming 否决，来源：requirements/REQ-2026-003/artifacts/requirement.md:96 范围段"不包含"）

  glob 引擎选 `pathspec` 库（gitignore 兼容语法，含 `**` 跨目录匹配；Python 3.11 stdlib 不支持，来源：requirements/REQ-2026-003/artifacts/tech-feasibility.md:33）。
- **Consequences**：
    - 好：路由逻辑可单测、零 token、人类可一眼看懂为什么命中（brainstorming Q1 选型依据）。
    - 好：未来真出现"某 yaml 路径粒度太粗"痛点时，调整粒度的成本只是改 yaml；不需要回头加判定维度。
    - 不好：路径命名不规范的代码库（如所有逻辑都堆在 `core/` 下）会导致路由器粒度过粗、推荐集接近全集；缓解——detail-design 阶段制定 yaml 书写规范 + R-1 风险条目（来源：requirements/REQ-2026-003/artifacts/tech-feasibility.md:88）。
    - 不好：新增 pathspec 依赖；缓解——MIT license / 维护活跃 / ~50 KB / 调用面收敛（来源：requirements/REQ-2026-003/artifacts/tech-feasibility.md:30）。
- **时间**：2026-04-30 20:50:12
