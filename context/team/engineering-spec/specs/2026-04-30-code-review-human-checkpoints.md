# 代码审查人类必经卡点 · 设计留档

**日期**：2026-04-30
**作者**：huangjian
**状态**：已落地（REQ-2026-003 F-004b 实施完成）
**关联文档**：
- `requirements/REQ-2026-003/artifacts/detailed-design.md`（权威设计源）
- `context/team/engineering-spec/specs/2026-04-27-reviewer-verdict-structuring-design.md`（前置设计：verdict 结构化）
- `scripts/lib/check_reviews.py`（is_signed_off helper + R003/R007）
- `scripts/check-signoff.sh`（sign-off 判定 wrapper）
- `context/team/ai-collaboration.md`（规则三：sign-off 是人类专属动作）

---

## 1. 引言：双卡点总览

REQ-2026-003 为代码审查流程引入两个人类必经卡点，确保 AI 无法独自通过审查门禁：

| 卡点 | 触发时机 | 目的 |
|---|---|---|
| **A · 路由确认** | `/code-review` 发起前 | 人类确认 reviewer 路由方向（完整 or trivial） |
| **B · sign-off** | AI 出 verdict 后、feature 转 done 前 | 人类签字确认结论，写入 human_signoff 字段 |

**关键设计决策引用（D-001 ~ D-010）**：

| 决策代号 | 内容摘要 | 落地位置 |
|---|---|---|
| D-001 | 两卡点都以 tty 校验为第一道防线 | `/code-review` Command + signoff Command |
| D-002 | 旧 verdict conclusion=approved 不视同 sign-off，强制重签 | F-001.4 干跑脚本 + cutover 清单 |
| D-003 | 路由确认输出写 `.review-scope.json`，供后续 reviewer 读取 | 卡点 A CLI |
| D-004 | signoff_source 本期仅 cli-tty，预留 PR-review 扩展 | review-schema CR-8 |
| D-005 | approved-trivial 与 approved 在 is_signed_off 等价 | SIGNOFF_PASS 常量 |
| D-006 | 三层防御：Command 预检 / Skill 二次校验 / CR-8 schema 拒收 | 见第 6 节 |
| D-007 | 不做 ppid 链检测（成本高于收益），硬规则兜底 | ai-collaboration.md 规则三 |
| D-008 | R003/R007 升级：必须 human_signoff 才放行 | check_reviews.py |
| D-009 | wrapper 脚本 check-signoff.sh 是唯一合法判定入口 | scripts/check-signoff.sh |
| D-010 | F-004 任务拆分：F-004a / F-004b 并行（D-010 放宽前置） | 任务规划阶段 |

---

## 2. 卡点 A：路由确认

### CLI 行为

```
/code-review [--all | --trivial]
```

- 无 flag 时：tty 校验通过后，弹出交互菜单，用户选择路由方向
- `--all`：跳过确认，直接走完整路由
- `--trivial`：跳过确认，走 trivial 通道（仅文档变更）

### `.review-scope.json` 4 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `req_id` | string | 需求 ID |
| `feature_id` | string | feature ID（null = 全量） |
| `routing` | string | `full` 或 `trivial` |
| `confirmed_by` | string | 确认人 email |

### 退出码（卡点 A）

| 情形 | 退出码 | stderr 关键串 |
|---|---|---|
| stdin 非 tty 且未带 --all/--trivial | 2 | `routing: stdin not a tty, refuse interactive confirmation` |
| 用户输入 abort | 0 | `routing: aborted by user` |
| 用户输入非法 token | 1 | `routing: invalid token <x>` |

---

## 3. 卡点 B：sign-off

### CLI 行为

```
/code-review:signoff <REV-ID> [--trivial]
```

- 调用前做 tty 校验（`[ -t 0 ]`）；非 tty 直接退出码 2
- 读取 `requirements/<REQ>/reviews/<suffix>.json`
- 填充 `human_signoff` 字段（decision / signed_at / signed_by / source）
- 写回 verdict 文件

### `human_signoff` 字段

| 子字段 | 类型 | 约束 |
|---|---|---|
| `decision` | string | `approved` / `approved-trivial` / `rejected` |
| `signed_at` | string | ISO 8601 含时区（e.g. `2026-04-30T14:30:00+0800`） |
| `signed_by` | string | email 格式 |
| `source` | string | 本期仅 `cli-tty` |

### 退出码（卡点 B）

| 情形 | 退出码 | stderr 关键串 |
|---|---|---|
| stdin 非 tty | 2 | `signoff: stdin not a tty, refuse to sign for AI` |
| verdict 文件不存在 | 4 | `signoff: verdict <REV-ID> not found` |
| 已签过 | 5 | `signoff: already signed by <email> at <time>` |
| trivial 通道含非文档文件 | 3 | `trivial: non-doc files detected: <paths>` |
| signoff_decision 非法值 | 1 | `signoff: invalid decision <x>, expected one of [approved, approved-trivial, rejected]` |

---

## 4. Schema 升级（CR-7 / CR-8）

**CR-7**：`conclusion` 字段必须命中新枚举 `{looks_clean, needs_attention, blocked}`，阻断 AI 残留写 `approved`。

```
CR-7: conclusion 'approved' not in enum [looks_clean, needs_attention, blocked]
```

**CR-8**：`human_signoff.source` 必须 ∈ `{cli-tty}`，拒绝非 CLI 来源的 sign-off。

```
CR-8: human_signoff.source '<x>' not in [cli-tty]
```

新旧枚举平移关系：

| 旧 conclusion | 新 conclusion |
|---|---|
| `approved` | `looks_clean` |
| `needs_revision` | `needs_attention` |
| `rejected` | `blocked` |

---

## 5. 异常退出码完整矩阵

| 卡点 | 异常 | 退出码 | stderr 关键串 |
|---|---|---|---|
| A | stdin 非 tty 且未带 --all/--trivial | 2 | `routing: stdin not a tty, refuse interactive confirmation` |
| A | 用户输入 abort | 0 | `routing: aborted by user` |
| A | 用户输入非法 token | 1 | `routing: invalid token <x>` |
| B | stdin 非 tty | 2 | `signoff: stdin not a tty, refuse to sign for AI` |
| B | verdict 文件不存在 | 4 | `signoff: verdict <REV-ID> not found` |
| B | 已签过 | 5 | `signoff: already signed by <email> at <time>` |
| B | trivial 通道含非文档文件 | 3 | `trivial: non-doc files detected: <paths>` |
| B | signoff_decision 非法值 | 1 | `signoff: invalid decision <x>, expected one of [approved, approved-trivial, rejected]` |
| schema | conclusion=approved（AI 残留） | 1 | `CR-7: conclusion 'approved' not in enum [looks_clean, needs_attention, blocked]` |
| schema | source ∉ [cli-tty] | 1 | `CR-8: human_signoff.source '<x>' not in [cli-tty]` |

退出码 2（tty 校验失败）与退出码 1（schema/参数失败）刻意区分，便于 CI 测试断言。

---

## 6. 三层防御

### 第一层：Command 预检（tty 校验）

`/code-review:signoff` Command 在调用 `save_review.py signoff` 前先做 `[ -t 0 ]` 校验，AI shell 直接被拒（退出码 2）。

### 第二层：Skill 二次校验

`code-review-signoff` Skill 在执行签字动作前再次确认当前是否为人类交互会话，非 tty 不执行写操作。

### 第三层：CR-8 schema 拒收非 cli-tty

`save_review.py` 写入 verdict 时触发 `_check_cr_rules`，CR-8 校验 `human_signoff.source == "cli-tty"`，非法值直接拒绝写盘（退出码 1）。任何绕过 tty 校验但设置了错误 source 的尝试都会被此层兜底。

---

## 7. 旧 verdict cutover 清单

本清单提供升级当日的处置步骤（来源：detailed-design.md §F-004.6）。

### 操作步骤

**步骤 1 · 预检**

```bash
python3 scripts/lib/migrate_review_v2.py --dry-run
```

得到全仓未签 verdict 列表，输出格式：`<REV-ID>  phase=<phase>  req=<REQ-ID>  status=<needs_signoff|skip>`

**步骤 2 · 分类**

| 条件 | 处置 |
|---|---|
| `phase ∈ {definition, tech-research, outline-design, detail-design}` 且对应需求处于 development+ 阶段 | 建议**重签**（不必重审），减小 development 阻断 |
| `phase = code` 且对应需求处于 testing 阶段 | 必须**重审**，由 reviewer 重新评估三档 |
| 已 completed/abandoned 的需求 | **不处理**（保持历史，不入新判定路径） |

**步骤 3 · 执行**

- 重签：开发者本人对每个 verdict 跑 `/code-review:signoff <REV-ID>` 或加 `--trivial`
- 重审：跑 `/code-review`（嵌入模式），生成新 verdict 后再签

**步骤 4 · 验收**

```bash
# 门禁全通过
python3 scripts/gates/run.py --trigger=ci

# 所有进行中需求不含 stale verdict
grep -r 'stale: true' requirements/*/meta.yaml
```

**不强制全仓重签**——已 completed/abandoned 需求保留旧字段，不入新判定流程。

### GATE 触发面与 cutover 范围的张力消解

> **GATE 触发面与 cutover 范围的张力消解**：GATE-REVIEW-VERDICT 在 phase-transition / submit / pre-commit / ci 时触发。本 cutover 范围**仅含进行中需求**（has un-done feature 或 phase ≠ completed/abandoned），其旧 verdict 在升级后第一次切阶段就会被阻断——这是有意的：阻断本身就是 cutover 信号，开发者按上述 4 步分类处理即可放行。已 completed/abandoned 需求不会再触发 phase-transition / submit，旧 verdict 自然不入判定路径，无需迁移。
>
> 如果某个进行中需求短期不打算切阶段（如挂起的 stash 分支），其旧 verdict 不需立刻处理；下次 resume 时按本清单走即可。

---

## 附录：is_signed_off 判定逻辑

所有下游系统通过 `scripts/check-signoff.sh <verdict.json>` 判定，退出码 0=已签 / 1=未签。
禁止在调用方自行 grep / awk / jq 解析 `human_signoff.decision`——所有判定必须通过此 wrapper。

```python
# scripts/lib/check_reviews.py
SIGNOFF_PASS: set[str] = {"approved", "approved-trivial"}

def is_signed_off(verdict: dict) -> bool:
    sig = verdict.get("human_signoff") or {}
    return sig.get("decision") in SIGNOFF_PASS
```

`approved-trivial` 与 `approved` 在 is_signed_off 判定下等价（都进入 SIGNOFF_PASS），
但下游审计可单独统计（区分普通签字与 trivial 快速通道）。
