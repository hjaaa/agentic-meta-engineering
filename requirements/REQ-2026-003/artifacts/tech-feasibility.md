---
id: REQ-2026-003
title: 代码审查人类必经卡点 · 技术可行性评估
created_at: "2026-04-29 21:30:00"
refs-tech-feasibility: true
---

# REQ-2026-003 · 技术可行性评估

## 总结

可行性：**high**。所有改动均落在项目已有技术栈（Python + Bash + Markdown Skill/Command 文件）内，无需引入新依赖。最大复杂度集中在两处：`save_review.py` 新增 `signoff` 子命令（tty 校验 + 字段写入）、以及下游三处门禁从"看 `conclusion`"改为"看 `human_signoff.decision`"。这两处均有清晰的改动边界，无 blocker 级阻碍。无平台级已知 bug 依赖（对比 REQ-2026-001 的 3 个平台级 bug，来源：requirements/REQ-2026-001/artifacts/tech-feasibility.md:11）。

总工作量估算：**16 人天**（单人串行），设计 3 天 / 开发 6.5 天 / 测试 6.5 天。

---

## 1. 关键技术选型

### 1.1 `code-review-prepare` 双阶段化（建议 → 等确认 → 写盘）

**现状**：`code-review-prepare` SKILL.md 当前第 4 步直接写 `.review-scope.json`（来源：.claude/skills/code-review-prepare/SKILL.md:24），第 5 步输出摘要"确认继续后触发并行审查"——但这个"确认"只是提示文字，没有写盘控制点。

**方案**：在 SKILL.md 中把流程拆为：
1. 扫描 diff、生成路由建议（含 `skipped_checkers` + 跳过理由）
2. 输出建议摘要给主对话，**停止，等人类回应**
3. 收到回应（`continue / all / custom`）后写 `.review-scope.json`（含 `routing_confirmed_by` 字段）

**可行性关键点**：Claude Code Skill 的停顿机制依赖主对话的交互式 prompt——Skill 本质是给 Agent 的指令文档，Agent 遇到"等用户回应"的指令会自然在主对话停顿。无平台 API 调用，无额外依赖。这是 Skill prompt 设计问题，而非代码问题。

**额外漏洞**：`code-review.md:40` 的"零 finding 快速路径"直出 `approved` 报告，绕过 `code-quality-reviewer`，需要同步删除或改写（来源：.claude/commands/code-review.md:40）。

**结论**：pure-Markdown 改动，零新增依赖，可行。scope-schema.md 新增 3 个字段（`selected_checkers / skipped_checkers / routing_confirmed_by`），已在来源文件中有明确定义（来源：requirements/REQ-2026-003/artifacts/requirement.md:85）。

### 1.2 `save-review.sh signoff` 子命令 + tty 校验

**现状**：`save-review.sh` 是薄壳（来源：scripts/save-review.sh:19），`exec python3 scripts/lib/save_review.py "$@"`。`save_review.py` 的 `main()` 只有一条写入路径（来源：scripts/lib/save_review.py:178），无子命令分支。

**方案**：在 `save_review.py` 新增 `signoff` 子命令（前置 `sys.argv[1] == "signoff"` 分支，避免 argparse subparsers 改 CLI 结构）。`signoff` 路径：
1. tty 校验：`os.isatty(sys.stdin.fileno())`（等价 `[ -t 0 ]`）；非 tty → `sys.exit(2)` + stderr `signoff: refusing in non-interactive shell (stdin not a tty)`
2. `--trivial` 路径：读取 `git diff --name-only` 文件列表，全部命中白名单（`*.md / docs/** / *.txt`）则放行，否则 `sys.exit(3)` + stderr `trivial: non-doc files detected`
3. 读取现有 verdict JSON，写入 `human_signoff: {by, at, decision}` 字段，原子写回

**跨平台 tty 校验**：`os.isatty(sys.stdin.fileno())` 是 Python 标准库，macOS / Linux 均可用。GitHub Actions CI 默认 stdin 非 tty，返回 `False`（符合阻断预期）。无需 `ps -p $PPID` 进程链识别（REQ-2026-002 的 H5 场景，来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:43），本需求场景简单——非交互环境直接拒签即可。

**`by` 字段取值**：`git config user.email`，失败时取 `git config user.name`，两者都无则 `unknown`。

**结论**：改动量约 +80 行 Python，完全在已有 `save_review.py` 体系内，零新增依赖，可行。

### 1.3 schema 升级与旧 verdict 迁移

**review-schema.yaml 改动**（来源：context/team/engineering-spec/review-schema.yaml）：
- `conclusion` 枚举从 `[approved, needs_revision, rejected]` 改为 `[looks_clean, needs_attention, blocked]`
- 新增顶层字段 `human_signoff`（非必填，null 表示未签字）：`{by: string, at: ISO8601, decision: approved | approved-trivial | rejected}`
- CR-1/CR-2/CR-3/CR-4/CR-6 规则涉及 `conclusion == "approved"` 的判定需同步更新（改为 `looks_clean` / `blocked` 对应逻辑）

**旧 verdict 迁移策略**：旧 verdict（无 `human_signoff` 字段）视为"未签字"。`check_reviews.py` 的 `_r003_not_rejected` 当前检查 `conclusion == "rejected"`（来源：scripts/lib/check_reviews.py:65），升级后需改为检查 `human_signoff is null` → 强制要求重新 sign-off（D-002 决策：旧签字不可继承，来源：requirements/REQ-2026-003/plan.md:62）。

**`code-quality-reviewer.md` 同步收敛**：当前结论规则含 `approved`（来源：.claude/agents/code-quality-reviewer.md:200），需改为 `looks_clean / needs_attention / blocked` 三档（来源：requirements/REQ-2026-003/artifacts/requirement.md:86）。

**结论**：改动点明确，但联动文件多（schema + agent + check_reviews + save_review），需严格按 PR 分批落地，可行。

### 1.4 GATE-REVIEW-VERDICT 升级

**现状**：`review_verdict.py` 的 `_run_single_requirement` 通过 `check_reviews` 的 R001~R007 规则判定（来源：scripts/gates/plugins/review_verdict.py:98）。R003 检查 `conclusion != "rejected"`（来源：scripts/lib/check_reviews.py:65），门禁不看 `human_signoff`。

**方案**：在 `run_r_rules` 中新增 R008 规则：检查 `meta.reviews.code.by_feature.<feature_id>.human_signoff.decision ∈ {approved, approved-trivial}`；缺失或不在集合内 → ERROR。R003 同步改为检查新 `conclusion` 枚举（`blocked` 对应 rejected 语义）。`registry.yaml:136` 的 `GATE-REVIEW-VERDICT` 注释需更新，plugin 逻辑改动但注册不变。

**`_run_single_requirement` 影响面**：`check_reviews.py` 是 `scripts/lib/` 下的共享库，改动影响 CLI 路径（`check_reviews.py main`）和 gate plugin 路径（通过 `run_r_rules`），需双路径测试。

**结论**：改动量约 +30 行，可行。

### 1.5 trivial 通道路径白名单实现

**方案**：在 `save_review.py signoff --trivial` 路径中，调用 `git diff --name-only <base>..HEAD`（base 从 `.review-scope.json` 读取）获取变更文件列表，逐行匹配白名单：
- `*.md`：`pathlib.Path(p).suffix == ".md"`
- `docs/**`：`str(p).startswith("docs/")`
- `*.txt`：`pathlib.Path(p).suffix == ".txt"`

全部命中 → `human_signoff.decision = "approved-trivial"`；任一不命中 → `sys.exit(3)` + stderr `trivial: non-doc files detected`。

**白名单实现复杂度**：三条规则，约 10 行 Python，无 glob 库依赖（pathlib 标准库）。

**结论**：实现简单，可行。

### 1.6 feature-lifecycle-manager / requirement:submit 三处门禁升级

**feature-lifecycle-manager**：当前转 done 逻辑看 `conclusion`（来源：requirements/REQ-2026-003/artifacts/requirement.md:16），改为查 `human_signoff.decision ∈ {approved, approved-trivial}`。改动位于 `.claude/skills/feature-lifecycle-manager/SKILL.md`（已确认存在，假设记录 1 闭合）。

**requirement:submit**：`submit-rules.md` 的预检条件当前看"artifacts/review-*.md 至少一份报告且无 severity: blocker"（来源：.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md），升级后额外要求 verdict 中 `human_signoff.decision ∈ {approved, approved-trivial}`。改动在 `submit-rules.md` 和 `gate-checklist.md`（渲染产物需同步更新）。

**GATE-REVIEW-VERDICT**：见 1.4 节。

**结论**：三处同逻辑改动（查 `human_signoff.decision` 而非 `conclusion`），联动但可行。

---

## 2. 风险识别

| # | 类别 | 描述 | 可能性 | 影响 | 缓解策略 |
|---|---|---|---|---|---|
| R-1 | tech | `conclusion` 枚举改名波及所有历史 verdict 文件：所有已落盘的 review JSON 含旧枚举值，`check_reviews.py _r002_schema_recheck` 会批量失败（来源：scripts/lib/check_reviews.py:82） | high | high | **迁移脚本细化方案**：(1) 新建 `scripts/lib/migrate_verdict_v2.py`，扫描对象 = `requirements/*/reviews/*.json` + `requirements/*/meta.yaml.reviews.*.conclusion`；(2) 替换映射 `approved→looks_clean / needs_revision→needs_attention / rejected→blocked`，python json.load + json.dump 保字段顺序；(3) 加 dry-run 标志，输出受影响文件清单；(4) 与 M-001 PR 同 commit 提交并执行；(5) 回滚方式 = `git revert M-001 commit` 自动恢复（脚本只处理本仓库 tracked 文件）；(6) CI 验证点 = M-001 commit 前后跑 `python3 scripts/lib/check_reviews.py --target-phase outline-design --req REQ-2026-002` 期望从 fail（旧枚举）转为 pass（新枚举） |
| R-2 | tech | `save_review.py signoff` 子命令与现有 argparse 结构冲突：当前 `main()` 直接 `parser.add_argument` 没有子命令层（来源：scripts/lib/save_review.py:202）；引入 subparsers 会改变 CLI 接口 | medium | medium | 采用前置 `sys.argv[1] == "signoff"` 判断分支（非 argparse subparsers）：signoff 路径独立解析，原路径保持不变；调用方无感知；detail-design 阶段锁定接口 |
| R-3 | tech | `code-review.md` 零 finding 快速路径漏洞：当前"8 checker 全部空 issues → 直接输出 `approved` 报告"（来源：.claude/commands/code-review.md:40）绕过了 `code-quality-reviewer` 和 `human_signoff`，本需求若只改 `code-quality-reviewer` Agent 定义而忘改 `code-review.md`，此路径仍可让 AI 直出 approved | high | high | 已闭合：本评审发现该漏洞后，requirement.md 范围/包含 段新增"删除该零 finding 快速路径"产出物（来源：requirements/REQ-2026-003/artifacts/requirement.md），plan.md D-007 记录范围扩展决策（来源：requirements/REQ-2026-003/plan.md:103）；M-001 PR 第一批改动即包含此文件 |
| R-4 | business | 旧 verdict 强制重签 ceremony 代价高：升级后所有含旧 verdict 的 feature 若未经 sign-off 都会被门禁拦截，开发者体验短期变差；若历史 verdict 数量多，迁移期可能卡住所有正在进行的需求 | medium | medium | 迁移窗口策略：先在 staging 分支跑 R008 新规则，统计受影响 verdict 数量；提供一键 sign-off 脚本（读取旧 verdict → 补写 human_signoff）供迁移期使用；超过 10 个旧 verdict 时需评估是否设置迁移豁免期 |
| R-5 | security | tty 伪造风险：`os.isatty()` 校验可被开发者给 AI shell 装 PTY（`pty.openpty()`）绕过（来源：requirements/REQ-2026-003/plan.md:37）；plan.md 的 R3 风险段早已识别此点；tty 校验不是绝对防伪 | low | medium | 配合 `ai-collaboration.md` 硬规则（来源：context/team/ai-collaboration.md:17）：禁止主动给 AI 装 PTY；此为社会工程防线而非技术防线，对单人项目已足够；未来团队化可加 audit log 比对 |
| R-6 | tech | `check_reviews.py` CR 规则与新 `conclusion` 枚举不一致：CR-1/CR-2/CR-3/CR-4/CR-6 横跨多行均基于 `conclusion == "approved"` 判定——CR-1 见 scripts/lib/save_review.py:88、CR-2 见 :92、CR-3 见 :96、CR-4 见 :103、CR-6 见 :120；枚举改名后若 CR 规则不同步改，所有新 verdict 的内部一致性校验会失效或误报 | medium | high | CR 规则改动与枚举改动必须同 PR 同步落地；detail-design 阶段列出每条 CR 规则的新语义（`approved→looks_clean, rejected→blocked`），PR review 时逐条比对 |
| R-7 | ops | `human_signoff` 字段写入后 R005 hash drift 风险：`signoff` 路径向 verdict JSON 文件写入新字段，若 verdict 文件本身在 `reviewed_artifacts` 中会触发 R005（来源：scripts/lib/check_reviews.py:129）；但 PR #47 已加黑名单兜底（`reviews/` 子路径被禁，来源：scripts/lib/save_review.py:178），此风险已被结构性解决 | low | low | 已闭合；detail-design 阶段确认 `signoff` 写入目标是 `reviews/*.json`，测试阶段只需验证 R005 不误报 |

---

## 3. 工作量估算

**估算依据**：
- 改动集中在 Markdown（Skill / Command / Agent 定义）和 Python（`save_review.py` / `check_reviews.py` / gate plugin）两类
- 历史参考：REQ-2026-002 check adapter 化每个约 0.5 天 dev（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:117）；类似 Markdown 改动约 0.3-0.5 天/文件
- `save_review.py` 当前 350 行（含 PR #47 黑名单），新增 signoff 子命令约 +80 行
- `check_reviews.py` 当前 270 行，新增 R008 约 +30 行；CR 规则更新约 +10 行

### M-001：schema + Agent + Skill / Command Markdown 层改动

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| review-schema.yaml conclusion 枚举改名 + human_signoff 字段定义 | 0.5 | 0.5 | 0.5 | 1.5 |
| code-quality-reviewer.md 结论规则收敛为三档（删 approved） | 0.5 | 0.5 | 0.5 | 1.5 |
| code-review.md 删零 finding 快速路径的 approved 直出 + 新增 signoff 提示步骤 | 0 | 0.5 | 0.5 | 1 |
| code-review-prepare SKILL.md 双阶段化 + scope-schema.md 新增 3 字段 | 0.5 | 0.5 | 0.5 | 1.5 |
| 新建 .claude/commands/code-review/signoff.md | 0.5 | 0.5 | 0.5 | 1.5 |
| **M-001 小计** | **2** | **2.5** | **2.5** | **7** |

### M-002：save_review.py signoff 子命令实现

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| signoff 路径：tty 校验 + by/at 字段获取 + verdict 读写 | 0.5 | 1 | 0.5 | 2 |
| --trivial 路径：白名单匹配 + 退出码 3 + decision=approved-trivial | 0 | 0.5 | 0.5 | 1 |
| 旧 verdict 迁移脚本（批量补写 conclusion 枚举值） | 0 | 0.5 | 0.5 | 1 |
| **M-002 小计** | **0.5** | **2** | **1.5** | **4** |

### M-003：check_reviews + gate 判定逻辑升级

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| check_reviews.py 新增 R008（human_signoff 存在性 + decision 集合校验） | 0.5 | 0.5 | 0.5 | 1.5 |
| CR-1~CR-6 规则同步新枚举（approved→looks_clean 等） | 0 | 0.5 | 0.5 | 1 |
| feature-lifecycle-manager + submit-rules.md 三处门禁升级 | 0 | 0.5 | 0.5 | 1 |
| **M-003 小计** | **0.5** | **1.5** | **1.5** | **3.5** |

### M-004：留档 + 端到端验收测试

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| context/team/engineering-spec/specs/2026-04-29-code-review-human-checkpoints.md 新建 | 0 | 0.5 | 0 | 0.5 |
| 端到端场景 1/1b/2/3 手工验证（tty 校验 / trivial 通道 / 非交互拒签） | 0 | 0 | 1 | 1 |
| **M-004 小计** | **0** | **0.5** | **1** | **1.5** |

### 汇总

| PR | design | dev | test | PR 合计 |
|---|---|---|---|---|
| M-001 | 2 | 2.5 | 2.5 | 7 |
| M-002 | 0.5 | 2 | 1.5 | 4 |
| M-003 | 0.5 | 1.5 | 1.5 | 3.5 |
| M-004 | 0 | 0.5 | 1 | 1.5 |
| **总计** | **3** | **6.5** | **6.5** | **16** |

### PR 拓扑依赖图

```
M-001 (schema + Agent + Skill)
   │
   │ 必须先：review-schema.yaml 的 conclusion 枚举改名 + human_signoff 字段定义
   │ 是后续所有 PR 的契约前提
   ▼
   ├─→ M-002 (save_review.py signoff 子命令)
   │      ├─ 弱依赖 M-001：写 human_signoff 字段需要 schema 已定义
   │      └─ 与 M-003 共享 save_review.py 文件（CR 规则改动），需 rebase 协调
   │
   └─→ M-003 (check_reviews + gate 升级)
          ├─ 强依赖 M-001：R008 校验 + CR 规则更新都基于新枚举
          └─ 与 M-002 弱并行（共享 save_review.py 和 check_reviews.py，需 rebase）
   
M-004 (留档 + 端到端验收)
   └─ 必须最后：依赖 M-001~M-003 全部合入后做端到端测试
```

**串行 / 并行关系**：
- M-001 → (M-002 与 M-003 弱并行) → M-004
- M-002 与 M-003 弱并行：可同时开发但合入需顺序（共享文件 rebase）
- 推荐串行节奏：M-001 → M-002 → M-003 → M-004，因为 M-002 与 M-003 共享文件，并行 rebase 成本未必低于串行

---

## 4. 前置条件

1. **review-schema.yaml 枚举改名必须先于所有其他改动落地**：下游 `check_reviews.py` / `save_review.py` / `code-quality-reviewer.md` 的新逻辑都依赖新枚举定义（来源：context/team/engineering-spec/review-schema.yaml）；若顺序反，CI 会因旧枚举校验失败阻断开发流程
2. **历史 verdict 文件迁移脚本须在 M-002 PR 合入前就绪**：`check_reviews.py _r002_schema_recheck` 会对所有已落盘 verdict 做枚举校验（来源：scripts/lib/check_reviews.py:82），PR 合入后旧 verdict 立即不合规；迁移脚本须在同批次 PR 中提供并执行
3. **`feature-lifecycle-manager` 所在文件已确认**：`.claude/skills/feature-lifecycle-manager/SKILL.md`（Skill 而非 Agent），改动量在 §1.6 + M-003 工作量估算中已涵盖，无前置阻塞
4. **Python 3.9+（`os.isatty` / `pathlib`）**：CI 固定 Python 3.11（来源：.github/workflows/quality-check.yml:22），本地开发环境需同版本

---

## 5. 假设记录

## 待澄清清单

_假设 1（feature-lifecycle-manager 路径）已闭合 · 2026-04-29：实际位于 `.claude/skills/feature-lifecycle-manager/SKILL.md`，是 Skill 而非 Agent；改动量在 §1.6 + §3 M-003 已包含，无工作量上调。_

[待补充]
- 内容：`.review-scope.json` 在 `signoff --trivial` 路径的可用性
- 依据：trivial 通道的白名单匹配需要变更文件列表，方案一是读 `.review-scope.json`（含 `diff_summary`），方案二是重新调用 `git diff --name-only`；若 `.review-scope.json` 不存在（独立模式且未跑 prepare），则需要 fallback 策略
- 风险：独立模式下用户直接执行 `signoff --trivial` 跳过 prepare，白名单无法读取 diff；可能需要强制要求 `.review-scope.json` 存在，否则降级到 fallback
- 验证时机：detail-design 阶段设计 signoff 命令的前置检查规则

---

## 6. 参考

- requirements/REQ-2026-003/artifacts/requirement.md — 主需求文档（范围 / 决策 / 用户场景）
- requirements/REQ-2026-003/plan.md — D-001~D-006 决策记录
- scripts/lib/save_review.py — 现有 review 写入 Python 实现（:178 黑名单 / :202 main 入口）
- scripts/lib/check_reviews.py — 现有门禁校验 Python 实现（:65 _r003_not_rejected / :129 _r005_hash_drift）
- scripts/gates/plugins/review_verdict.py — GATE-REVIEW-VERDICT plugin（:98 _run_single_requirement）
- scripts/gates/registry.yaml:136 — GATE-REVIEW-VERDICT 注册
- context/team/engineering-spec/review-schema.yaml — verdict JSON schema 唯一事实源
- .claude/skills/code-review-prepare/SKILL.md — 现有 prepare 流程（:24 写盘步骤）
- .claude/skills/code-review-prepare/reference/scope-schema.md — ReviewScope JSON schema
- .claude/commands/code-review.md — /code-review 编排逻辑（:40 零 finding 快速路径漏洞）
- .claude/agents/code-quality-reviewer.md:200 — 现有结论规则（含 approved，需收敛）
- .claude/skills/managing-requirement-lifecycle/reference/submit-rules.md — submit 预检条件
- requirements/REQ-2026-001/artifacts/tech-feasibility.md — 历史格式参考（:11 可行性判断基准）
- requirements/REQ-2026-002/artifacts/tech-feasibility.md — 历史格式参考（:43 tty 校验跨平台分析 / :117 工作量估算基准）
