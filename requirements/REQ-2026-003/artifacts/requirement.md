---
id: REQ-2026-003
title: 代码审查人类必经卡点（路由确认 + 结论 sign-off）
created_at: "2026-04-30 10:37:09"
refs-requirement: true
---

# REQ-2026-003 · 代码审查人类必经卡点（路由确认 + 结论 sign-off）

## 背景

`/code-review` 命令在 Step 2 硬编码并行调起 8 个专项 checker（来源：.claude/commands/code-review.md:29），主 Agent 没有任何"按需取舍"机制：阶段 7 的 feature-lifecycle-manager 每完成一个 feature 都自动触发一次完整 8 路 fan-out，token 消耗与 feature 数量呈线性关系。

`code-review-prepare` Skill 已预置一段激进的"卡点 A"设计——调 `code_review_routing.py` 做路由建议、tty 确认、`--all` / `--trivial` 不豁免、非 tty stdin 退码 2（来源：.claude/skills/code-review-prepare/SKILL.md:17）。但**该脚本至今未实现**，commands/code-review.md 的 fan-out 也未对接"按 route 跑"的形态——文档与实际行为分叉。

本需求标题中的另一半"卡点 B 结论 sign-off"已在 F-004b 实现（来源：scripts/check-signoff.sh）（来源：scripts/lib/save_review.py），且配套人类专属约束已写入团队规范（来源：context/team/ai-collaboration.md:38）。本需求**只聚焦缺失的卡点 A**：实现路由器、收紧 fan-out、补齐文档与代码一致性。

## 目标

- **主目标**：把 `/code-review` 的 fan-out 从"硬编码 8 个 checker"改为"按路径规则引擎推荐 + 人工 tty 确认"。单次审查的 checker 调用数从固定 8 降至按需 0-8（trivial 路径 0；普通路径预期 1-3）。
- **次要目标**：
  - 卡点 A 由代码强制——非 tty stdin 退码 2，AI 不得在主对话或子 agent 中绕过（与卡点 B 同源约束，来源：context/team/ai-collaboration.md:38）
  - 路由失败 fail-closed（退码 3/4 不降级到全集），让规则坏掉立刻被察觉
  - trivial 路径（纯 docs/ + `*.md` 等）100% 命中白名单时跳过卡点 A、跳过整个 review，process.txt 留审计行
  - 高风险路径（auth / payment / db migrations / api 契约 / sql）有 ≤5 条硬兜底规则（must），用户在自定义子集中不可去掉
  - 文档与实现一致：commands/code-review.md、skills/code-review-prepare/SKILL.md、`.review-scope.json` schema 同步更新

## 用户场景

### 场景 1：开发者完成 feature，自动触发审查

- **角色**：开发者；自动触发方：阶段 7 feature-lifecycle-manager（来源：.claude/skills/feature-lifecycle-manager/SKILL.md）的具体触发位置 [待用户确认]
- **前置**：feature 状态切到 done，触发 `/code-review` 嵌入模式（scope 限定到该 feature 的 services）
- **主流程**：
  1. code-review-prepare 取 diff、写出 `.review-scope.json` 骨架（不含 checker_route）
  2. 路由器读 yaml 规则、扫 diff 路径，输出推荐集（must 项标 [must]）
  3. 终端展示推荐集，开发者按 enter（接受）/ a（升全集）/ q（取消）/ 数字逗号（自定义）
  4. 主 Agent 按最终 route 并行调起 N 个 checker（N 通常 1-3）
  5. critic + judge + 报告生成 + 卡点 B sign-off（不变）
- **期望结果**：单次审查的 checker 调用数显著减少；high-risk 路径仍被 must 强制覆盖；审计可追溯。

### 场景 2：开发者只改了 README

- **角色**：开发者
- **前置**：diff 全部命中 `*.md` / `docs/**` 白名单
- **主流程**：
  1. 路由器识别 100% trivial → 写 `scope.skipped=true`、`checker_route=[]`
  2. process.txt 追加 `[code-review-skipped] N 文件全在白名单内`
  3. 主 Agent 看到 `skipped=true` → 不调 checker / critic / judge / 报告
- **期望结果**：0 个 checker 被调起；审计日志可验"这次审查发生过且选择了豁免"。

### 场景 3：AI 尝试在子 agent 中触发 /code-review

- **角色**：AI（被禁止方）
- **前置**：AI 在非 tty 环境（管道、heredoc、subagent 调用）尝试触发路由器
- **主流程**：
  1. routing.py 检测 stdin 不是 tty
  2. 直接退码 2，不读 yaml、不写盘
  3. 主 Agent 收到退码 2 → 终止流程并报错
- **期望结果**：路由确认强制由人类完成；与卡点 B 同源约束（来源：context/team/ai-collaboration.md:38）；AI 无法借助 trick 绕过。

### 场景 4：yaml 规则文件被改坏

- **角色**：开发者（事故场景）
- **前置**：路由 yaml 语法错（手抖 / 误删条目）
- **主流程**：
  1. routing.py 加载失败 → 退码 4
  2. 主 Agent 终止 `/code-review` 并报错"路由器异常，请修复 .claude/code-review-routing.yaml"
- **期望结果**：用户必须先修 yaml 才能继续审查；不会"路由失败 → 静默降级跑全集 → 长期不被察觉"。

## 非功能需求

- **性能**：路由器执行时间 < 200ms（diff < 2000 行；纯 path glob 匹配，无 LLM 调用）
- **兼容性**：现有 `.review-scope.json` 消费方（critic / judge / report）只新增字段，不破坏老字段；`skipped=true` 由这些消费方显式短路返回。改动需配套测试 [待补充]
  - 内容：critic / judge / report 在 skipped 路径下不可崩溃，必须 graceful exit
  - 依据：现状这些消费方都假设 checker_route ≠ ∅
  - 风险：若任一消费方未做 skip 检测，trivial-skip 场景会异常报错
  - 验证时机：detail-design 阶段列出每个消费方的 skip 处理逻辑；testing 阶段端到端验证
- **安全/合规**：tty 校验代码与 `save_review.py` sign-off 同源（`[ -t 0 ]` / `os.isatty(0)`）；不引入新的鉴权点
- **可审计**：每次卡点 A 的最终 route + decision mode 写入 `.review-scope.json.routing_decision`；trivial-skip 与 abort 写 process.txt（格式遵循 `YYYY-MM-DD HH:MM:SS [event-type] 简短原因`，来源：context/team/engineering-spec/time-format.md）

## 范围

- **包含**：
  - 新增 `.claude/code-review-routing.yaml`（路径规则库，三段：must / suggest / trivial_whitelist）
  - 新增 `scripts/lib/code_review_routing.py`（路由引擎 + tty 卡点 A）
  - 修改 `.claude/skills/code-review-prepare/SKILL.md`（trivial 100% 命中改为豁免行为，与现状的"不豁免"对齐到本需求决策）
  - 修改 `.claude/commands/code-review.md` 第 29-38 行（fan-out 改读 `checker_route`）
  - 修改 `.claude/skills/code-review-prepare/reference/scope-schema.md`（新增 `checker_route` / `routing_decision` / `skipped` 字段）
  - 单元测试（路径匹配 + must 不可绕过 + trivial 全/部分命中 + yaml 异常）
  - tty 集成测试（4 档热键 + 非 tty 退码 2 + 连续无效输入 abort）
  - 端到端测试（混合 diff / trivial-only diff）
- **不包含**：
  - 卡点 B（sign-off）的任何变更——已在 F-004b 实现，本需求不动它
  - 引入关键词扫描 / LLM router 等"非纯路径"判定信号（已 brainstorming 否决）
  - features.json 增加 review_profile 字段（已 brainstorming 否决）
  - 路由失败 fallback 机制（明确决定 fail-closed）
  - 大改动自动升级 / 风险等级评分 / 抽查 audit（已 brainstorming 否决）
  - 修改 critic / judge / report 等下游 Agent 的核心逻辑（仅要求其识别 `skipped=true` 短路返回）

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| 判定依据 | 路径规则 / 路径+关键词 / LLM router / features.json 声明 | **纯路径规则** | brainstorming Q1：可单测、零 token、可解释；粒度问题靠目录命名替代 |
| 人工介入 | tty 4 档热键 / [Y/n] 单按键 / 全自动+抽查 / 风险等级区分 | **tty 4 档热键** | brainstorming Q2：默认接受最快（回车），出错可细调；与 SKILL.md:17-21 现状一致 |
| Trivial 处理 | tty 仍走 / 白名单豁免 / 倒计时自动通过 | **白名单豁免 + process.txt 审计** | brainstorming Q3：极轻量改动 0 按键；审计行支持后续统计跳过率 |
| 硬兜底 | 少量 must / 不设 / 大改动升级 | **少量 must（≤5 条）** | brainstorming Q4：auth / payment / migration / api / sql 5 类强制 security 等，防误操作 |
| 路由失败处置 | fail-closed / fail-open（降级全集） | **fail-closed（退码 3/4 终止）** | brainstorming 追问：让规则坏掉立刻被察觉，避免"温水煮青蛙"——长期降级却无人察觉 |
| Abort 审计 | 不留痕 / 记一行 | **process.txt 写 [code-review-aborted]** | brainstorming 追问：abort 频率本身是诊断信号（路由质量、用户偏好） |
| Keywords in diff | 保留弱加权 / 不保留 | **不保留** | brainstorming 追问：违背 Q1 "纯路径规则" 承诺；YAGNI——真出现路径粒度太粗痛点再加 |

## 待澄清清单

1. yaml 中 `must` 的 5 条草案（auth / payment / db migrations / api 契约 / sql）是否完全匹配本仓库的目录约定？需要在 detail-design 阶段比对实际 services 目录结构后定稿 [待用户确认]。
2. trivial 白名单是否包含 `requirements/<id>/notes.md`？理由是 notes.md 高频改动且属于过程文档，但跨需求改动通常无审查价值 [待用户确认]。
3. `.review-scope.json.routing_decision.user_action_at` 时间格式默认沿用 meta.yaml 的 `YYYY-MM-DD HH:MM:SS`（Asia/Shanghai），detail-design 阶段最终确认（来源：context/team/engineering-spec/time-format.md）。
4. 自定义子集输入连续无效"3 次"作为 abort 阈值，是否合理？参考 ssh / sudo 默认 3 次错误的人机交互习惯，但本场景输入更宽容；testing 阶段以人工试用感受验收 [待用户确认]。
5. critic / judge / report 三个下游 Agent 在 `skipped=true` 路径下的具体短路实现（对应"非功能需求·兼容性"段下的同一议题）：detail-design 阶段需逐 Agent 列出现状代码假设 + 改造点；testing 阶段端到端覆盖 trivial-only diff 场景。
