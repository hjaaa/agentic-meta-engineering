# Reviewer Verdict 结构化 · 设计记录

**日期**：2026-04-27
**作者**：huangjian
**状态**：设计中（pending 实施，落地后归档至 `roadmap.md` G3 标记 done）
**关联文档**：
- `context/team/engineering-spec/roadmap.md` 第"门禁体系缺陷与演进"段（G3）
- `context/team/engineering-spec/specs/2026-04-22-index-meta-validation-design.md`（meta.yaml schema 扩展先例 + check 脚本风格）
- `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md`（待改造的纯文本门禁清单）
- `.claude/agents/{requirement,outline-design,detail-design,code}-quality-reviewer.md`（4 个 reviewer 输出契约待改）
- `context/team/engineering-spec/meta-schema.yaml`（待新增 `reviews` 字段）

---

## 1. 背景与问题

### 1.1 当前 4 个 reviewer Agent 的输出形态

| Agent | verdict 字段 | 输出格式 | 落点 |
|---|---|---|---|
| `requirement-quality-reviewer` | `conclusion ∈ {approved, needs_revision, rejected}` | JSON | **仅主对话**（未持久化） |
| `outline-design-quality-reviewer` | 同上 | JSON | 仅主对话 |
| `detail-design-quality-reviewer` | 同上 | JSON | 仅主对话 |
| `code-quality-reviewer` | 同上（含 merged_issues / adjudication） | JSON | 仅主对话 |

### 1.2 4 类失败模式

代号沿用 brainstorming 时和用户对齐的命名：

- **A**：Reviewer 给出了 verdict，**主对话 LLM 在切阶段时没认真读**，凭印象判过
- **B**：Reviewer Agent **根本没被调用**，主对话直接 `/requirement:next`
- **C**：Reviewer **自身判断不严**，看几眼就 approved
- **D**：Review 给了 approved，但**之后 artifact 被改了**，verdict 已失效

### 1.3 当前体系为什么拦不住

- `gate-checklist.md` 是**纯文本清单**，"verdict ≠ rejected" 这条靠主对话 LLM 自觉读 → 拦不住 A
- 没有"必须有近期 review 文件"的硬校验 → 拦不住 B
- 4 个 reviewer 自评自审，无对抗（仅 `/code-review` 有 review-critic）→ 拦不住 C
- 评审完就只在主对话飘着，没有锚定 commit / artifact hash → 拦不住 D

### 1.4 为什么现在做

- A/B/D 的根因都是"verdict 不是机器可读结构"，一次结构化改造能同时堵住
- C 的根因不同（reviewer 自身能力），靠对抗 critic 解决；本期暂缓，但 schema 层面预留 C3 规则（见 §3.2）
- `roadmap.md` 已记 G3，这是从 6 个门禁缺陷里**优先级最高的 1 个**

---

## 2. 设计目标与非目标

### 2.1 做什么

| # | 能力 | 解决 |
|---|---|---|
| 1 | Reviewer JSON 持久化为 `requirements/<id>/reviews/<phase>-NNN.json`（append-only） | A/B/D 的数据基础 |
| 2 | `meta.yaml` 加 `reviews` 顶层字段，作为各阶段 latest 指针 + hash 索引 | 切阶段门禁的 O(1) 查询 |
| 3 | 新增 `scripts/save-review.sh` 作为唯一写入通道，schema 层 + CR 规则层双校验 | 防 LLM 直接改文件、防 reviewer 内部一致性失守 |
| 4 | 新增 `scripts/check-reviews.sh` 作为唯一读取通道，7 项门禁校验 | A/B/D 的执行体 |
| 5 | `gate-checklist.md` / `submit-rules.md` / CI 三处接入 `check-reviews.sh` | 把"提示式"全部转"阻断式" |
| 6 | hash drift 自动失效 + `protect-branch` 禁写 reviews 文件 | D 的强约束 |

### 2.2 不做什么（本期）

- **不引入 design-critic Agent**（C2/C1）：等 1~2 个真实需求跑出 reviewer 是否真"虚高"，数据驱动再决定上 C2 还是 C4
- **不做 hash 部分匹配**：reviewed_artifacts 列表里任一 hash 不匹配就整体 stale，不做"哪几个失效"的细粒度
- **不重构现有 reviewer 的评审维度**：本期只改输出契约，维度定义不动

---

## 3. 数据模型

### 3.1 review JSON Schema

文件路径：`requirements/<id>/reviews/<phase>-NNN.json`，append-only。

```json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2026-001-definition-001",
  "requirement_id": "REQ-2026-001",
  "phase": "definition",
  "reviewer": "requirement-quality-reviewer",
  "reviewed_at": "2026-04-27 10:30:00",
  "reviewed_commit": "2fde52f",
  "reviewed_artifacts": [
    {"path": "artifacts/requirement.md", "sha256": "abc123..."}
  ],
  "conclusion": "approved",
  "score": 85,
  "dimensions": {
    "completeness": {"score": 90, "issues": []},
    "consistency":  {"score": 85, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null
}
```

**字段约束**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | string | 是 | 当前固定 `"1.0"`，后续 break change 升 `2.0` |
| `review_id` | string | 是 | 全局唯一，格式 `REV-<requirement_id>-<phase>-<NNN>`；`code` 类走 `REV-<req>-code-<feature_id>-<NNN>` |
| `requirement_id` | string | 是 | 必须匹配所在目录 |
| `phase` | enum | 是 | `definition / outline-design / detail-design / code`（注：`code` 是评审类别名，与项目生命周期 phase 不同——code 类评审实际发生在 `development` 期，按 feature_id 多次评审） |
| `reviewer` | enum | 是 | 4 个 reviewer Agent 名之一 |
| `reviewed_at` | string | 是 | `YYYY-MM-DD HH:MM:SS`（Asia/Shanghai），遵循 `time-format.md` |
| `reviewed_commit` | string | 是 | git rev-parse HEAD 短 hash（7+ 字符），评审快照 |
| `reviewed_artifacts` | array | 是 | 评审实际消费的文件清单 + sha256 |
| `conclusion` | enum | 是 | `approved / needs_revision / rejected` |
| `score` | int 0-100 | 是 | reviewer 综合分 |
| `dimensions` | object | 是 | 各维度分数与 issues |
| `required_fixes` | array | 是（可空） | 必修项；每项 `{description, location, severity}` |
| `suggestions` | array | 是（可空） | 建议项 |
| `scope` | object\|null | 是 | `code` 类专用，`{"feature_id": "F-001"}`；其他 reviewer 必须 null |
| `supersedes` | string\|null | 是 | 二次评审时指向上一份 `review_id`，形成链；首次评审为 null |

`reviewed_artifacts[].sha256` 计算规则：对文件原始字节做 sha256，**不**做行尾标准化或编码转换。

### 3.2 CR 规则（C3 烧进 schema）

`save-review.sh` 在写入前必须通过的内部一致性规则。**违反任一条直接拒收**，reviewer Agent 必须修正后重提：

| ID | 规则 | 意图 |
|---|---|---|
| **CR-1** | `conclusion = approved` ⇒ `required_fixes = []` | 不允许"approved 但有必修项" |
| **CR-2** | `required_fixes ≠ []` ⇒ `conclusion ∈ {needs_revision, rejected}` | 必修项必须升级结论 |
| **CR-3** | 任一 `dimensions.*.score < 60` ⇒ `conclusion ≠ approved` | 单维度过低不可总评通过 |
| **CR-4** | `score < 70` ⇒ `conclusion ≠ approved` | 综合分线 |
| **CR-5** | `dimensions.*.issues[].severity ∈ {blocker, major, minor}` 且 `description` 非空 | 防"打了 80 分但 issues 是空对象" |
| **CR-6** | 任一 `issues[].severity = blocker` ⇒ `conclusion ≠ approved` | blocker 必阻断 |

CR 规则**不涵盖**"维度本身打分虚高"——那是 C 问题的本体，要靠 critic（本期不做）。

### 3.3 meta.yaml.reviews 索引

新增 `reviews` 顶层字段，结构：

```yaml
reviews:
  definition:
    latest: REV-REQ-2026-001-definition-002
    conclusion: approved
    reviewed_commit: 2fde52f
    artifact_hashes:
      "artifacts/requirement.md": "abc123..."
    history: ["REV-REQ-2026-001-definition-001", "REV-REQ-2026-001-definition-002"]
    stale: false
  outline-design:
    latest: null
  detail-design:
    latest: null
  code:
    by_feature:
      F-001:
        latest: REV-REQ-2026-001-code-F001-001
        conclusion: approved
        reviewed_commit: ...
        artifact_hashes: {...}
        history: [...]
        stale: false
```

`stale` 字段由 `check-reviews.sh` 在发现 hash drift 时写入，**不**主动定期扫描。

加入 `meta-schema.yaml`，由 `check-meta.sh` 一并校验结构合法性。

---

## 4. 写入路径：save-review.sh

### 4.1 调用契约

```bash
scripts/save-review.sh \
  --req REQ-2026-001 \
  --phase definition \
  --reviewer requirement-quality-reviewer \
  [--scope feature_id=F-001]      # 仅 phase=code 必填
  < verdict.json                   # JSON via stdin
```

### 4.2 行为

1. 读 stdin JSON
2. JSON schema 校验（字段类型、枚举值、必填）
3. CR-1~CR-6 规则校验
4. 检查 `reviewed_commit` 是否等于 `git rev-parse --short HEAD`；不等则 ERROR（防"评审跑在错误 commit"）
5. 对 `reviewed_artifacts[]` 重算 sha256 并替换 stdin 中的值（防 reviewer 算错或伪造）
6. 计算下一个 NNN（扫 `reviews/` 目录）
7. 写入 `requirements/<req>/reviews/<phase>-NNN.json`（或 `code-<feature_id>-NNN.json`）
8. 更新 `meta.yaml.reviews.<phase>` 段：
   - `latest = review_id`
   - `conclusion = ...`
   - `reviewed_commit = ...`
   - `artifact_hashes = {path: sha256}` 全量覆盖
   - `history.append(review_id)`
   - `stale = false`
9. 退出码 0/1/2 同 `common.py` 约定

### 4.3 实现位置

- `scripts/save-review.sh`（薄壳，参数解析 + 调 Python）
- `scripts/lib/save_review.py`（核心逻辑）
- `scripts/lib/common.py`（复用现有 Severity / Report / exit_code）

---

## 5. 校验机制：check-reviews.sh

### 5.1 调用契约

```bash
scripts/check-reviews.sh \
  --req REQ-2026-001 \
  --target-phase tech-research \   # 即将切到的 phase
  [--strict]
```

### 5.2 7 项校验

| ID | 校验 | 解决 | 默认 Severity | --strict |
|---|---|---|---|---|
| **R001** | 当前 phase 要求的 review 文件**存在**（即 `meta.yaml.reviews.<phase>.latest ≠ null`） | B | ERROR | ERROR |
| **R002** | review JSON schema 合法（含 CR-1~CR-6 复检） | A/C3 | ERROR | ERROR |
| **R003** | `latest.conclusion ≠ rejected` | A | ERROR | ERROR |
| **R004** | `latest.conclusion = needs_revision` | A | WARNING | ERROR |
| **R005** | `reviewed_artifacts` 中所有文件**当前 sha256 匹配** | D | ERROR | ERROR |
| **R006** | `supersedes` 链无环、无悬挂引用 | 数据完整性 | ERROR | ERROR |
| **R007** | `code.by_feature` 覆盖 `features.json` 中所有 `status=done` 的 feature | A/B（开发→测试） | ERROR | ERROR |

### 5.3 phase ↔ 必需 review 映射

| 即将切到的 target-phase | 必须存在的 review |
|---|---|
| `tech-research` | `definition` |
| `outline-design` | `definition` |
| `detail-design` | `outline-design` |
| `task-planning` | `detail-design` |
| `development` | `detail-design` |
| `testing` | `detail-design` + `code`（每个 done feature） |
| `completed` | 全部历史 review 必须存在且不 stale |

### 5.4 R005 hash drift 处理流程

1. 检测到 drift → 把 `meta.yaml.reviews.<phase>.stale = true`（save-review.sh 之外的**唯一**写 meta.reviews 的入口）
2. 报错：`Review REV-... is stale: artifacts/requirement.md changed (was abc..., now def...). Re-run requirement-quality-reviewer.`
3. **不**提供 `--allow-stale` 类参数。理由见 §2.2。

---

## 6. 集成点

### 6.1 Reviewer Agent 输出契约改造

4 个 Agent 的 SKILL.md 末尾从 "返回 JSON 给主对话" 改为：

```
完成评审后，组装 JSON 后调用：

  bash scripts/save-review.sh \
    --req $REQUIREMENT_ID \
    --phase <phase> \
    --reviewer <self> \
    [--scope feature_id=<id>] \
    <<'EOF'
  { ... your verdict JSON ... }
  EOF

如果 save-review.sh 退出码非 0，按 stderr 提示修正后重提；
不要把 JSON 直接丢回主对话——主对话不再读 verdict 文本。
```

### 6.2 gate-checklist.md 改造

每条文本检查替换为脚本引用。示例：

```diff
## definition → tech-research

- [ ] artifacts/requirement.md 存在
- - [ ] 需求评审结论 ≠ rejected（由 requirement-quality-reviewer Agent 产生...）
+ - [ ] `scripts/check-reviews.sh --req $REQ_ID --target-phase tech-research` 退出码 = 0
- [ ] 无「待用户确认」标记
```

`/requirement:next` 的执行体：把"逐条对照清单"改为"逐条跑命令；任一非 0 → 终止"。

### 6.3 submit-rules.md 改造

`/requirement:submit` 的预检里加一条：

```
- [ ] scripts/check-reviews.sh --req $REQ_ID --target-phase $(yq '.phase' meta.yaml) --strict 退出码 = 0
```

### 6.4 CI 接入

`.github/workflows/quality-check.yml` 加 step：

```yaml
- name: Check reviews
  run: |
    for dir in requirements/*/; do
      req=$(basename "$dir")
      [ -f "$dir/meta.yaml" ] || continue
      legacy=$(yq '.legacy // false' "$dir/meta.yaml")
      [ "$legacy" = "true" ] && continue
      phase=$(yq '.phase' "$dir/meta.yaml")
      scripts/check-reviews.sh --req "$req" --target-phase "$phase" --strict
    done
```

PR4 之前 step 不带 `--strict`。

### 6.5 写保护（D7）

两道防线：

1. **`.claude/hooks/protect-branch.sh` 加禁写规则**：拦截对 `requirements/*/reviews/*.json` 的 Edit/Write。`save-review.sh` 是 Bash 调用，不走 Edit/Write 工具，不受影响。
2. **`scripts/git-hooks/pre-commit` 加 diff 校验**：检查 `meta.yaml` 的 `reviews:` 段 diff 是否仅由 save-review.sh / check-reviews.sh 触发；判别方式——commit 前比较 `reviews:` 段，若变化但 `reviews/*.json` 无对应新增/无 hash 变化，则拒 commit。

---

## 7. 落地计划（4 PR · N3 模式）

| PR | 内容 | 风险闸门 | 可独立回滚 |
|---|---|---|---|
| **PR1** 基础设施 | `review-schema.yaml` / `save-review.sh` / `check-reviews.sh` / `meta-schema.yaml` 加 `reviews`（条件必填：phase 在 definition 之后才检查）/ CI 接入但 **non-strict** | 不改任何 reviewer Agent；行为零变化 | 是 |
| **PR2** 试点 | 改 `requirement-quality-reviewer.md` 输出契约；改 `gate-checklist.md` 的 `definition → tech-research` 段；用 1~2 个真实需求跑通 write→read→drift 全链 | 试点期其他 3 reviewer 维持现状 | 是（仅 1 个 Agent） |
| **PR3** 全量切换 | 改剩余 3 个 reviewer + `gate-checklist.md` 全段；加 `protect-branch` 禁写 + pre-commit diff 校验（D7） | reviewer 行为统一；CI 仍 non-strict 不卡死人 | 是 |
| **PR4** 升 strict + 治理 | CI step 加 `--strict`；历史 `requirements/REQ-2026-001` 在 meta.yaml 加 `legacy: true`（D5：completed 跳过、活跃需求强制治理）；`roadmap.md` G3 标记 done | 真正阻断；前面 3 PR 已暴露问题 | 是（去 `--strict` 即可） |

---

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Reviewer Agent SKILL.md 改了之后还是忘记调 save-review.sh | 中 | 高（B 完全失守） | R001 兜底——切阶段时发现 latest=null 直接 ERROR；reviewer 不调 → 切不了阶段 → 主对话被迫回头让 reviewer 重跑 |
| CR 规则太严，reviewer 的 JSON 反复被拒，主对话陷入循环 | 中 | 中（用户体验差） | PR2 试点期重点观察；如出现规律性拒收，调整 CR 阈值（如 CR-4 的 70 分线）而不是关规则 |
| 历史 requirement 数量大，PR4 升 strict 时一批 PR 红 CI | 低（当前仅 1 个 completed REQ） | 低 | `legacy: true` 一键豁免；活跃需求若不多就手工补；写 `scripts/mark-legacy.sh` 一键工具兜底 |
| pre-commit diff 校验逻辑复杂、误判多 | 中 | 中 | PR3 落地时优先实现"meta.yaml.reviews 段被改但 reviews/ 目录无新 json" 这一条，其他规则视实测加 |
| reviewed_artifacts 列表过大（detail-design 阶段可能涉及多文件），hash 计算慢 | 低 | 低 | 仅算 `artifacts/` 下 reviewer 实际消费的文件，由 reviewer 在 JSON 里显式声明；不全量扫目录 |
| `save-review.sh` 写 meta.yaml 时与其他写 meta.yaml 的脚本（`save-meta.sh` 等）发生写冲突 | 低 | 中 | 写入用 `flock` 串行化；YAML 序列化保持字段顺序稳定（用 ruamel.yaml） |

---

## 9. 决策记录

brainstorming 期间敲定的 7 个决策点，记录如下：

| # | 决策点 | 选择 | 理由 |
|---|---|---|---|
| **D1** | review JSON 单文件覆盖 vs append-only | append-only（多文件 + supersedes 链） | 可追溯多次评审，对抗式验证留痕；存储成本低 |
| **D2** | `needs_revision` 是否阻塞切阶段 | 默认 WARNING，--strict ERROR | 给"小问题先推进"的口子，但 CI 强制；本地切阶段不卡死 |
| **D3** | hash drift 处理 | 立即标 stale 强制重审，无 override | 这是 D 问题的全部价值；给口子等于不做 |
| **D4** | `code` 类评审 scope 粒度 | 按 `feature_id`（与 features.json 对齐） | 简单、与现有 feature-lifecycle-manager 自然衔接 |
| **D5** | 历史需求处理 | completed 一律 `legacy: true` 跳过；活跃需求强制治理 | 已 ship 的不动，活跃需求纳入新流程 |
| **D6** | save-review.sh 由谁调用 | Reviewer Agent 直接 Bash 调用（非主对话 LLM 中转） | 少一道传递、少一次 LLM 失误；Agent 有 Bash 权限 |
| **D7** | meta.yaml.reviews 写权限锁定 | hook 字符串拦 + pre-commit diff 校验，双层 | 单层 hook 难精确拦字段；pre-commit 是最后一道 |

C 问题的处理决策（**C5**）：本期不引入 critic Agent，把 C3 烧进 schema（CR-1~CR-6）；落地 1~2 个真实需求后看数据：

- 若多份 review 出现"打分虚高但 CR 全过"的形态 → 启动 C4（schema + 通用 design-critic Agent）
- 若 reviewer 输出基本符合直觉 → 维持现状不加 critic

---

## 10. 后续规划

- 落地后归档 `roadmap.md` G3 标记 done
- 同步推进 G1（CI build/test/lint 兜底）和 G4（testing→completed 校验测试真跑）——这两个与本设计正交，可并行
- C 问题升级（C5 → C4）的触发信号写入 `roadmap.md`：3 个或以上 review 出现"全维度 ≥ 80 分但实际推进时发现 blocker 漏报"

---

## 附录 A：与既有结构化产出物的对比

`features.json` 是项目里已有的结构化产出物（详细设计阶段产出），但其校验是由 `detail-design-quality-reviewer` Agent 手工做（jq + 主观读），**没有专门校验脚本**。本设计在两点上比 features.json 更严：

1. 引入 `save-review.sh` 作为唯一写入通道，不允许 LLM 直接 Edit
2. 引入 `check-reviews.sh` + CI strict 强制校验

`features.json` 后续可参照本设计加一份 `check-features.sh`，但不在本期范围。
