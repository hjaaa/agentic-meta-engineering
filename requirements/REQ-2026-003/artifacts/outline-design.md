---
id: REQ-2026-003
title: 代码审查人类必经卡点（路由确认 + 结论 sign-off）
phase: outline-design
created_at: 2026-04-29T22:50:00+08:00
refs-design: true
---

# REQ-2026-003 · 概要设计

## 1. 设计目标 / 总体架构

### 1.1 目标对齐

把 `/code-review` 流水线由「AI 单链路闭环」改造成「AI 建议 + 人类必经两卡」结构。改造范围严格限制在**编排层 + verdict schema + 下游门禁判定**三处，不动 8 个 checker 的内部检查规则（来源：requirements/REQ-2026-003/artifacts/requirement.md:101）。

### 1.2 总体架构

升级后的 `/code-review` 编排：

```
┌─────────────────────────────────────────────────────────────────────────┐
│  /code-review                                                           │
│                                                                         │
│  ① code-review-prepare                                                  │
│     ├─ 扫 diff，按规则给 checker_route 建议                             │
│     ├─ 卡点 A：tty 等开发者输入（accept / all / abort）                 │
│     └─ 写 .review-scope.json（含 routing_confirmed_by）                 │
│                                                                         │
│  ② 8 个或子集 checker 并行执行                                          │
│                                                                         │
│  ③ review-critic 对抗验证                                               │
│                                                                         │
│  ④ code-quality-reviewer (Judge)                                        │
│     └─ 输出三档机器评估：looks_clean / needs_attention / blocked        │
│        （禁止 approved；通过 review-schema.yaml 枚举校验）              │
│                                                                         │
│  ⑤ code-review-report 渲染 Markdown 报告（含"待 sign-off"段）           │
│                                                                         │
│  ───  /code-review 返回；流水线结束，但 verdict 未签字 ──                │
│                                                                         │
│  ⑥ 开发者另起 /code-review:signoff <REV-ID> [--trivial]                 │
│     ├─ 卡点 B：Command 预检 tty + verdict 存在                          │
│     ├─ 委托 code-review-signoff Skill 写 human_signoff 字段             │
│     └─ save_review.py 校验 schema → 落盘                                │
│                                                                         │
│  ⑦ feature-lifecycle-manager 转 done 时调用 is_signed_off(verdict)      │
│     └─ 仅 human_signoff.decision ∈ {approved, approved-trivial} 放行   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 与 plan.md 决策的对应关系

| 决策 | 落点 |
|---|---|
| D-001 双卡点 | 卡点 A（步骤①）+ 卡点 B（步骤⑥） |
| D-002 AI 三档 | 步骤④ + review-schema.yaml 枚举升级 |
| D-003 tty 校验 | 步骤①与⑥的 Command 预检 + Skill 拒签逻辑 |
| D-005 `--all` 兜底 | 步骤①接收 `--all`，跳过路由建议直接全跑 |
| D-006 trivial 通道 | 步骤⑥接收 `--trivial`，路径白名单判定 + decision = approved-trivial |
| D-007 删除零 finding 旁路 | 步骤②/③/④/⑤之间无快速路径——`.claude/commands/code-review.md:40` 删除 |
| D-008 GATE 升级 | 步骤⑦的 helper 同时被 GATE-REVIEW-VERDICT 调用，判定双口径一致 |

## 2. 模块划分

| # | 模块 | 路径 | 改动类型 | 职责（一句话） | 行数预估 |
|---|---|---|---|---|---|
| M1 | code-review-prepare Skill | `.claude/skills/code-review-prepare/SKILL.md` + `reference/scope-schema.md` | 改 | 加路由建议 + tty 确认 + `--all` 标志；scope-schema 加 4 字段 | +60 |
| M2 | /code-review Command | `.claude/commands/code-review.md` | 改 | **删 L40 零 finding 快速路径**；编排顺序保持 | -3 |
| M3 | code-quality-reviewer Agent | `.claude/agents/code-quality-reviewer.md` | 改 | conclusion 三档替换；结论规则重写（L199-205） | +20 / -8 |
| M4 | review-schema 唯一事实源 | `context/team/engineering-spec/review-schema.yaml` | 改 | conclusion 枚举替换；新增 human_signoff 子 schema 与 signoff_decision 枚举 | +30 |
| M5 | save_review.py CR 规则 | `scripts/lib/save_review.py` | 改 | CR-1 / CR-4 适配新枚举；新增 CR-7 conclusion 枚举校验；新增 signoff 子命令 | +80 |
| M6 | check_reviews.is_signed_off helper | `scripts/lib/check_reviews.py` | 改 | 提供共享判定 helper；R003/R007 升级查 human_signoff | +40 |
| M7 | feature-lifecycle-manager Skill | `.claude/skills/feature-lifecycle-manager/SKILL.md` | 改 | done 转换调 is_signed_off，移除字符串 `approved` 硬编码 | +5 / -3 |
| M8 | code-review:signoff Command（新） | `.claude/commands/code-review/signoff.md` | 新 | < 100 行；预检 + 委托 Skill；接收 `<REV-ID>` 与 `--trivial` | < 80 |
| M9 | code-review-signoff Skill（新） | `.claude/skills/code-review-signoff/SKILL.md` + `reference/` | 新 | tty 校验、trivial 路径判定、写 human_signoff 字段、调 save_review 校验 | < 1500 字 |
| M10 | code-review-report Skill | `.claude/skills/code-review-report/SKILL.md` | 改 | 报告模板加路由说明段 + 待 sign-off 提示段；删除"零 finding 时该项为空"豁免 | +15 / -3 |
| M11 | 旧 verdict 处置策略 | `scripts/lib/save_review.py`（启动期校验）| 改 | 升级后旧 verdict（无 human_signoff）一律视为未签——见 §3.3 兼容性策略 | +10 |
| M12 | ai-collaboration 硬规则 | `context/team/ai-collaboration.md` | 改 | 加"AI 不得自代签 sign-off / 不得绕过 tty 校验"硬规则 | +5 |
| M13 | engineering-spec 留档 | `context/team/engineering-spec/specs/2026-04-29-code-review-human-checkpoints.md` | 新 | 双卡点机制规范（决策记录 + 兼容性策略 + 异常矩阵） | ~250 |

### 2.1 删除点说明（M2 / D-007）

`.claude/commands/code-review.md:40` 现有原文（来源：.claude/commands/code-review.md:40）：

> **零 finding 快速路径**：若 8 个 checker 全部返回空 issues，直接跳到第 4 步输出 `approved` 报告，不调 critic / 不调综合 reviewer。

**操作**：整段删除，连同其下的"不调 critic / 不调综合 reviewer"约束。删除后所有 review 路径必经 critic + quality-reviewer + sign-off。

**连锁改动**：
- M10 `code-review-report` 模板里"零 finding 快速路径时该项为空"豁免说明（来源：.claude/skills/code-review-report/SKILL.md:14）一并删除
- M3 `code-quality-reviewer` 在收到全空 issues 输入时，输出 conclusion = `looks_clean`（不是直接放行）
- 测试覆盖：仓库内对该旁路是否存在硬依赖测试或文档，待 detail-design 阶段全仓 grep 复核（详见本文末「待澄清清单」第 1 条）

## 3. 关键流程

### 3.1 正常路径时序

#### 3.1.1 卡点 A（审前路由确认）

| 步骤 | 动作方 | 输入 | 输出 |
|---|---|---|---|
| A1 | code-review-prepare | 当前 diff | 候选 checker_route + skipped_checkers + 跳过原因 |
| A2 | code-review-prepare | tty stdin | 等待 `accept`/`all`/`abort`/`<n,m,...>` |
| A3 | code-review-prepare | 用户决定 | 写 `.review-scope.json`，含 routing_confirmed_by 子段 |
| A4 | /code-review | scope.json | 派发对应 checker |

异常矩阵（卡点 A）：

| 异常 | 退出码 | stderr 关键串 |
|---|---|---|
| stdin 非 tty 且未带 `--all` / `--trivial` 标志 | 2 | `routing: stdin not a tty, refuse interactive confirmation` |
| 用户输入 `abort` | 0（流程正常退出） | `routing: aborted by user` |
| 用户输入非法 token | 1 | `routing: invalid token <x>` |

#### 3.1.2 卡点 B（审后 sign-off）

| 步骤 | 动作方 | 输入 | 输出 |
|---|---|---|---|
| B1 | dev | 命令行 | `/code-review:signoff <REV-ID> [--trivial]` |
| B2 | signoff Command | argv + tty 状态 | 预检通过则委托 Skill；否则退出码 2 |
| B3 | code-review-signoff Skill | REV-ID + diff（trivial 模式需扫文件）| 调用 save_review.py signoff 子命令 |
| B4 | save_review.py signoff | verdict 文件 + decision | 写 `human_signoff: { decision, signed_at, signed_by, source }` + schema 校验 + append process.txt |
| B5 | feature-lifecycle-manager（异步） | verdict 文件 | 下次 done 转换时调用 is_signed_off → 放行 |

异常矩阵（卡点 B）：

| 异常 | 退出码 | stderr 关键串 |
|---|---|---|
| stdin 非 tty（非 trivial 模式） | 2 | `signoff: stdin not a tty, refuse to sign for AI` |
| verdict 文件不存在 | 4 | `signoff: verdict <REV-ID> not found` |
| 已签过 | 5 | `signoff: already signed by <email> at <time>` |
| trivial 通道含非文档文件 | 3 | `trivial: non-doc files detected: <paths>` |
| signoff_decision 非法值 | 1 | `signoff: invalid decision <x>, expected one of [approved, approved-trivial, rejected]` |

退出码分配遵守与 requirement.md 场景 3 的契约（来源：requirements/REQ-2026-003/artifacts/requirement.md:69）：tty 校验失败固定为 2，与 schema 校验失败的退出码 1 区分。

### 3.2 AI 试图代签的阻断点

按 D-003 / requirement.md 场景 3，三层防御：

1. **Command 层**：`signoff.md` 预检 `[ -t 0 ]`，非 tty 立刻 exit 2
2. **Skill 层**：`code-review-signoff` 重复 tty 校验（防 Command 被绕过直接调 Skill）
3. **CR 层**：`save_review.py` `_check_cr_rules` 新增 CR-8——human_signoff.source 必须在白名单 `[cli-tty]`，未来扩展 PR Review 时再扩枚举（D-004 out of scope 不在本期）

辅助约束：`context/team/ai-collaboration.md` 加硬规则（M12），明文禁止 AI 在主对话或子 Agent 中调用 `/code-review:signoff` / `save-review.sh signoff`（违反则视为流程违规，由人类发现并回滚）。

### 3.3 兼容性策略——旧 verdict 处置

按 requirement.md 第 75 行（来源：requirements/REQ-2026-003/artifacts/requirement.md:75）与 D-002 Consequences：

- 旧 verdict（无 `human_signoff` 字段或 `conclusion ∈ {approved, needs_revision, rejected}`）：
  - 升级后 `is_signed_off()` 一律返回 false → 视为"未签字"
  - feature-lifecycle-manager / GATE-REVIEW-VERDICT 立刻拦截
  - 所有"已 done 但 verdict 未签"的 feature **不会被回退**（done 状态保留），只有"待转 done"的 feature 受影响
- 一次性迁移脚本（M11 内嵌或独立脚本）：
  - 干跑模式：扫 `requirements/*/reviews/*.yaml`，列出所有 conclusion ∈ {approved} 的旧 verdict
  - 用户决定后再批量重签或保留——不强制自动转换（避免幻觉式签字）

## 4. 接口契约

### 4.1 .review-scope.json 升级（M1）

新增 4 字段（来源：requirements/REQ-2026-003/artifacts/requirement.md:85）：

```jsonc
{
  // ...现有字段保留
  "checker_route": [                      // AI 建议跑的 checker 子集
    "security-checker",
    "complexity-checker"
  ],
  "skipped_checkers": [                   // R2 风险落盘，事后可审计
    {"name": "concurrency-checker", "reason": "diff 无并发原语命中"}
  ],
  "mode_hint": "default",                 // "default" | "all" | "trivial"
  "routing_confirmed_by": {               // 卡点 A 输出
    "decision": "accept",                 // "accept" | "all" | "custom" | "abort"
    "confirmed_at": "2026-04-29T22:55:00+08:00",
    "confirmed_by": "huangjian@example.com",
    "tty_verified": true
  }
}
```

字段约束：
- `checker_route`：8 个 checker 名的子集，元素互斥；空数组合法（仅命中 mode_hint=trivial 时）
- `routing_confirmed_by.decision = "all"` ⇔ `checker_route` 等于 8 个 checker 全集（D-005）
- `routing_confirmed_by.decision = "abort"` ⇒ 流程已退出，scope.json 不应被消费

### 4.2 review-schema.yaml 升级（M4）

```yaml
enums:
  conclusion:                # 替换：旧值 [approved, needs_revision, rejected]
    - looks_clean
    - needs_attention
    - blocked
  signoff_decision:          # 新增
    - approved
    - approved-trivial
    - rejected
  signoff_source:            # 新增（D-003 + D-004 out of scope，仅 cli-tty）
    - cli-tty

fields:
  conclusion:
    required: true
    enum: conclusion
  human_signoff:
    required: false          # AI 输出 verdict 时缺省；卡点 B 后填充
    schema:
      decision:    { required: true, enum: signoff_decision }
      signed_at:   { required: true, format: iso8601 }
      signed_by:   { required: true, format: email }
      source:      { required: true, enum: signoff_source }
```

**未来扩展兼容性策略**：D-004 已声明 PR Review 等价 sign-off 完全 out of scope，但 schema 演进留两条意图记录——
1. `cli-tty` 始终保持为 `signoff_source` 合法值（即便未来扩到 `pr-review`，旧 verdict 不需要重写 source 字段）
2. 新增枚举值采用「append 不替换」原则；新值必须同时在 review-schema.yaml 与 save_review.py 的 CR-8 校验中扩，且新值默认不进入 `is_signed_off()` 接受集合，需独立评审决定
   —— 这条记录避免未来扩展者把 `pr-review` 一刀加进接受集合而绕过本期审慎设计

### 4.3 save_review.py CR 规则升级（M5）

| 规则 ID | 升级 | 描述 |
|---|---|---|
| CR-1 | 改 | `human_signoff.decision ∈ {approved, approved-trivial}` ⇒ `required_fixes` 必须为空（语义平移自旧"approved → required_fixes 空"） |
| CR-4 | 改 | `human_signoff.decision != ""` ⇒ `score >= 70`（人不能给低分签字） |
| CR-7 | 新 | `conclusion` 必须命中 `enums.conclusion` —— 拦截 AI 写出 `approved`（schema 层兜底防 D-002 漂移） |
| CR-8 | 新 | `human_signoff.source` 必须命中 `enums.signoff_source`（防 PR Review 等价 sign-off 在未升级前被偷偷写入） |
| signoff 子命令 | 新 | `save-review.sh signoff <REV-ID> --decision=<v> [--trivial]`：tty 预检、字段写入、CR 全量重跑、process.txt append |

### 4.4 check_reviews.is_signed_off helper（M6）

```python
def is_signed_off(verdict: dict) -> bool:
    """REQ-2026-003 双卡点 sign-off 判定，feature-lifecycle-manager 与
    GATE-REVIEW-VERDICT 必须共用此 helper 避免双轨。"""
    sig = verdict.get("human_signoff") or {}
    return sig.get("decision") in {"approved", "approved-trivial"}
```

R003 / R007 / 新增 R008（按需）调用 `is_signed_off`；feature-lifecycle-manager 通过 `python3 -c "from scripts.lib.check_reviews import is_signed_off; ..."` 间接调用，或在 SKILL.md 直接给 bash 包装。具体实现路径在 detail-design 阶段定。

**强约束（禁止绕过 helper）**：

- ❌ feature-lifecycle-manager / GATE-REVIEW-VERDICT 严禁直接对 verdict 文件做字符串匹配 `decision == "approved"` 或 `grep approved` 自行解析 `human_signoff.decision`
- ✅ 两条候选实现路径（bash python3 一行式 / 独立 helper script）必须共用同一段 Python 代码即 `is_signed_off`；新增判定方一律走 helper
- ✅ 当判定语义需扩展（如未来加 `approved-trivial` 之外的新 decision）时，只在 `is_signed_off` 一处调整，不允许在调用方各自维护接受集合
  —— 这条收口避免 R-O2 在 detail-design 阶段被双轨实现，并确保 testing 阶段对"双轨一致性"维度可单测一处覆盖两端

### 4.5 code-review:signoff CLI（M8）

```
/code-review:signoff <REV-ID> [--decision=<v>] [--trivial]

Options:
  --decision=<v>   approved | approved-trivial | rejected
                   缺省时进入交互确认（提示 "type APPROVE / TRIVIAL / REJECT"）
  --trivial        快速通道；自动设 decision=approved-trivial 并校验路径白名单
                   要求 diff 中所有文件命中 *.md / docs/** / *.txt（D-006）
                   非全命中：退出码 3，stderr 含 trivial: non-doc files detected

Exit codes:
  0  签字成功
  1  schema 校验失败 / 非法 decision
  2  stdin 非 tty
  3  trivial 通道路径不命中
  4  REV-ID 不存在
  5  已签过
```

## 5. 与需求场景的对应

| requirement.md 场景 | 落点（模块 + 步骤） |
|---|---|
| 场景 1 主流程 步骤 1-4（路由确认）| M1 / M2，§3.1.1 卡点 A |
| 场景 1 主流程 步骤 5（judge 出三档）| M3 / M4，§4.2 conclusion 枚举升级 |
| 场景 1 主流程 步骤 6（"待 sign-off"提示）| M10 报告模板 |
| 场景 1 主流程 步骤 7-8（sign-off 写入）| M8 / M9 / M5 signoff 子命令，§3.1.2 卡点 B |
| 场景 1 主流程 步骤 9（feature-lifecycle-manager 校验）| M6 / M7，§4.4 is_signed_off helper |
| 场景 1b（trivial 通道） | M8 `--trivial` 标志 + M5 路径白名单校验 + M9 自动写 decision=approved-trivial |
| 场景 2（独立模式） | M1-M5 全部生效；M7 不接入（独立模式无 feature-lifecycle-manager），仅靠 CLI 拒签生成签结报告 |
| 场景 3（AI 代签拦截） | §3.2 三层防御（Command / Skill / CR-8）+ M12 ai-collaboration 硬规则 |
| 范围/包含 GATE-REVIEW-VERDICT 升级 | M6 R003/R007 升级（D-008 修订口径，与 feature-lifecycle-manager 共用 is_signed_off helper） |
| 范围/包含 删除零 finding 旁路 | M2 §2.1 删除点，连锁改动 M10 |

## 6. 边界与排除项

- ❌ 不动 8 个 checker 的内部检查规则（complexity / security / concurrency / performance / error-handling / design-consistency / history-context / auxiliary-spec）——本需求只动编排层（来源：requirements/REQ-2026-003/artifacts/requirement.md:101）
- ❌ 不实现一份共享的 checker 输出契约骨架（前一轮审查发现的 P0 问题，归独立 REQ）
- ❌ 不实现 GitHub PR Review 等价 sign-off（D-004 完全 out of scope；schema 层 `signoff_source` 枚举仅 `cli-tty`，不留 `pr-review` 字面量预留）
- ❌ 不强制自动转换旧 verdict（M11 仅提供干跑迁移脚本，转换由用户显式触发）
- ❌ 不修改 requirement-level 流程（`/requirement:next` / `/requirement:submit`）的 schema；submit 升级仅落在 GATE-REVIEW-VERDICT 一处（D-008）

## 7. 风险与已识别假设

| ID | 风险 / 假设 | 严重度 | 缓解 |
|---|---|---|---|
| R-O1 | conclusion 枚举重命名（approved → looks_clean）会破坏既有 verdict 文件 | 高 | M11 干跑脚本 + 升级文档显式说明；feature-lifecycle-manager done 转换降级为"未签字"——不强制重跑 review |
| R-O2 | M6 helper 在 feature-lifecycle-manager（Skill / Bash）调用方式未定 | 中 | detail-design 阶段确定（候选：bash python3 一行式 / 单独 helper script） |
| R-O3 | 卡点 A 的 tty 交互在某些 IDE 终端可能伪装为 tty | 中 | tty 校验 + ppid 链检测留待 detail-design 评估；初版仅 `[ -t 0 ]`，配合 ai-collaboration 硬规则兜底 |
| R-O4 | 删除 `code-review.md:40` 后零 finding 场景仍跑 critic + judge，仪式偏重 | 低 | `--trivial`（D-006）+ `--all`（D-005）配合，"小改但非纯文档"暂时接受多按一次确认 |
| R-O5 | M5 signoff 子命令与既有 save-review.sh 的命名冲突 | 低 | detail-design 阶段确认子命令在 save-review.sh 还是新 CLI；本设计暂归 save_review.py 复用 schema 校验链 |

## 8. 验证维度（detail-design 阶段细化）

| 维度 | 关键验证点 |
|---|---|
| 端到端 | 场景 1 主流程一遍跑通：prepare 卡 tty → checker → judge → signoff → feature 转 done |
| 退出码 | 卡点 A / B 的 7 种异常退出码全部命中（详见 §3.1 矩阵） |
| schema 校验 | review-schema.yaml 升级后旧 verdict 一律拒收；新 verdict 补 human_signoff 后通过 |
| AI 代签 | 在 non-tty 环境（CI / Hook / 子 Agent shell）调 `signoff` 必须 exit 2 |
| 双轨一致性 | feature-lifecycle-manager 与 GATE-REVIEW-VERDICT 对同一 verdict 给出相同放行/拒绝结论 |

---

_本文档由 outline-design 阶段产出，与 plan.md 决策（D-001 ~ D-008）、requirement.md 场景（1 / 1b / 2 / 3）逐一对应。详细设计阶段以本文档 §2 模块表为输入，逐模块产出接口签名 / 数据结构 / 时序图，并落 features.json。_

## 待澄清清单

- §2.1 删除 `.claude/commands/code-review.md:40` 旁路后，仓库内是否仍有测试或文档对该旁路存在硬依赖？[待用户确认]——计划在 detail-design 阶段以全仓 grep `零 finding 快速路径` / `approved` 字面量复核，若发现需在 features.json 增加清理任务。
