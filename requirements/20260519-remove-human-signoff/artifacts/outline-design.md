---
id: 20260519-remove-human-signoff
phase: outline-design
created_at: 2026-05-19T03:40:00Z
---

# 概要设计 · 20260519-remove-human-signoff

> 权威单源同 requirement.md（来源：requirements/20260519-remove-human-signoff/plan.md:62）；本文档聚焦"删除 / 改造 / 改名"在 schema-code-yaml-doc 四类制品上的拓扑，不重复 spec 内容。

## 1. 架构方案：四类制品的同步退化

human sign-off 在仓库中以四类制品形态存在；本期同步退化使其在所有维度归零：

```
       ┌────────────────────────────────────────────────────────────┐
       │                   ⚠ 当前 human sign-off 拓扑                 │
       └────────────────────────────────────────────────────────────┘

  ① schema           context/team/engineering-spec/review-schema.yaml
                       enums.signoff_decision / signoff_source
                       fields.human_signoff
                       CR-1 / CR-4 / CR-8 中 is_signed_off 条件
                              │
                              ▼ 引用
  ② code             scripts/lib/check_reviews.py  (SIGNOFF_PASS / is_signed_off)
                     scripts/lib/save_review.py   (CR-1/CR-4 依赖 / signoff parser)
                     scripts/lib/signoff.py       (整文件)
                     scripts/gates/plugins/review_verdict{,_ci}.py
                     scripts/check-signoff.sh
                              │
                              ▼ 调用
  ③ tool/skill       .claude/commands/code-review/signoff.md
                     .claude/skills/code-review-signoff/
                     .claude/skills/feature-lifecycle-manager/   (check-signoff wrapper 判定)
                     .claude/skills/code-review-report/          (待 sign-off 模板)
                     .claude/agents/code-quality-reviewer.md     (human_signoff 禁写说明)
                              │
                              ▼ 编排
  ④ workflow yaml   .claude/workflows/requirement/standard-8phase.yaml
                     6 节点 *-signoff
                     .claude/commands/workflow/approve.md / reject.md
```

退化原则：① 删字段 → ② 删判定 → ③ 删 CLI/SKILL + 改文案 → ④ 节点改名 *-signoff → *-confirm。形成"自上而下"的删除波及；每层都有对应 feature 单元（详细见 features.json）。

## 2. 模块切分

将 spec §实现边界 + plan.md §包含项 映射为 10 个 feature：

| Feature | 制品类别 | 入口 | 主要动作 | 依赖 |
|---|---|---|---|---|
| F-001 | ① schema | review-schema.yaml | 删 3 字段 + 3 条件 + 注释收紧规则 | none |
| F-002 | ② code | check_reviews.py + save_review.py | 删 SIGNOFF_PASS / is_signed_off / R003-R007 签字检查 / CR-1 CR-4 依赖 / CR-8 / save_review signoff parser | F-001 |
| F-003 | ② code | signoff.py + check-signoff.sh | 删文件 + 同步删 import / re-export | F-002 |
| F-004 | ② code | gate plugins review_verdict{,_ci}.py | 沿用新规，去暴露签字 error | F-002 |
| F-005 | ③ tool/skill | feature-lifecycle-manager + code-review-report + code-quality-reviewer | "check-signoff wrapper 判定" → "软确认 + review conclusion 判定"；"待 sign-off 提示" → "人工确认提示"；reviewer agent 改"只输出机器结论" | F-002 |
| F-006 | ④ workflow yaml | standard-8phase.yaml + workflow/approve.md + reject.md | 6 节点改名 + 依赖链同步 + 命令文案对齐 | none |
| F-007 | doc | context/ 多篇 + onboarding + experience + 当前需求 task 验收项 | 文案替换；历史 spec 加废弃声明 | F-001 ~ F-006 |
| F-008 | data | requirements/*/reviews/*.json（当前活跃） | 删 human_signoff 字段；不动 review_id / conclusion / score / reviewed_artifacts | F-001 |
| F-009 | ② code | scripts/gates/run.py:127 + scripts/gates/plugins/features_schema.py:106 | _REQ_ID_PATTERN 扩为接受新旧两种格式（复用 requirement_naming 正则） | none |
| F-010 | test | tests/ + 残留扫描 | pytest 全过 + scripts/gates/run.py --trigger=ci --strict + rg 残留扫描白名单 | F-001 ~ F-009 |

依赖关系：F-002 依赖 F-001；F-003 依赖 F-002（删后才能 import 验证）；F-008 依赖 F-001（删字段顺序）；F-005 依赖 F-002（判定函数下线后才改文案）；F-007 / F-010 收尾；F-006 / F-009 与主链解耦可并行。

## 3. 关键技术选型

### 选型 1：review-schema 兼容历史 review JSON 的策略

- 候选 A：批量迁移所有 review JSON（active + archived）删字段 → 一次性彻底
- 候选 B：schema 改为"忽略未知字段"，仅迁移 active；archived 历史保留 human_signoff 字段不读
- **决策**：候选 B（待澄清 C-2 收口前的工作假设；详 tech-feasibility §1.1 §4 C-2 备注）
- 理由：实施成本最低；保留历史审计链；archived 不在加载路径上不影响新 gate

### 选型 2：feature lifecycle 软确认对接

- 候选 A：在 SKILL.md 中显式描述"等待用户 approve/reject"流程，由主对话承接
- 候选 B：保留 wrapper 但改成"打印提示 + 退出 0"
- **决策**：候选 A（详 spec §代码审查后；plan.md 范围条目"修改文案与 agent 指令"）
- 理由：完全去 wrapper，回到主对话承接软确认；与 spec §设计原则"软确认不落 verdict"对齐

### 选型 3：workflow 节点改名兼容性

- 候选 A：保持兼容旧 jsonl（添加 alias 表 *-signoff → *-confirm 的反扫映射）
- 候选 B：不兼容旧 run-state.jsonl；仅对新 workflow 生效
- **决策**：候选 B（待澄清 C-3；详 tech-feasibility §1.5 §4 C-3 备注）
- 理由：当前活跃 run 仅本 REQ 在 bootstrap 节点，无 *-signoff 事件；旧 completed run 不再回放；兼容成本不划算

### 选型 4：D-001 顺带修复的复用入口

- 候选 A：在 scripts/gates/run.py 内重写一份新格式正则
- 候选 B：复用 scripts/lib/requirement_naming.py 已有的 `_LEGACY_REQUIREMENT_KEY_RE` + `_NEW_REQUIREMENT_KEY_RE`，加 `is_new_requirement_key()` 公开 helper
- **决策**：候选 B（详 tech-feasibility §1.8）
- 理由：唯一事实源；避免双轨漂移；与 REQ-2026-014 D-014 单一入口约定一致

## 4. 关键流程

### 流程 1：代码审查后软确认（场景 1）

```
  /code-review
       │
       ▼
  reviewer agents 并行（8 checker + critic + judge）
       │
       ▼
  review JSON + Markdown 报告（不含 human_signoff 字段）
       │
       ▼
  主对话提示：approve / reject ?
       │
       ├──→ approve → main agent 触发 feature-lifecycle 转 done（依赖 review conclusion 判定）
       │                  │
       │                  ├─ looks_clean & no required fixes → done
       │                  ├─ needs_attention → 需用户显式接受风险才转 done（C-1 工作假设）
       │                  └─ blocked → fail-closed
       │
       └──→ reject → 回到修复循环
```

无 verdict 字段写入；软确认仅作用于当前流程。

### 流程 2：phase-transition gate（场景 2）

```
  scripts/gates/run.py --trigger=phase-transition
       │
       ▼
  GATE-REVIEW-VERDICT plugin
       │
       ▼
  check_reviews.R001 / R002 / R003 / R004 / R005 / R006 / R007
       │      （R003/R007 不再校验 human_signoff）
       ▼
  pass / fail
```

R003 仅判 conclusion ≠ blocked/rejected；R007 仅判 done feature 有 latest code review 且 conclusion 不为 blocked/rejected。

### 流程 3：workflow approval（场景 3）

`/workflow:approve` / `/workflow:reject` 不变，仅作用对象从 `*-signoff` 节点切到 `*-confirm`；底层 workflow_approve.py / workflow_reject.py 无逻辑修改。

## 5. 待澄清（沿用 requirement.md）

C-1 ~ C-4 沿用 requirement.md §待澄清清单 中的清单。本阶段以"工作假设"形式继续推进；detail-design 阶段做最终决策（来源：requirements/20260519-remove-human-signoff/artifacts/requirement.md:106）。

## 6. 结构级开放问题

- **AC-A1**：F-008 数据迁移脚本是单次手工脚本（不入 scripts/）还是入仓的可重复 CLI？建议单次 + commit message 留 trail；不入仓避免变成历史负担。
- **AC-A2**：F-009 加 `is_new_requirement_key()` 公开 helper 是否需要本期同时发布到 workflow_run.py / common.py 等所有 ID 校验入口？建议本期仅 gate 层，其它入口后续 follow-up。
