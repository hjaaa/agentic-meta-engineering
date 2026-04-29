---
id: REQ-2026-003
title: 代码审查人类必经卡点（路由确认 + 结论 sign-off）· 详细设计
phase: detail-design
created_at: 2026-04-30T00:25:00+08:00
refs-detail-design: true
---

# REQ-2026-003 · 详细设计

本文档以 features.json 的 4 个 feature 为主线，逐 feature 给出**接口签名 / 数据契约 / 时序 / 边界 / 测试要点**。outline-design.md §2 的 13 模块映射到 4 个 feature 的对应关系详见各 feature 头部「模块映射」段。

---

## F-001 · review-schema 升级 + save_review CR 扩展 + 旧 verdict 处置基础

### F-001.1 模块映射
- M4 review-schema.yaml
- M5 save_review.py（CR-7 / CR-8 + 枚举平移）
- M11 旧 verdict 干跑迁移脚本骨架

### F-001.2 review-schema.yaml 精确变更

**Schema diff 写法清单**（实施者按本清单依次落地，避免误把替换写成 append）：

| 操作 | 段落 | 字段 |
|---|---|---|
| 整体替换 | `enums.conclusion` | 旧 [approved, needs_revision, rejected] → 新 [looks_clean, needs_attention, blocked] |
| append | `enums` 段 | 新增 `signoff_decision` / `signoff_source` 两个枚举（不删任何既有项） |
| append | `fields` 段 | 新增 `human_signoff` 子 schema（required: false，含 4 个子字段） |
| **不动** | `required_fields` 段 | 不增不减；`human_signoff` 在 fields 标 `required: false` 即可，不进 required_fields 列表 |

**变更前**（来源：context/team/engineering-spec/review-schema.yaml:46）：

```yaml
enums:
  conclusion:
    - approved
    - needs_revision
    - rejected
```

**变更后**：

```yaml
enums:
  conclusion:                           # 替换：AI 三档机器评估
    - looks_clean                       # 旧 approved 平移
    - needs_attention                   # 旧 needs_revision 平移
    - blocked                           # 旧 rejected 平移
  signoff_decision:                     # 新增
    - approved
    - approved-trivial
    - rejected
  signoff_source:                       # 新增；D-004 out of scope，仅 cli-tty
    - cli-tty

fields:
  conclusion:
    required: true
    enum: conclusion
  human_signoff:
    required: false                     # AI 出 verdict 时缺省；卡点 B 后填充
    schema:
      decision:    { required: true, enum: signoff_decision }
      signed_at:   { required: true, format: iso8601 }
      signed_by:   { required: true, format: email }
      source:      { required: true, enum: signoff_source }
```

### F-001.3 save_review.py CR 规则签名

新增的 CR-7 / CR-8 必须**与既有 _check_cr_rules 同构**（来源：scripts/lib/save_review.py:82）——
即接收 `(verdict, report, label)` 三参数，内部调 `report.add(label, Severity.ERROR, "CR-N", msg)`，
**禁止**引入仓库不存在的 `CRViolation` 类型；返回值 `None`，错误通过 `report.add` 累积。

```python
# scripts/lib/save_review.py（增量段；既有 CR-1~CR-6 保留并按下表平移语义）

CONCLUSION_NEW: set[str] = {"looks_clean", "needs_attention", "blocked"}
SIGNOFF_DECISION_PASS: set[str] = {"approved", "approved-trivial"}


def _check_cr_rules(verdict: dict, report: Report, label: str) -> None:
    """接续既有 6 条规则；本节只列新增的 CR-7 / CR-8 + 平移后的 CR-1/3/4/6。
    完整函数体由 F-001 实施时一次替换写入，保持参数签名 (verdict, report, label) -> None。"""

    # CR-7（新增）：conclusion 必须命中新枚举——阻断 AI 残留写 approved
    if verdict.get("conclusion") not in CONCLUSION_NEW:
        report.add(
            label,
            Severity.ERROR,
            "CR-7",
            f"conclusion {verdict.get('conclusion')!r} not in enum {sorted(CONCLUSION_NEW)}",
        )

    # CR-8（新增）：human_signoff.source 必须 ∈ signoff_source 枚举（仅 cli-tty）
    sig = verdict.get("human_signoff") or {}
    src = sig.get("source")
    if sig and src != "cli-tty":
        report.add(
            label,
            Severity.ERROR,
            "CR-8",
            f"human_signoff.source {src!r} not in [cli-tty]",
        )
```

**既有 CR-1 / CR-3 / CR-4 / CR-6 的判定字段平移**（现行实现来源：scripts/lib/save_review.py:88）——
本期重命名 conclusion 枚举后，原对 `"approved"` 字符串的硬编码判定全部按下表替换；语义不变：

| 规则 | 现行（save_review.py:88-125） | 平移后 |
|---|---|---|
| CR-1 | `conclusion == "approved"` ⇒ `required_fixes == []` | `is_signed_off(verdict)` ⇒ `required_fixes == []`（语义平移：approved 通过的语义改由 human_signoff 承载） |
| CR-2 | `len(required_fixes) > 0` ⇒ `conclusion ∈ {needs_revision, rejected}` | `len(required_fixes) > 0` ⇒ `conclusion ∈ {needs_attention, blocked}`（枚举重命名） |
| CR-3 | 任一 `dim.score < 60` ⇒ `conclusion ≠ "approved"` | 任一 `dim.score < 60` ⇒ `conclusion ≠ "looks_clean"` |
| CR-4 | `score < 70` ⇒ `conclusion ≠ "approved"` | `score < 70` ⇒ `conclusion ≠ "looks_clean"`，**且** `is_signed_off(verdict)` 必须为 False（人不能给低分签字） |
| CR-6 | 任一 issue.severity=blocker ⇒ `conclusion ≠ "approved"` | 任一 issue.severity=blocker ⇒ `conclusion = "blocked"`（语义增强：不仅"非 approved"，必须正向落到 blocked 一档） |

`is_signed_off()` helper 的实现见 §F-004.4。本期 CR-1/CR-4 在 save_review.py 内部直接 import：
`from scripts.lib.check_reviews import is_signed_off`。

### F-001.4 migrate_review_v2.py 接口

```python
# scripts/lib/migrate_review_v2.py
"""
旧 verdict 干跑迁移工具——升级 review-schema.yaml 后用。

用法：
  python3 scripts/lib/migrate_review_v2.py --dry-run            # 列出所有旧 verdict 路径与 conclusion 字面值
  python3 scripts/lib/migrate_review_v2.py --apply              # 写盘转换：approved→looks_clean，其他不动
                                                                # 转换后 stale=true，强制重审或重签
"""
def scan_old_verdicts(reviews_root: Path) -> list[OldVerdict]:
    """扫 requirements/*/reviews/*.json，返回 conclusion ∈ 旧枚举的 verdict 列表。"""

def render_dry_run_report(items: list[OldVerdict]) -> str:
    """返回多行报告：每行 'path :: conclusion :: <重签建议|可平移>'。"""

def apply_rename(items: list[OldVerdict]) -> int:
    """干跑通过后 --apply 路径：仅做字面量替换 approved→looks_clean，
    其余结论保留；human_signoff 字段一律置空（强制重签）；stale 由 save-review.sh 重算覆盖。"""
```

**禁止**：自动把旧 conclusion=approved 视同 sign-off 通过（D-002 Consequences 明确"强制重签"）。

### F-001.5 测试要点

- review-schema.yaml 改完后跑 `python3 scripts/gates/run.py --validate-registry`
- save_review.py 加 CR-7/CR-8 fixture：
  - `conclusion="approved"` → 拒收，stderr 含 `CR-7: conclusion 'approved' not in enum`
  - `human_signoff.source="pr-review"` → 拒收，stderr 含 `CR-8: human_signoff.source 'pr-review'`
- migrate_review_v2.py 干跑跑全仓不写盘；--apply 在 sandbox REQ-2099-NNN 下验证

---

## F-002 · 卡点 A——code-review-prepare 路由 + tty + --all + 删除零 finding 旁路

### F-002.1 模块映射
- M1 code-review-prepare（含 reference/scope-schema.md）
- M2 .claude/commands/code-review.md（删除 L40 旁路）
- M10 部分（删除 code-review-report L14 豁免说明，路由说明段在 F-003 加）

### F-002.2 .review-scope.json 字段（增量）

```jsonc
{
  // 既有字段保留
  "checker_route": [                         // 8 个 checker 名子集
    "complexity-checker",
    "security-checker",
    "concurrency-checker",
    "performance-checker",
    "error-handling-checker",
    "design-consistency-checker",
    "history-context-checker",
    "auxiliary-spec-checker"
  ],
  "skipped_checkers": [                      // 跳过原因可审计
    {"name": "concurrency-checker", "reason": "diff 无并发原语命中"}
  ],
  "mode_hint": "default",                    // "default" | "all" | "trivial"
  "routing_confirmed_by": {
    "decision": "accept",                    // "accept" | "all" | "custom" | "abort"
    "confirmed_at": "2026-04-30T00:30:00+08:00",
    "confirmed_by": "huangjian@example.com", // git config user.email
    "tty_verified": true
  }
}
```

**字段不变量**：

| 字段 | 约束 |
|---|---|
| `checker_route` | 元素 ∈ 8-checker 全集；元素互斥；空数组仅当 `mode_hint="trivial"` |
| `routing_confirmed_by.decision == "all"` | ⇔ `checker_route` = 8 个 checker 全集 ∧ `mode_hint="all"` |
| `routing_confirmed_by.decision == "abort"` | scope.json **不应被消费**（prepare 退出后下游不读） |
| `tty_verified` | 必须 `true`（非 tty 写盘视为契约违规） |
| `routing_confirmed_by.confirmed_by` | 必须命中 RFC 5322 邮箱简化正则 `^[^@\s]+@[^@\s]+\.[^@\s]+$`；空字符串 / 主机名 / 进程 ID 均拒收（与 review-schema.yaml `human_signoff.signed_by` 的 format=email 同口径） |

### F-002.3 code-review-prepare 流程时序

```
prepare 入口
   │
   ├─ argv 含 --all？
   │     └─ Yes: 跳过路由建议；写 scope.json (mode_hint=all, checker_route=全集, decision=all, tty_verified=[ -t 0 ]结果)
   │              注：--all 仍要求 tty（防 AI 自动加 --all 绕过卡点 A）
   │
   ├─ argv 含 --trivial？
   │     └─ Yes: 仅作为 mode_hint 透传给下游（写 scope.json mode_hint=trivial），
   │              **prepare 阶段不豁免卡点 A**——仍走 default 路径的 tty 确认与 checker 路由
   │              （场景 1b 节省的是卡点 B 的人工 review，不是卡点 A 的路由确认；
   │              纯文档变更仍可能跑 auxiliary-spec-checker 抓低级错误）
   │              路径白名单判定推迟到卡点 B 的 signoff Skill（F-004.3）
   │
   ├─ default 路径：
   │     ├─ 扫 diff，按规则匹配 checker_route 候选 + skipped_checkers + 跳过原因
   │     ├─ stdin 非 tty？  → 退出码 2，stderr 'routing: stdin not a tty'
   │     ├─ tty 输入 prompt：accept / all / abort / <n,m,...> 自定义子集
   │     ├─ 用户输入解析：
   │     │     accept → checker_route=AI 建议
   │     │     all    → checker_route=8 全集，decision=all
   │     │     abort  → 退出码 0，stderr 'routing: aborted by user'，不写 scope.json
   │     │     非法   → 退出码 1，stderr 'routing: invalid token <x>'
   │     └─ 写 .review-scope.json + routing_confirmed_by 子段
   │
   └─ 触发 8 个或子集 checker 并行
```

### F-002.4 删除点 diff 摘要

`.claude/commands/code-review.md:40` 删除原文（来源：.claude/commands/code-review.md:40）：

```diff
- > **零 finding 快速路径**：若 8 个 checker 全部返回空 issues，直接跳到第 4 步输出 `approved` 报告，不调 critic / 不调综合 reviewer。
```

`.claude/skills/code-review-report/SKILL.md` 删除 3 处「零 finding」残留（来源：.claude/skills/code-review-report/SKILL.md:14）：

```diff
- (line 14) 1 份 critic 输出（review-critic 的 verdicts + summary）；**零 finding 快速路径时该项为空**
+ (line 14) 1 份 critic 输出（review-critic 的 verdicts + summary）

- (line 15) 1 份综合裁决（code-quality-reviewer 的 adjudication + merged_issues + conclusion）；**零 finding 快速路径时该项为空**
+ (line 15) 1 份综合裁决（code-quality-reviewer 的 adjudication + merged_issues + conclusion）

- (line 40) ❌ 禁止丢弃裁决明细段（即便零 finding 快速路径也要保留该段，写明"无 finding，未触发 critic / quality-reviewer"）
+ (line 40) ❌ 禁止丢弃裁决明细段（无 finding 时仍要保留该段，写明"8 checker 全空 issues，已经 critic + quality-reviewer 出 conclusion=looks_clean"）
```

**回归测试要求**：
1. 全空 issues 输入下，编排仍走完整 critic + quality-reviewer + sign-off 流程
2. quality-reviewer 收到全空 issues 时输出 `conclusion = looks_clean`（不是直接 approved）
3. `git grep '零 finding 快速路径'` 命中范围限制在：outline-design.md / detailed-design.md / requirement.md / plan.md / specs/2026-04-30-code-review-human-checkpoints.md（即仅历史/spec 文档承载该词，工具链代码与 SKILL.md 内全部清空）

### F-002.5 测试要点

| Case | 输入 | 期望 |
|---|---|---|
| TC-A1 | tty + 输入 `accept` | scope.json checker_route=AI 建议子集，decision=accept，退出 0 |
| TC-A2 | tty + 输入 `all` | scope.json checker_route=8 全集，decision=all，退出 0 |
| TC-A3 | tty + 输入 `abort` | 不写 scope.json，退出 0，stderr 'aborted by user' |
| TC-A4 | tty + 输入 `xx` | 退出 1，stderr 'invalid token xx' |
| TC-A5 | 非 tty + 无标志 | 退出 2，stderr 'routing: stdin not a tty' |
| TC-A6 | 非 tty + `--all` | **同样退出 2**（防 AI 自动加 --all 绕过） |
| TC-A7 | 全空 issues 流水线 | 走到 quality-reviewer，conclusion=looks_clean |

---

## F-003 · Judge 三档收敛 + report 模板更新

### F-003.1 模块映射
- M3 code-quality-reviewer Agent
- M5 部分（CR-1/CR-3/CR-4 在三档下的语义重写）
- M10 code-review-report Skill（路由说明段 + 待 sign-off 提示段）

### F-003.2 .claude/agents/code-quality-reviewer.md 替换段

`.claude/agents/code-quality-reviewer.md:199-205` 现行结论规则（来源：.claude/agents/code-quality-reviewer.md:199）：

```
- 无 keep 的 critical + keep 的 major ≤ 5 + keep 的 minor ≤ 20 → `approved`
- 有 keep 的 major 或 keep 的 minor > 20 → `needs_revision`
- 有 keep 的 critical → `rejected`
```

**替换为**：

```
- 无 keep 的 critical + keep 的 major ≤ 5 + keep 的 minor ≤ 20 → `looks_clean`
- 有 keep 的 major 或 keep 的 minor > 20 → `needs_attention`
- 有 keep 的 critical → `blocked`

明文禁止：
- ❌ 输出 `approved`（CR-7 在 schema 层兜底拒收，但 Agent 输入空间也禁止）
- ❌ 输出 `needs_revision` / `rejected`（旧名，已替换）
- ❌ 写入 human_signoff 字段（这是人类卡点 B 的字段，AI 不得填充）
```

### F-003.3 code-review-report 渲染段增量

模板新增两段（追加在既有 verdict 摘要段之后）：

````markdown
## 路由说明

本次审查路由由 `code-review-prepare` 卡点 A 确认：

- **决策**：`{routing_confirmed_by.decision}`
- **确认人**：`{routing_confirmed_by.confirmed_by}`
- **确认时间**：`{routing_confirmed_by.confirmed_at}`
- **跑了哪些 checker**：`{checker_route}`
- **跳过的 checker（含原因）**：
  {#each skipped_checkers}
  - `{name}`：{reason}
  {/each}

## 待 sign-off 提示

本次评审输出 `conclusion = {conclusion}`，**这只是 AI 的机器评估**，
不代表合并通过。请开发者本人执行：

```bash
/code-review:signoff {review_id}            # 对话式 sign-off
/code-review:signoff {review_id} --trivial  # 纯文档变更快速通道
```

未 sign-off 时 feature-lifecycle-manager 不会把对应 feature 转为 done，
GATE-REVIEW-VERDICT 在 phase-transition / submit 时会阻断。
````

### F-003.4 测试要点

- 三档结论规则单测（参考 outline §3.2 / 现行 reviewer 测试 fixture 改名）：
  - `no_critical_few_major` → `looks_clean`
  - `has_major` → `needs_attention`
  - `has_critical` → `blocked`
- report 渲染测试：scope.json 含 routing_confirmed_by 时报告含「路由说明」段；含 skipped_checkers 时含子条目

---

## F-004 · 卡点 B + 下游门禁 + 文档与 spec

> **任务粒度说明**：features.json 中 F-004 已按 reviewer 建议拆为 **F-004a（signoff CLI/Skill + save_review signoff 子命令，3.5d，依赖 F-001）** + **F-004b（下游门禁 helper / feature-lifecycle / ai-collab / spec，2d，依赖 F-001/F-002/F-003/F-004a）**。本 detail-design 章节保持「F-004」单一标题便于阅读连贯，下属各 §F-004.X 节在派发任务时按下列归属切分：
>
> - F-004a：§F-004.2 / §F-004.3（含 save_review.py argparse subparser 兼容方案）/ §F-004.7 异常退出码（卡点 B 部分）
> - F-004b：§F-004.4 / §F-004.5 / §F-004.6 / §F-004.7（schema 部分）/ §F-004.8 / §F-004.9（测试 case 中 TC-B8~B14 部分）
>
> 总人天保持 5.5（与 tech-feasibility 估算一致）。

### F-004.1 模块映射
- M5 save_review.py signoff 子命令
- M6 check_reviews.is_signed_off helper + R003/R007 升级
- M7 feature-lifecycle-manager done 判定升级
- M8 .claude/commands/code-review/signoff.md（新）
- M9 .claude/skills/code-review-signoff/ Skill（新）
- M11 cutover 清单（在 spec 文档内）
- M12 ai-collaboration.md 硬规则
- M13 specs/2026-04-30-code-review-human-checkpoints.md（新）

### F-004.2 /code-review:signoff Command 接口

`.claude/commands/code-review/signoff.md` 命令骨架（< 100 行）：

```markdown
## 用途
完成代码审查的人类卡点 B：把 human_signoff 字段写入 verdict 文件。

## 用法
/code-review:signoff <REV-ID> [--decision=<v>] [--trivial]

## 预检（Command 层职责，全部失败立即退出）
1. 检查 stdin 是 tty（[ -t 0 ]）；非 tty → 退出码 2 + stderr 'signoff: stdin not a tty, refuse to sign for AI'
2. 解析 <REV-ID>，定位 reviews/<phase>-NNN.json；不存在 → 退出码 4 + stderr 'signoff: verdict <REV-ID> not found'
3. 检查 verdict.human_signoff 是否已填；已签 → 退出码 5 + stderr 'signoff: already signed by ...'
4. 解析 --decision；非法值 → 退出码 1 + stderr 'signoff: invalid decision <x>'

## 委托
预检通过后调 Skill code-review-signoff，传入 (REV-ID, decision, --trivial flag)。
```

### F-004.3 code-review-signoff Skill 流程（< 1500 字）

> **二次 tty 校验的成本/收益**（防止未来维护者误删）：成本 ≈ 一次 `[ -t 0 ]` 系统调用（< 10ms），收益是阻断 `cat verdict.json | python3 save_review.py signoff` 这类管道注入或调用方绕过 Command 直接调用 Skill 的攻击面。Skill 改 Python 实现时等价 `sys.stdin.isatty()`。**禁止以"过度工程"为由删除**——即便 Command 层已校验过，深防御不冗余。

```
Skill code-review-signoff
  │
  ├─ 二次 tty 校验（深防御，防 Skill 被绕过 Command 直接调用；见上方注释）
  │     非 tty → 退出码 2
  │
  ├─ --trivial 路径白名单判定（仅 --trivial 模式跑）：
  │     git diff --name-only --diff-filter=ACMR <base>..HEAD
  │     全部文件路径 ∈ {*.md, docs/**, *.txt} ？
  │       Yes: decision = "approved-trivial"，继续
  │       No : 退出码 3 + stderr 'trivial: non-doc files detected: <paths>'
  │
  ├─ 取 git config user.email → signed_by
  │     date -u +%Y-%m-%dT%H:%M:%S%z → signed_at
  │     "cli-tty" → source
  │
  ├─ 调 save_review.py signoff 子命令（CLI 形式见下表）
  │
  └─ save_review.py 内部：
        ├─ 读 verdict 文件
        ├─ 写 human_signoff 字段
        ├─ 全量重跑 CR-1 ~ CR-8（含新规则）
        ├─ 通过 → 写盘 + append <req>/process.txt 评审事件
        │         事件格式: '<ts> [signoff] <REV-ID> <decision> by <email>'
        └─ 失败 → 退出码 1 + stderr CR 详情
```

**save_review.py main() argparse subparser 兼容方案**（修复 reviewer R-005）——
现行 main 是单一子命令模型（来源：scripts/lib/save_review.py:201），新加 signoff 必须升级为 argparse subparser，与既有 save-review.sh 调用兼容：

```python
def main() -> int:
    parser = argparse.ArgumentParser(description="写入 review JSON / 签字")
    sub = parser.add_subparsers(dest="cmd", required=False)

    # 默认子命令（无 cmd 时进入）：save —— 与既有调用方完全兼容
    save_p = sub.add_parser("save", help="写入 review JSON + 更新 meta.yaml.reviews")
    save_p.add_argument("--req", required=True)
    save_p.add_argument("--phase", required=True)
    save_p.add_argument("--reviewer", required=True)
    save_p.add_argument("--scope")  # 现有参数全部保留

    # 新增子命令：signoff
    signoff_p = sub.add_parser("signoff", help="写 human_signoff 字段（卡点 B 调用）")
    signoff_p.add_argument("--rev-id", required=True)
    signoff_p.add_argument("--decision", required=True,
                           choices=["approved", "approved-trivial", "rejected"])
    signoff_p.add_argument("--signed-by", required=True)
    signoff_p.add_argument("--signed-at", required=True)
    # 注：--source 当前枚举仅 cli-tty 一个值，仍设为 CLI 参数
    # 是为预留 D-004 未来扩展（PR Review 等价 sign-off）时无需改 CLI 形态
    signoff_p.add_argument("--source", default="cli-tty",
                           choices=["cli-tty"])

    args = parser.parse_args()
    if args.cmd is None or args.cmd == "save":
        return _run_save(args)        # 既有逻辑迁入
    if args.cmd == "signoff":
        return _run_signoff(args)     # F-004 新增
    return 2

# 既有 save-review.sh 调用 'python3 save_review.py --req X --phase Y --reviewer Z'
# 在升级后等价于 'python3 save_review.py save --req X --phase Y --reviewer Z'
# 通过 args.cmd is None 路径走 _run_save，无需改 save-review.sh
```

**save-review.sh 是否要改**：默认**不改**——argparse 在 cmd 缺省时走 save 路径，与历史 CLI 完全兼容。仅当 F-004 实施时如果 save-review.sh 也要新增 signoff 子命令对外暴露，才追加 `bash scripts/save-review.sh signoff ...` 一段；本期不做（卡点 B 直接调 python 入口）。

### F-004.4 check_reviews.is_signed_off helper

```python
# scripts/lib/check_reviews.py（增量）

SIGNOFF_PASS: set[str] = {"approved", "approved-trivial"}

def is_signed_off(verdict: dict) -> bool:
    """REQ-2026-003 双卡点 sign-off 判定，feature-lifecycle-manager 与
    GATE-REVIEW-VERDICT 必须共用此 helper 避免双轨。

    True 当且仅当 verdict.human_signoff.decision ∈ {approved, approved-trivial}。
    缺字段 / decision 为 rejected / 空字符串 → False。
    """
    sig = verdict.get("human_signoff") or {}
    return sig.get("decision") in SIGNOFF_PASS
```

**R003 / R007 升级**（来源：scripts/lib/check_reviews.py:73）：

```diff
- if verdict.get("conclusion") == "rejected":
-     return Violation("R003", f"verdict {rev_id} rejected")
+ if verdict.get("conclusion") == "blocked":
+     return Violation("R003", f"verdict {rev_id} conclusion=blocked")
+ if not is_signed_off(verdict):
+     return Violation("R003", f"verdict {rev_id} missing human_signoff or rejected")
```

**强约束**（与 outline §4.4 一致）：

- ❌ 禁止在 `feature-lifecycle-manager` SKILL.md 用字符串 `grep approved` / `decision == "approved"` 自行判断
- ❌ 禁止用 `python3 -c "..."` 一行式（reviewer 指出 zsh / bash 引号嵌套与 sys.path 拼接易踩坑）
- ✅ 所有调用方走独立 wrapper 脚本 `scripts/check-signoff.sh`：

```bash
# scripts/check-signoff.sh
#!/usr/bin/env bash
# 单一职责：读 verdict 文件，按 is_signed_off 返回 0（已签）/ 1（未签）
# 任何下游判定（feature-lifecycle-manager / GATE-REVIEW-VERDICT）必须走此脚本，
# 严禁 grep / awk / jq 自行解析 human_signoff.decision。
set -e
VERDICT="${1:?usage: check-signoff.sh <path-to-verdict.json>}"
exec python3 -c '
import json, sys
sys.path.insert(0, "scripts/lib")
from check_reviews import is_signed_off
sys.exit(0 if is_signed_off(json.load(open(sys.argv[1]))) else 1)
' "$VERDICT"
```

**为什么 wrapper 而不是一行式**：
1. bash/zsh 单引号嵌套差异：双引号包 `python3 -c` 时 `from check_reviews import is_signed_off` 中的 import 在某些 shell 下被局部还原；wrapper 用单引号 heredoc 形式杜绝
2. SKILL.md 里直接复制粘贴的命令最稳定形态是 `bash scripts/check-signoff.sh <path>`——零思考、零引号
3. 同一段 Python 仍只有一份（在 wrapper 内 inline），与 outline §4.4「不允许双轨」原则一致

### F-004.5 feature-lifecycle-manager done 判定升级

`.claude/skills/feature-lifecycle-manager/SKILL.md:51` 现行（来源：.claude/skills/feature-lifecycle-manager/SKILL.md:51）：

```
- approved → 更新 task 文件 status 到 done...
```

**替换为**：

```
- 调用 wrapper 脚本判定 sign-off 状态（不允许自行 grep / 一行式）：
    bash scripts/check-signoff.sh requirements/<id>/reviews/<rev-id>.json
- 退出码 0 → human_signoff.decision ∈ {approved, approved-trivial} → 转 done
- 退出码 1 → 未签字 / decision=rejected / 缺字段 → 保持 in-progress，提示开发者执行 /code-review:signoff
```

### F-004.6 旧 verdict cutover 清单（M11 闭合 architectural_concern）

specs/2026-04-30-code-review-human-checkpoints.md 必须含本节，提供升级当日的处置清单。

> **路径日期口径**：本路径以 detail-design 阶段产出日 `2026-04-30` 为准（spec 文档由本阶段定稿）；outline-design.md §M13 列的 `2026-04-29` 是 outline 起草日的占位，detail-design 阶段统一为 04-30。F-004 实施时按本路径创建文件即可；outline 不必为此一处再走 stale 重审。

**Cutover 操作步骤**：

1. **预检**：跑 `python3 scripts/lib/migrate_review_v2.py --dry-run`，得到全仓未签 verdict 列表
2. **分类**：
   - `phase ∈ {definition, tech-research, outline-design, detail-design}` 且对应需求处于 development+ 阶段：建议**重签**（不必重审），减小 development 阻断
   - `phase = code` 且对应需求处于 testing 阶段：必须**重审**，由 reviewer 重新评估三档
   - 已 completed/abandoned 的需求：**不处理**（保持历史）
3. **执行**：
   - 重签：开发者本人对每个 verdict 跑 `/code-review:signoff <REV-ID>` 或 `--trivial`
   - 重审：跑 `/code-review`（嵌入模式），生成新 verdict 后再签
4. **验收**：
   - `python3 scripts/gates/run.py --trigger=ci` 跑完 0 错误
   - 所有进行中需求的 `meta.yaml.reviews.<phase>.stale` 全为 false

**不强制全仓重签**——已 completed/abandoned 需求保留旧字段，不入新判定流程。

> **GATE 触发面与 cutover 范围的张力消解**：GATE-REVIEW-VERDICT 在 phase-transition / submit / pre-commit / ci 时触发。本 cutover 范围**仅含进行中需求**（has un-done feature 或 phase ≠ completed/abandoned），其旧 verdict 在升级后第一次切阶段就会被阻断——这是有意的：阻断本身就是 cutover 信号，开发者按上述 4 步分类处理即可放行。已 completed/abandoned 需求不会再触发 phase-transition / submit，旧 verdict 自然不入判定路径，无需迁移。
>
> 如果某个进行中需求短期不打算切阶段（如挂起的 stash 分支），其旧 verdict 不需立刻处理；下次 resume 时按本清单走即可。

### F-004.7 异常退出码完整矩阵

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

退出码 2（tty 校验失败）与退出码 1（schema/参数失败）刻意区分，便于 CI 测试断言（来源：requirements/REQ-2026-003/artifacts/requirement.md:69）。

### F-004.8 ai-collaboration.md 硬规则增量

追加在「规则二：渐进式输出」之后：

```markdown
### 规则三：sign-off 是人类专属动作

Agent 在主对话或子 Agent 中，**禁止**调用以下命令或 CLI：
- `/code-review:signoff <REV-ID>`
- `bash scripts/save-review.sh signoff ...`
- `python3 scripts/lib/save_review.py signoff ...`

调用前的 tty 校验（`[ -t 0 ]`）会拒绝 AI shell，但 AI 不得通过假 tty / pipe trick / heredoc 等方式绕过。
违反视为流程违规——人类发现即回滚 verdict 字段并在需求 notes.md 记录。
```

### F-004.9 测试要点

| Case | 输入 | 期望 |
|---|---|---|
| TC-B1 | tty + 普通 sign-off | verdict.human_signoff 全字段填充，CR 校验通过，退出 0 |
| TC-B2 | 非 tty 调 signoff Command | 退出 2，stderr 含 `stdin not a tty` |
| TC-B3 | 非 tty 直调 Skill（绕过 Command） | 退出 2（深防御命中） |
| TC-B4 | --trivial + 全 .md diff | decision=approved-trivial，退出 0 |
| TC-B5 | --trivial + 含 .py diff | 退出 3，stderr `non-doc files detected` |
| TC-B6 | sign-off 已签 verdict | 退出 5 |
| TC-B7 | sign-off 不存在 REV-ID | 退出 4 |
| TC-B8 | is_signed_off(approved) | True |
| TC-B9 | is_signed_off(approved-trivial) | True |
| TC-B10 | is_signed_off(rejected) | False |
| TC-B11 | is_signed_off({}) | False |
| TC-B12 | feature-lifecycle-manager 转 done + 未签 verdict | 阻断，提示 signoff |
| TC-B13 | GATE-REVIEW-VERDICT + 旧 verdict 无 human_signoff | 阻断（cutover 清单要求） |
| TC-B14 | AI 在子 Agent shell（fake tty）调 signoff | 退出 2（手工冒烟） |

---

## 5. 数据契约示例

> **时间格式注释**：示例中 `reviewed_at` 沿用既有 review-schema.yaml 的 datetime 格式 `YYYY-MM-DD HH:MM:SS`（无时区），`signed_at` 用 ISO 8601 含时区偏移。这是**有意的**——前者是 verdict 落盘时的本地时间戳（既有 reviewer 已用此格式），后者是 sign-off 操作的时间戳（可能跨时区，回溯审计需要时区信息）。F-001.2 schema 中 `human_signoff.signed_at` 的 `format: iso8601` 明确这一不同源；实施者**禁止**为"美观一致"把两者统一成同一格式。

### 5.1 升级后 verdict 文件示例

```json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2026-099-code-001",
  "requirement_id": "REQ-2026-099",
  "phase": "code",
  "reviewer": "code-quality-reviewer",
  "reviewed_at": "2026-04-30 14:00:00",
  "reviewed_commit": "abc1234",
  "reviewed_artifacts": [
    {"path": "src/foo.py", "sha256": "..."}
  ],
  "conclusion": "looks_clean",
  "score": 88,
  "dimensions": { "...": "..." },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null,
  "human_signoff": {
    "decision": "approved",
    "signed_at": "2026-04-30T14:30:00+0800",
    "signed_by": "huangjian@example.com",
    "source": "cli-tty"
  }
}
```

### 5.2 trivial 通道 verdict 示例

```jsonc
{
  "// ...": "其余字段同上",
  "conclusion": "looks_clean",
  "human_signoff": {
    "decision": "approved-trivial",
    "signed_at": "2026-04-30T14:30:00+0800",
    "signed_by": "huangjian@example.com",
    "source": "cli-tty"
  }
}
```

`approved-trivial` 与 `approved` 在 is_signed_off 判定下等价（都进入 SIGNOFF_PASS），但下游审计可单独统计（spec 文档 §统计指标段落）。

---

## 6. 与 outline / requirement 的引用一致性矩阵

| outline §X | requirement §Y | 详细设计落点 |
|---|---|---|
| §3.1.1 卡点 A | 场景 1 步骤 1-4 | F-002.3 时序 + F-002.4 删除点 |
| §3.1.2 卡点 B | 场景 1 步骤 7-8 | F-004.2 + F-004.3 |
| §3.2 三层防御 | 场景 3 | F-004.2 预检 + F-004.3 二次校验 + F-001.3 CR-8 |
| §3.3 兼容性策略 | 范围/不包含 + 非功能 | F-004.6 cutover 清单 + F-001.4 干跑脚本 |
| §4.1 scope-schema | 范围/包含 第 1 条 | F-002.2 |
| §4.2 review-schema | 范围/包含 第 6 条 | F-001.2 |
| §4.3 CR 规则 | 范围/包含 第 7 条 | F-001.3 |
| §4.4 is_signed_off | D-008 修订口径 | F-004.4 + F-004.5 |
| §4.5 signoff CLI | 场景 1 步骤 7 | F-004.2 |
| §2.1 删除点 | D-007 范围扩展 | F-002.4 |

---

## 7. 风险闭合（对接 outline §7）

| outline 风险 | 详细设计闭合 |
|---|---|
| R-O1 conclusion 重命名破坏旧 verdict | F-001.4 干跑脚本 + F-004.6 cutover 清单 |
| R-O2 helper 调用方式未定 | F-004.4 落实为独立 wrapper 脚本 `scripts/check-signoff.sh`（不再候选一行式）—— 选 **wrapper**：避免 `python3 -c` 在 zsh/bash 引号嵌套与 sys.path 拼接踩坑；调用方零思考；同一段 Python 仅一份 inline 在 wrapper 内，与 outline §4.4「不允许双轨」一致 |
| R-O3 假 tty 绕过 | F-004.3 二次校验 + F-004.8 ai-collaboration 硬规则；ppid 链检测**不做**（成本高于收益，由硬规则兜底） |
| R-O4 仪式偏重 | F-002.3 --all + F-004.3 --trivial 双兜底已足够 |
| R-O5 signoff 子命令归属 | F-004.3 落在 save_review.py（同进程复用 schema 校验链）；save-review.sh 不加 signoff 子命令 |

---

## 8. features.json 工作量与依赖图

```
F-001 (3.5d) ─┬─→ F-003 (3d)
              │
F-002 (4d)  ──┼─→ F-004 (5.5d)
              │
              └─→ F-004 (depends on F-001)
```

总计 **16 人天**（与 tech-feasibility.md approved 估算一致）。

F-001 / F-002 可并行（无依赖）；F-003 等 F-001（schema 升级先）；F-004 等 F-001 + F-002 + F-003（依赖最重，需所有上游契约就绪）。

---

## 9. 验收门槛（对接 outline §8）

| 维度 | 验收方式 |
|---|---|
| 端到端 | 在 sandbox REQ-2099-NNN 跑通：prepare→checker→judge→signoff→feature 转 done；中途任一步骤断流即不通过 |
| 退出码 | TC-A1~A7 + TC-B1~B14 全过 |
| schema 校验 | F-001.5 fixture 全过 + 全仓 `python3 scripts/gates/run.py --trigger=ci --strict` 0 错误 |
| AI 代签 | TC-B14 手工冒烟：在子 Agent shell 调 signoff Command + 直调 Skill + 直调 save_review.py，三处全部退出 2 |
| 双轨一致性 | feature-lifecycle-manager 与 GATE-REVIEW-VERDICT 对同一 verdict 文件给出相同放行/拒绝结论（is_signed_off 共用 helper 即天然保证；附手工对比脚本一份） |

---

## 待澄清清单

- F-002.4 删除 `code-review.md:40` 后，仓库内可能仍存在文档/测试硬依赖（如 specs 旧版本、CI fixture）。计划：F-002 实施时先全仓 `git grep -E '零 finding|全空 issues|empty findings'` 复核。命中即在该 feature 内同步清理。[待用户确认]——是否接受"F-002 实施时复核"这一推迟节奏，还是希望详细设计阶段就预扫一遍？
