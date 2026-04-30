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

### D-001 <决策标题>
- **Context**：做决策时的背景 / 约束
- **Decision**：选了什么，没选什么
- **Consequences**：好的后果、不好的后果
- **时间**：YYYY-MM-DD HH:MM:SS
- **Supersedes**：D-NNN（废弃前一决策时才有）
