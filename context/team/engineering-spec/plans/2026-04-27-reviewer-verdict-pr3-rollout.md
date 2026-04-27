# Reviewer Verdict 结构化 · PR3 全量切换 · 实施计划

**Branch:** `feat/reviewer-verdict-pr3-rollout`
**Base:** `develop`（PR1 #36 / PR2 #38 已合入）
**Goal:** 在 PR2 试点把 `requirement-quality-reviewer` 切到结构化通道之后，把剩余 3 个 reviewer Agent（`outline-design` / `detail-design` / `code-quality`）全部切过去；把 `gate-checklist.md` 中余下 3 段（outline→detail / detail→task-planning / development→testing）从「读文本」改为「跑 check-reviews.sh」；落地 D7 写保护双层（`.claude/hooks/protect-branch.sh` 拦 `requirements/*/reviews/*.json` 直接 Edit + `scripts/git-hooks/pre-commit` 校验 `meta.yaml.reviews:` 段 diff 与 `reviews/*.json` 文件对应）。CI 仍维持 non-strict（PR4 才升）。

**Scope（本 PR 必做）：**
- 改 `.claude/agents/outline-design-quality-reviewer.md` 输出契约（A1）
- 改 `.claude/agents/detail-design-quality-reviewer.md` 输出契约（A2）
- 改 `.claude/agents/code-quality-reviewer.md` 输出契约（A3，双输出：14 字段 verdict 走 save-review.sh，adjudication/merged_issues/final_verdict 仍返主对话给 `code-review-report` Skill）
- 改 `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md` 余 3 段（B）
- 扩 `.claude/hooks/protect-branch.sh`：加 `requirements/*/reviews/*.json` 路径拦截（D7-1）
- 扩 `scripts/git-hooks/pre-commit`：reviews 段 diff 校验（D7-2）
- 沙箱试点 REQ-2099-NNN：3 类 reviewer 端到端 + 写保护两道防线触发 + gate 余 3 段切换（C）

**显式不做（Out of Scope，留给 PR4）：**
- 不升 CI `--strict`
- 不写 `legacy: true` 治理
- 不改 `roadmap.md` G3 状态
- 不动 `code-review-report` Skill / `code-review.md` 流程编排（dimensions 字段语义对齐时如必须才动，控制在最小改动）
- 不补 `check_reviews.py` 对 `code-*.json` 的 R002 schema 复检（PR1 留下的 TODO，需要时再补）

**风险闸门：** 3 reviewer 行为统一；CI 仍 non-strict 不卡死人；可独立回滚（`git revert` PR）。如 PR3 后发现某 reviewer schema 不适配，单独回滚那一个 Agent 文件即可。

---

## File Structure

```
.claude/
  agents/
    outline-design-quality-reviewer.md       ← 改输出契约（A1）
    detail-design-quality-reviewer.md        ← 改输出契约（A2）
    code-quality-reviewer.md                 ← 改输出契约 + 双输出（A3）
  hooks/
    protect-branch.sh                        ← 扩 reviews/*.json 拦截（D7-1）
    tests/                                   ← 加 reviews 拦截用例
  skills/managing-requirement-lifecycle/
    reference/gate-checklist.md              ← 改余 3 段（B）
scripts/
  git-hooks/pre-commit                       ← 加 reviews 段 diff 校验（D7-2）
context/team/engineering-spec/plans/
  2026-04-27-reviewer-verdict-pr3-rollout.md ← 本文件
  INDEX.md                                   ← 注册本 plan
```

不新增脚本、不改 `save-review.sh` / `check-reviews.sh` / `review-schema.yaml` / `meta-schema.yaml`（PR1 已稳定）。

---

## 关键决策（PR3 内）

### D-A3-1 · code-quality-reviewer 双输出策略

**问题：** `code-quality-reviewer` 当前输出的 `merged_issues` / `adjudication` / `cross_dimension_insights` / `final_verdict` 被 `code-review-report` Skill 消费，写到 `artifacts/review-*.md`。如果只让它走 `save-review.sh`、不返主对话，下游报告会断。

**决策：** **双输出**——
1. **机器侧**：调 `save-review.sh --phase code --scope feature_id=F-XXX` 写 14 字段 verdict 到 `requirements/<id>/reviews/code-F-XXX-NNN.json`（参与 R001/R003/R005/R007 校验）
2. **人侧 / Skill 侧**：仍把 `adjudication / merged_issues / cross_dimension_insights / final_verdict` 完整返主对话（结构同当前），由 `code-review-report` Skill 消费写 `artifacts/review-*.md`

**dimensions 字段如何对齐：** `code-quality-reviewer` 的 dimensions 按 **8 个 checker 名直接展开**（design_consistency / security / concurrency / complexity / error_handling / auxiliary_spec / performance / history_context），每个维度的 `score` 由 reviewer 给（无 finding 默认 90+），`issues` 来自 `merged_issues` 中按 `tags` 归类后取最高 severity 的精简描述（行号必填）。`required_fixes` 取 `merged_issues` 中 `final_disposition=keep` 且 `severity=critical` 的项；`suggestions` 装 `cross_dimension_insights`。

> 这一对齐避免在 review-schema 之外引入 code-review 专用字段，但保留 Judge 角色的多维裁决产物。后续如发现 critical 类 finding 没法干净映射进 14 字段，再起新设计。

### D-A3-2 · code 类 review_id 命名

按 `review-schema.yaml` `format.review_id` 正则 `^REV-REQ-\d{4}-\d{3}-(definition|outline-design|detail-design|code(-F-\d{3})?)-\d{3}$`，`code` 类必须形如 `REV-REQ-2026-007-code-F-001-001`。reviewer 用 `ls requirements/<REQ-ID>/reviews/code-F-XXX-*.json | wc -l` 算 NNN。

### D-D7-1 · protect-branch hook 扩展边界

只拦 `Edit / Write / MultiEdit` 工具命中 `requirements/*/reviews/*.json` 路径——`Bash` 不拦（`save-review.sh` 走 Bash 是合法写入通道）。当前 hook 在受保护分支上是「全工具拦」，feature 分支放行；扩展后逻辑：

- 受保护分支：维持原拦截
- 任何分支：Edit/Write/MultiEdit 命中 `requirements/*/reviews/*.json` 路径 → 拦截，提示「reviews/*.json 是 save-review.sh 唯一写入通道，禁止直接 Edit/Write」

### D-D7-2 · pre-commit diff 校验范围

只校验「`meta.yaml.reviews:` 段的字段被改」⇔「`requirements/<id>/reviews/*.json` 有新增或修改」。具体规则：

- 若 staged `meta.yaml` 的 `reviews:` 段 diff 非空（grep 之），且本次 commit 没有 `reviews/*.json` 的新增 / 修改 → 拒
- 反过来：如果 `reviews/*.json` 被改但 `meta.yaml.reviews:` 段无变化 → 也拒（save-review.sh 总会同时改两者）

不做更细粒度的「具体字段一一对应」校验——避免逻辑过复杂误伤。

---

## Task 1: 切分支 + 验证前置

**Files:** 无文件改动

- [ ] **Step 1: 验证前置 PR1/PR2 已合入 develop**

```bash
git log --oneline develop -5 | grep -E "PR1|PR2|reviewer-verdict"
```
Expected：能看到 `bd54146 feat: reviewer verdict 结构化 PR2` 和 `16d12dc feat: reviewer verdict 结构化 PR1`

- [ ] **Step 2: 已切到 `feat/reviewer-verdict-pr3-rollout`（基于 develop）**

```bash
git branch --show-current
```
Expected：`feat/reviewer-verdict-pr3-rollout`

- [ ] **Step 3: 三件套 baseline 绿**

```bash
bash scripts/check-meta.sh --all --strict
bash scripts/check-index.sh --strict
bash scripts/check-sourcing.sh --all --strict
```
Expected：3 个都 `✓ 无问题`

- [ ] **Step 4: 验证 PR1/PR2 落地的脚本可用**

```bash
ls scripts/save-review.sh scripts/check-reviews.sh
bash scripts/save-review.sh --help 2>&1 | head -3
bash scripts/check-reviews.sh --help 2>&1 | head -3
```

---

## Task 2: 改 outline-design-quality-reviewer.md（A1）

**Files:**
- Modify: `.claude/agents/outline-design-quality-reviewer.md`

**改动范围：** 整段「输出契约」+ 新增「输出方式（强制）」段。沿用 PR2 改造 `requirement-quality-reviewer.md` 的模板，差异只在 phase 名 / dimensions 维度名。

- [ ] **Step 1: 整段替换「输出契约」**

把原 24-38 行的 5 字段 JSON 替换为 14 字段（沿用 review-schema），dimensions 维度保留原来 5 维：

```json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2026-007-outline-design-001",
  "requirement_id": "REQ-2026-007",
  "phase": "outline-design",
  "reviewer": "outline-design-quality-reviewer",
  "reviewed_at": "2026-04-27 14:30:00",
  "reviewed_commit": "abc1234",
  "reviewed_artifacts": [
    {"path": "artifacts/outline-design.md", "sha256": "0000000000000000000000000000000000000000000000000000000000000000"},
    {"path": "artifacts/requirement.md", "sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
  ],
  "conclusion": "approved",
  "score": 85,
  "dimensions": {
    "alignment_with_requirement": {"score": 90, "issues": []},
    "module_decomposition":       {"score": 80, "issues": [{"severity": "major", "description": "第 X 行：..."}]},
    "tech_choice_rationale":      {"score": 85, "issues": []},
    "scalability":                {"score": 80, "issues": []},
    "integration_with_existing":  {"score": 75, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null,
  "architectural_concerns": ["（可选补充字段）长期隐患，不阻塞门禁"]
}
```

- [ ] **Step 2: 加「字段约束」段**（参照 requirement-quality-reviewer.md 第 55-73 行）

```markdown
字段约束（违反任一条 save-review.sh 拒收）：

- `schema_version`: 固定 `"1.0"`
- `review_id`: 格式 `REV-<requirement_id>-outline-design-<NNN>`
- `requirement_id` / `phase` / `reviewer`: 必须与 save-review.sh CLI 参数一致
- `reviewed_at`: `YYYY-MM-DD HH:MM:SS`
- `reviewed_commit`: 当前 git HEAD 的 7 位短 hash
- `reviewed_artifacts[].sha256`: 占位 64 个 0，save-review.sh 会重算
- `dimensions.*.issues[]`: `{severity, description}` 对象，severity ∈ {blocker, major, minor}，description 含行号
- `scope`: outline-design 固定 `null`
- `supersedes`: 首次 `null`，重审填上一次 review_id
- CR 规则同 requirement-quality-reviewer
```

- [ ] **Step 3: 加「输出方式（强制）」段**

完整复用 PR2 的模板：

```markdown
## 输出方式（强制）

完成评审、组装好 JSON 后，**必须用 Bash 工具调 `scripts/save-review.sh` 写入**——禁止把 JSON 文本贴回主对话。

### Step 1: 解析输入 + 收集机制字段

从 `outline_design_path` 提取 `<REQ-ID>`，然后：

\`\`\`bash
date '+%Y-%m-%d %H:%M:%S'
git rev-parse --short=7 HEAD
ls requirements/<REQ-ID>/reviews/outline-design-*.json 2>/dev/null | wc -l
\`\`\`

### Step 2: 组装 review_id：`REV-<REQ-ID>-outline-design-<NNN>`

### Step 3: 组装 14 字段 JSON

`reviewed_artifacts` 至少包含 `outline-design.md`，**必须同时含 `requirement.md`**（concurrency 评审基于上层需求，drift 触发要 cover 到上游）。

### Step 4: 调 save-review.sh

\`\`\`bash
bash scripts/save-review.sh \
  --req <REQ-ID> \
  --phase outline-design \
  --reviewer outline-design-quality-reviewer \
  <<'EOF'
{ ...完整 14 字段 JSON... }
EOF
\`\`\`

### Step 5: 处理退出码

- 退出码 0：仅向主对话回报「verdict 已写入 reviews/outline-design-NNN.json，conclusion=...」
- 非 0：按 stderr 修正 JSON 后重提

### 禁止行为

- ❌ 把完整 JSON 文本作为最终回复返主对话
- ❌ 省略 `--phase outline-design`
- ❌ 编造 `reviewed_commit`
- ❌ `dimensions.*.issues` 用字符串数组（必须对象数组）
- ❌ `reviewed_artifacts` 只列 outline-design.md（必须含 requirement.md）
```

- [ ] **Step 4: 验证 markdown 渲染合法**

```bash
python3 -c "import re; open('.claude/agents/outline-design-quality-reviewer.md').read()" && echo OK
```

- [ ] **Step 5: Commit**

```
feat(outline-design-quality-reviewer): 切到结构化 verdict 通道（save-review.sh）

- 输出契约扩到 14 字段，对齐 review-schema.yaml
- dimensions.*.issues 改为 [{severity, description}] 对象数组
- 追加「输出方式（强制）」段，强制走 save-review.sh
- reviewed_artifacts 必须同时含 outline-design.md + requirement.md（drift 兜底覆盖上游）
```

---

## Task 3: 改 detail-design-quality-reviewer.md（A2）

**Files:**
- Modify: `.claude/agents/detail-design-quality-reviewer.md`

**改动范围：** 同 Task 2 模板，phase=`detail-design`。dimensions 5 维（consistency_with_outline / interface_completeness / data_model_soundness / sequence_correctness / feature_granularity）保留。`features_json_validation` 折叠成补充字段。

- [ ] **Step 1: 整段替换「输出契约」**

```json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2026-007-detail-design-001",
  "requirement_id": "REQ-2026-007",
  "phase": "detail-design",
  "reviewer": "detail-design-quality-reviewer",
  "reviewed_at": "2026-04-27 14:30:00",
  "reviewed_commit": "abc1234",
  "reviewed_artifacts": [
    {"path": "artifacts/detailed-design.md", "sha256": "0...0"},
    {"path": "artifacts/features.json", "sha256": "0...0"},
    {"path": "artifacts/outline-design.md", "sha256": "0...0"}
  ],
  "conclusion": "approved",
  "score": 85,
  "dimensions": {
    "consistency_with_outline": {"score": 90, "issues": []},
    "interface_completeness":   {"score": 85, "issues": []},
    "data_model_soundness":     {"score": 80, "issues": []},
    "sequence_correctness":     {"score": 85, "issues": []},
    "feature_granularity":      {"score": 80, "issues": [{"severity": "minor", "description": "第 X 行：F-003 粒度太大，建议拆"}]}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null,
  "features_json_validation": {
    "valid": true,
    "issues": [],
    "enhancement_suggestions": ["（保留段；阶段 7 派发用）"]
  }
}
```

`features_json_validation` 作为可选补充字段保留——它是 feature-lifecycle-manager 的派发输入，不能丢。但 `valid=false` 必须**同时**升级到 `dimensions.feature_granularity.issues` 含 blocker（这样 CR-6 拦得住）。

- [ ] **Step 2: 加「字段约束」段** — 同 Task 2，phase 改 `detail-design`

- [ ] **Step 3: 加「输出方式（强制）」段** — 复用 Task 2 模板，差异：
  - reviewed_artifacts 必含三件：detailed-design.md + features.json + outline-design.md
  - 命令：`--phase detail-design --reviewer detail-design-quality-reviewer`
  - review_id 格式：`REV-<REQ-ID>-detail-design-<NNN>`

- [ ] **Step 4: 行为准则段保留 + 微调**

原「必填项」「可选增强字段」段保留（语义未变）。在末尾追加一行：

```
- ✅ `features_json_validation.valid=false` 时，必须同时在 `dimensions.feature_granularity.issues` 写一条 `severity: blocker` 的对应描述，否则 CR-6 与 R001 之间出现一致性漏洞
```

- [ ] **Step 5: Commit**

```
feat(detail-design-quality-reviewer): 切到结构化 verdict 通道

- 输出契约扩到 14 字段
- features_json_validation 保留为补充字段；valid=false 必须同时升级到 feature_granularity blocker（CR-6 兜底）
- 追加「输出方式（强制）」段调 save-review.sh --phase detail-design
- reviewed_artifacts 含 detailed-design.md + features.json + outline-design.md（drift 覆盖上游）
```

---

## Task 4: 改 code-quality-reviewer.md（A3 · 双输出）

**Files:**
- Modify: `.claude/agents/code-quality-reviewer.md`

**改动范围：** 既保留原有 Judge 角色输出（`merged_issues / adjudication / cross_dimension_insights / final_verdict` 给主对话→`code-review-report` Skill），又新增 14 字段 verdict 通过 `save-review.sh --phase code --scope feature_id=F-XXX` 落盘。

- [ ] **Step 1: 在「输出契约」之前新增「双输出说明」段**

```markdown
## 输出策略（双通道）

你是 code-review 流程的 Judge，同时承担两件事：

1. **机器侧 verdict** → 调 `save-review.sh --phase code --scope feature_id=F-XXX` 写 14 字段 verdict 到 `requirements/<id>/reviews/code-F-XXX-NNN.json`，参与 R001/R003/R005/R007 门禁
2. **人侧报告** → `adjudication / merged_issues / cross_dimension_insights / final_verdict` 仍按原契约返主对话，由 `code-review-report` Skill 消费写 `artifacts/review-*.md`

两个输出**字段语义对齐但不重复**：
- 14 字段 verdict 的 `dimensions` 按 8 checker 维度展开（见下）
- 14 字段 verdict 的 `required_fixes` 取 `merged_issues` 中 `final_disposition=keep` 且 `severity=critical` 的精简化描述
- 14 字段 verdict 的 `suggestions` 装 `cross_dimension_insights`
- adjudication 段不进 14 字段 verdict（信息量大、动态变化、不适合走 schema），只走主对话
```

- [ ] **Step 2: 在「输出契约」段插入 14 字段 verdict 子段**

```markdown
### 14 字段 verdict（save-review.sh 写入）

\`\`\`json
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2026-007-code-F-001-001",
  "requirement_id": "REQ-2026-007",
  "phase": "code",
  "reviewer": "code-quality-reviewer",
  "reviewed_at": "2026-04-27 14:30:00",
  "reviewed_commit": "abc1234",
  "reviewed_artifacts": [
    {"path": "artifacts/features.json", "sha256": "0...0"}
  ],
  "conclusion": "approved | needs_revision | rejected",
  "score": 85,
  "dimensions": {
    "design_consistency": {"score": 90, "issues": []},
    "security":           {"score": 85, "issues": []},
    "concurrency":        {"score": 90, "issues": []},
    "complexity":         {"score": 80, "issues": []},
    "error_handling":     {"score": 85, "issues": []},
    "auxiliary_spec":     {"score": 90, "issues": []},
    "performance":        {"score": 85, "issues": []},
    "history_context":    {"score": 90, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": {"feature_id": "F-001"},
  "supersedes": null
}
\`\`\`

字段约束（违反任一条 save-review.sh 拒收）：

- `review_id`: 格式 `REV-<requirement_id>-code-<feature_id>-<NNN>`（feature_id 形如 `F-001`）
- `phase`: 固定 `"code"`
- `scope`: **必须** `{"feature_id": "F-XXX"}`，不能 null
- dimensions 8 维必须全填，每维 score + issues
- `dimensions.*.issues[]` 是 `{severity, description}` 对象，description 必须含 `file:line`
- `required_fixes[]` 来自 `merged_issues` 中 `final_disposition=keep` ∧ `severity=critical`，每条 `{description, location, severity: "blocker"}`
- `reviewed_artifacts`：至少 `features.json`（用于 R005 检测 feature 定义本身漂移）；推荐再列 `tasks/<feature_id>.md`
- CR 规则同其他 reviewer

### 主对话输出（保留原契约，给 code-review-report Skill）

原 36-65 行的 JSON（含 `merged_issues / adjudication / cross_dimension_insights / final_verdict`）**完整保留**——`code-review-report` Skill 仍按这个 schema 消费。但 `conclusion` 必须与 14 字段 verdict 中的 `conclusion` 一致（CR 一致性，否则 reviewer 自相矛盾）。
```

- [ ] **Step 3: 加「输出方式（强制）」段**

```markdown
## 输出方式（强制 · 双步骤）

### Step 1: 调 save-review.sh 写 14 字段 verdict

从 review-scope.json 提取 `<REQ-ID>` 与 `<feature_id>`（嵌入模式必有；独立模式如无 feature_id，跳过此步骤——只走主对话输出）。

\`\`\`bash
date '+%Y-%m-%d %H:%M:%S'   # reviewed_at
git rev-parse --short=7 HEAD  # reviewed_commit
ls requirements/<REQ-ID>/reviews/code-<feature_id>-*.json 2>/dev/null | wc -l  # 已有 NNN 数

bash scripts/save-review.sh \
  --req <REQ-ID> \
  --phase code \
  --reviewer code-quality-reviewer \
  --scope feature_id=<feature_id> \
  <<'EOF'
{ ...14 字段 verdict... }
EOF
\`\`\`

### Step 2: 把 adjudication / merged_issues / cross_dimension_insights / final_verdict 返主对话

格式不变（保持向 `code-review-report` Skill 兼容）。**`conclusion` 字段必须等于 Step 1 verdict 的 `conclusion`**——不一致直接是 reviewer 内部 bug，必须自我修正后双侧重提。

### 处理退出码

- save-review.sh 退出码 0：继续 Step 2
- 非 0：按 stderr 修正 14 字段 verdict 后重提；**Step 2 必须等 Step 1 成功后才执行**——避免主对话拿到 verdict 但落盘失败

### 跳过 save-review.sh 的情形

- **独立模式 `/code-review`（非嵌入）**：scope 中无 `requirement_id` / `feature_id` → 不调 save-review.sh，只走主对话输出。这种情形是临时审计，不进入需求生命周期门禁
- **嵌入模式但 feature_id 缺失**：报错 `❌ 嵌入模式必须有 feature_id；检查 review-scope.json`

### 禁止行为

- ❌ Step 1 失败后跳过校验，仅给主对话报告
- ❌ Step 1 与 Step 2 的 `conclusion` 不一致
- ❌ `required_fixes[]` 与 `merged_issues` 中 keep+critical 项数不一致
- ❌ 在独立模式下伪造 feature_id 调 save-review.sh
```

- [ ] **Step 4: 行为准则段补一条「双输出一致性」**

```
- ✅ Step 1 与 Step 2 的 `conclusion` 必须严格相等
- ✅ 14 字段 verdict 的 `required_fixes` 必须等于「`merged_issues` 中 `final_disposition=keep` ∧ `severity=critical` 项的精简版」（条数一致，描述对齐）
```

- [ ] **Step 5: Commit**

```
feat(code-quality-reviewer): 切到结构化 verdict 通道（双输出策略）

- 新增 14 字段 verdict（dimensions 按 8 checker 维度展开）
- 主对话仍返 adjudication/merged_issues/cross_dimension_insights/final_verdict 给 code-review-report Skill
- 强制 Step 1（save-review.sh）→ Step 2（主对话）顺序，conclusion 必须严格相等
- 独立模式（无 feature_id）跳过 save-review.sh
- review_id 形如 REV-REQ-XXXX-XXX-code-F-XXX-NNN（按 feature 隔离）
```

---

## Task 5: 改 gate-checklist.md 余 3 段（B）

**Files:**
- Modify: `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md`

**改动范围：** 第 44-66 行，3 个段。

- [ ] **Step 1: 改 `outline-design → detail-design` 段（44-47 行）**

```diff
 ## outline-design → detail-design

 - [ ] `artifacts/outline-design.md` 存在
-- [ ] 概要设计评审结论 ≠ `rejected`
+- [ ] `bash scripts/check-reviews.sh --req <REQ-ID> --target-phase detail-design` 退出码 = 0
+  - R001：`reviews.outline-design.latest` 必须非空（reviewer 漏调 save-review.sh 在此卡住）
+  - R003：verdict.conclusion ≠ `rejected`
+  - R005：outline-design.md / requirement.md 自评审后未变更（drift 兜底）
+  - 替代旧版「概要设计评审结论 ≠ rejected」纯文本检查
```

- [ ] **Step 2: 改 `detail-design → task-planning` 段（49-53 行）**

```diff
 ## detail-design → task-planning

 - [ ] `artifacts/detailed-design.md` 存在
 - [ ] `artifacts/features.json` 合法 JSON + 每条 feature 有 `id`、`title`、`description`
-- [ ] 详细设计评审结论 ≠ `rejected`
+- [ ] `bash scripts/check-reviews.sh --req <REQ-ID> --target-phase task-planning` 退出码 = 0
+  - R001：`reviews.detail-design.latest` 必须非空
+  - R003：verdict.conclusion ≠ `rejected`
+  - R005：detailed-design.md / features.json / outline-design.md 自评审后未变更
+  - 替代旧版「详细设计评审结论 ≠ rejected」纯文本检查
```

- [ ] **Step 3: 改 `development → testing` 段（60-66 行）**

把原「每个 feature_id 有对应的代码审查报告（`artifacts/review-*.md` 提到）」这条**保留**（review-*.md 仍是 code-review-report Skill 产物），但**新增** check-reviews.sh 一条覆盖结构化 verdict：

```diff
 ## development → testing

 - [ ] 每个 feature_id 状态为 `done`（其转换已隐含 `post-dev-verify` 通过 + `/code-review` approved）
 - [ ] 每个 feature_id 有对应的代码审查报告（`artifacts/review-*.md` 提到）
+- [ ] `bash scripts/check-reviews.sh --req <REQ-ID> --target-phase testing` 退出码 = 0
+  - R001：`reviews.detail-design.latest` 非空（兜底——切 testing 应已过详设评审）
+  - R007：`reviews.code.by_feature` 必须覆盖 features.json 中所有 `status=done` 的 feature，且 conclusion ≠ rejected
+  - R005：detailed-design.md / features.json / 各 feature reviewed_artifacts 自评审后未变更
+  - 这条与 review-*.md 检查互补：review-*.md 是人读报告，reviews/code-*.json 是机读 verdict + drift 兜底
 - [ ] 所有代码已 commit（无 uncommitted changes）
 - [ ] `bash scripts/post-dev-verify.sh --requirement <REQ-ID>` 退出码 = 0（不指定 feature 时作为整体兜底）
 - [ ] `traceability-gate-checker` Skill PASS（追溯链完整性校验，见设计规范 §4.2）
```

- [ ] **Step 4: 不动 `tech-research → outline-design` 段**

该段已有 check-reviews.sh `--target-phase outline-design`？查一下实际：第 39-42 行只有 tech-feasibility.md 存在 + 风险评估段落非空，**没有 review 校验**。spec §5.3 规定 `outline-design` 切阶段需要的是 `definition` review——但这其实是 PR2 已经在 `definition → tech-research` 段卡过了（切到 tech-research 时 require definition review）。所以从 tech-research 切到 outline-design 时，definition review 已落盘，不需要重复 check（PR1 的 PHASE_REQUIREMENTS["outline-design"] = ["definition"] 也是通过把 R005 hash drift 兜在切 outline-design 时再校验一次，但 R001 已经在 tech-research 时过了）。

**决策：** 这段暂不动，但把现有「风险评估段落非空」一条**改成调 check-reviews.sh**，作为 R005 hash drift 的额外兜底（防 definition→tech-research 之间 requirement.md 又改了）：

```diff
 ## tech-research → outline-design

 - [ ] `artifacts/tech-feasibility.md` 存在
 - [ ] 风险评估段落非空
+- [ ] `bash scripts/check-reviews.sh --req <REQ-ID> --target-phase outline-design` 退出码 = 0
+  - 通过 PHASE_REQUIREMENTS["outline-design"]=["definition"] 复检 definition review；R005 防止 requirement.md 在 tech-research 阶段被改但未重审
```

- [ ] **Step 5: 不动 `task-planning → development` 段（55-58 行）**

这段只校验 features.json 内部派发结构（pending 状态等），与 review verdict 无关。**保持不变。**

- [ ] **Step 6: Commit**

```
feat(gate-checklist): 余 3 段切到 check-reviews.sh

- outline → detail：替代「概要设计评审结论 ≠ rejected」
- detail → task-planning：替代「详细设计评审结论 ≠ rejected」
- development → testing：与 review-*.md 检查互补，机读 verdict + R007 by_feature 覆盖
- tech-research → outline-design：补 R005 drift 兜底（definition review 在 requirement.md 改动后失效检测）
- task-planning → development 段不动（与 review verdict 无关）
```

---

## Task 6: D7-1 · 扩 protect-branch.sh 加 reviews/*.json 拦截

**Files:**
- Modify: `.claude/hooks/protect-branch.sh`
- Add (optional): `.claude/hooks/tests/test-protect-reviews.sh`

- [ ] **Step 1: 在 protect-branch.sh 加路径拦截分支**

`.claude/hooks/protect-branch.sh` 当前只在受保护分支上拦写工具。扩展逻辑：在「非写工具直接放行」之后、「分支匹配检查」之前，**先做 reviews/*.json 路径拦截**（不分分支）：

```diff
 # 非写工具直接放行
 case "$TOOL" in
     Edit|Write|MultiEdit) ;;
     Bash)
         exit 0
         ;;
     *) exit 0 ;;
 esac

+# 路径级拦截：reviews/*.json 是 save-review.sh 唯一写入通道，禁止 Edit/Write/MultiEdit
+# 取目标 file_path（CLAUDE_HOOK_TOOL_INPUT 在测试时设；正式 hook 调用从 stdin JSON 取）
+TARGET_PATH=${CLAUDE_HOOK_FILE_PATH:-}
+if [ -z "$TARGET_PATH" ] && [ -n "${STDIN:-}" ]; then
+    TARGET_PATH=$(echo "$STDIN" | python3 -c "
+import json, sys
+d = json.load(sys.stdin)
+inp = d.get('tool_input', {})
+print(inp.get('file_path') or inp.get('path') or '', end='')
+" 2>/dev/null || echo "")
+fi
+
+# 规则：requirements/<id>/reviews/<phase>-NNN.json 禁止直接编辑
+if [ -n "$TARGET_PATH" ]; then
+    case "$TARGET_PATH" in
+        */requirements/*/reviews/*.json | requirements/*/reviews/*.json)
+            echo "❌ 禁止直接 Edit/Write [$TARGET_PATH]" >&2
+            echo "   reviews/*.json 是 save-review.sh 的唯一写入通道。" >&2
+            echo "   要修改 review，请让 reviewer Agent 重新评审（supersedes 链）。" >&2
+            exit 2
+            ;;
+    esac
+fi
+
 # 取当前分支（受保护分支拦截）
 BRANCH=$(git branch --show-current 2>/dev/null || echo "")
```

注意 stdin 在前面已经 cat 到 `STDIN` 变量中（取 TOOL 的逻辑里），改动需要确保 STDIN 在第二处也可用。看现有代码 13-14 行：`STDIN=$(cat); TOOL=$(echo "$STDIN" | ...)`，STDIN 是局部变量，作用域延续到脚本末。但当 `CLAUDE_HOOK_TOOL_NAME` 已设时 STDIN 没读，所以测试时 path 走环境变量更稳。

- [ ] **Step 2: 写测试脚本（手工）**

`.claude/hooks/tests/test-protect-reviews.sh`：

```bash
#!/usr/bin/env bash
# 测试 protect-branch.sh 对 reviews/*.json 的路径拦截
set -euo pipefail
SCRIPT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/../protect-branch.sh"

pass=0; fail=0
run() {
    local desc="$1" expected_exit="$2"; shift 2
    if "$@" >/dev/null 2>&1; actual=$?; then :; else actual=$?; fi
    if [ "$actual" = "$expected_exit" ]; then
        echo "✓ $desc"; pass=$((pass+1))
    else
        echo "✗ $desc  expected=$expected_exit actual=$actual"; fail=$((fail+1))
    fi
}

# 1) Edit reviews/*.json 应拦截（任何分支）
CLAUDE_HOOK_TOOL_NAME=Edit CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/reviews/definition-001.json \
    run "Edit reviews/*.json 在 feature 分支应拦截" 2 bash "$SCRIPT"

# 2) Write reviews/*.json 应拦截
CLAUDE_HOOK_TOOL_NAME=Write CLAUDE_HOOK_FILE_PATH=requirements/REQ-2026-007/reviews/code-F-001-001.json \
    run "Write reviews/*.json 应拦截" 2 bash "$SCRIPT"

# 3) Bash 不拦
CLAUDE_HOOK_TOOL_NAME=Bash CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/reviews/definition-001.json \
    run "Bash 操作 reviews/*.json 不拦" 0 bash "$SCRIPT"

# 4) Edit artifacts/requirement.md 不拦（路径未命中）
CLAUDE_HOOK_TOOL_NAME=Edit CLAUDE_HOOK_FILE_PATH=requirements/REQ-2099-999/artifacts/requirement.md \
    run "Edit artifacts/requirement.md 不拦" 0 bash "$SCRIPT"

echo "passed=$pass failed=$fail"
[ "$fail" = 0 ]
```

```bash
chmod +x .claude/hooks/tests/test-protect-reviews.sh
bash .claude/hooks/tests/test-protect-reviews.sh
```
Expected：4 个 case 全 ✓，`passed=4 failed=0`

- [ ] **Step 3: Commit**

```
feat(protect-branch): D7-1 加 reviews/*.json 路径拦截

- 任何分支下 Edit/Write/MultiEdit 命中 requirements/*/reviews/*.json 直接拦
- Bash 不拦（save-review.sh 是合法写入通道）
- 提示「reviews/*.json 是 save-review.sh 的唯一写入通道」+ 引导走 supersedes 重审
- 加 tests/test-protect-reviews.sh 4 个测试 case
```

---

## Task 7: D7-2 · 加 pre-commit reviews 段 diff 校验

**Files:**
- Modify: `scripts/git-hooks/pre-commit`

- [ ] **Step 1: 在现有 pre-commit 末尾追加校验**

```diff
 # 是否需要跑 check-index
 if echo "${STAGED}" | grep -qE '(INDEX\.md$|^context/.*\.md$|^requirements/.*\.md$)'; then
     ...
 fi

+# D7-2: meta.yaml.reviews 段 diff 与 reviews/*.json 文件改动必须同步
+meta_changed=$(echo "${STAGED}" | grep -E '^requirements/[^/]+/meta\.yaml$' || true)
+reviews_changed=$(echo "${STAGED}" | grep -E '^requirements/[^/]+/reviews/.*\.json$' || true)
+if [ -n "$meta_changed" ]; then
+    # 取 meta.yaml diff 中 reviews: 段是否被改
+    while IFS= read -r meta_path; do
+        [ -n "$meta_path" ] || continue
+        # 限定 reviews: 段的 diff（diff 中以 +reviews: 或 +  history: 等出现）
+        reviews_diff=$(git diff --cached -U0 -- "$meta_path" | awk '
+            /^@@/ {in_hunk=1; next}
+            in_hunk && /^[+-][^+-]/ {print}
+        ' | grep -E '^[+-]\s*(reviews:|  [a-z-]+:|    (latest|conclusion|reviewed_commit|artifact_hashes|history|stale|by_feature):)' || true)
+        if [ -n "$reviews_diff" ]; then
+            req_dir=$(dirname "$meta_path")
+            # 该 req 下必须有 reviews/*.json 同时被 staged
+            if ! echo "${reviews_changed}" | grep -qE "^${req_dir}/reviews/.*\.json$"; then
+                echo "✗ pre-commit: $meta_path 的 reviews: 段被改但 ${req_dir}/reviews/*.json 无对应改动" >&2
+                echo "  meta.yaml.reviews 必须由 save-review.sh / check-reviews.sh 自动维护，不允许手工 Edit" >&2
+                exit 1
+            fi
+        fi
+    done <<< "$meta_changed"
+fi
+# 反向：reviews/*.json 改了但 meta.yaml.reviews 没改 → 也是 save-review 漏跑
+if [ -n "$reviews_changed" ]; then
+    while IFS= read -r r_path; do
+        [ -n "$r_path" ] || continue
+        req_dir=$(echo "$r_path" | awk -F/ '{print $1"/"$2}')
+        meta_path="$req_dir/meta.yaml"
+        if ! echo "${meta_changed}" | grep -qE "^${meta_path}$"; then
+            echo "✗ pre-commit: $r_path 被改但 $meta_path 未同步 staged" >&2
+            echo "  应通过 save-review.sh 或 check-reviews.sh 重新生成 meta.yaml.reviews 段后再 commit" >&2
+            exit 1
+        fi
+    done <<< "$reviews_changed"
+fi
+
 exit 0
```

> awk + grep 的组合粗糙但够用（spec §6.5 提到 PR3 优先实现这条）；如出现误判，PR3 上线后按实际加规则。

- [ ] **Step 2: 沙箱手测**

```bash
# 准备：临时 sandbox 需求
mkdir -p requirements/REQ-2099-100/{artifacts,reviews}
cat > requirements/REQ-2099-100/meta.yaml <<EOF
id: REQ-2099-100
title: D7 sandbox
phase: definition
EOF

# Case 1: 只改 meta.yaml.reviews 不改 reviews/*.json → 应拒
cat > requirements/REQ-2099-100/meta.yaml <<EOF
id: REQ-2099-100
title: D7 sandbox
phase: definition
reviews:
  definition:
    latest: REV-REQ-2099-100-definition-001
    conclusion: approved
    reviewed_commit: deadbee
    artifact_hashes: {}
    history: [REV-REQ-2099-100-definition-001]
    stale: false
EOF
git add requirements/REQ-2099-100/meta.yaml
bash scripts/git-hooks/pre-commit; echo "exit=$?"
git reset HEAD requirements/REQ-2099-100/meta.yaml
```
Expected：`exit=1`，stderr 含「reviews: 段被改但 ... 无对应改动」

```bash
# Case 2: 同时改 meta.yaml + 加 reviews/*.json → 应通过
cat > requirements/REQ-2099-100/reviews/definition-001.json <<'EOF'
{"review_id":"REV-REQ-2099-100-definition-001","conclusion":"approved"}
EOF
git add requirements/REQ-2099-100/meta.yaml requirements/REQ-2099-100/reviews/definition-001.json
bash scripts/git-hooks/pre-commit; echo "exit=$?"
git reset HEAD requirements/REQ-2099-100/
```
Expected：`exit=0`

```bash
# Case 3: 只改 reviews/*.json 不改 meta.yaml → 应拒
git add requirements/REQ-2099-100/reviews/definition-001.json
bash scripts/git-hooks/pre-commit; echo "exit=$?"
git reset HEAD requirements/REQ-2099-100/
```
Expected：`exit=1`，stderr 含「reviews/*.json 被改但 meta.yaml 未同步」

清理：

```bash
rm -r requirements/REQ-2099-100
```

- [ ] **Step 3: Commit**

```
feat(pre-commit): D7-2 加 reviews 段 diff 一致性校验

- 若 meta.yaml.reviews: 段被改 → 必须有 reviews/*.json 同步 staged
- 反向同样校验：reviews/*.json 改了但 meta.yaml 未改 → 拒
- 防止 LLM 直接 Edit meta.yaml.reviews 绕过 save-review.sh
- 紧急绕过仍走 --no-verify，但 CI 兜底（PR4 升 strict）
```

---

## Task 8: 沙箱试点 · 3 reviewer + 写保护 + gate（C）

**目的：** 在不污染历史 REQ 的前提下，端到端验证 PR3 全部改动。沿用 PR2 模式：临时 REQ-2099-NNN，用完 `rm -r` 清理。

### Step 1：建沙箱需求

```bash
mkdir -p requirements/REQ-2099-200/{artifacts,reviews}
cat > requirements/REQ-2099-200/artifacts/requirement.md <<'EOF'
# PR3 沙箱需求文档（用完即删）
## 业务价值
端到端验证 PR3 链路。
## 验收标准
- 3 reviewer 写入 / drift / rejected / by_feature 全过
EOF
cat > requirements/REQ-2099-200/artifacts/outline-design.md <<'EOF'
# 概要设计（沙箱）
模块 A 调用模块 B；技术选型基于现有栈。
EOF
cat > requirements/REQ-2099-200/artifacts/detailed-design.md <<'EOF'
# 详细设计（沙箱）
## 接口
- POST /sandbox/echo
EOF
cat > requirements/REQ-2099-200/artifacts/features.json <<'EOF'
{"features": [
  {"id": "F-001", "title": "echo", "description": "echo back", "status": "done"},
  {"id": "F-002", "title": "ping", "description": "ping", "status": "pending"}
]}
EOF
cat > requirements/REQ-2099-200/meta.yaml <<EOF
id: REQ-2099-200
title: PR3 沙箱
phase: definition
created_at: "2026-04-27 14:00:00"
branch: feat/reviewer-verdict-pr3-rollout
base_branch: develop
project: agentic-meta-engineering
services: []
feature_area: hooks
change_type: feature
affected_modules: []
EOF
```

### Step 2：3 类 reviewer 写入端到端

```bash
HEAD=$(git rev-parse --short=7 HEAD)

# definition（沿用 PR2 已通的 requirement-quality-reviewer fixture，仅替换 req）
python3 -c "
import json, sys
v = json.load(open('tests/fixtures/reviews/valid-definition-001.json'))
v['reviewed_commit'] = '$HEAD'
v['review_id'] = 'REV-REQ-2099-200-definition-001'
v['requirement_id'] = 'REQ-2099-200'
json.dump(v, sys.stdout)
" | bash scripts/save-review.sh --req REQ-2099-200 --phase definition --reviewer requirement-quality-reviewer

# outline-design
cat <<EOF | bash scripts/save-review.sh --req REQ-2099-200 --phase outline-design --reviewer outline-design-quality-reviewer
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2099-200-outline-design-001",
  "requirement_id": "REQ-2099-200",
  "phase": "outline-design",
  "reviewer": "outline-design-quality-reviewer",
  "reviewed_at": "$(date '+%Y-%m-%d %H:%M:%S')",
  "reviewed_commit": "$HEAD",
  "reviewed_artifacts": [
    {"path": "artifacts/outline-design.md", "sha256": "$(printf '0%.0s' {1..64})"},
    {"path": "artifacts/requirement.md", "sha256": "$(printf '0%.0s' {1..64})"}
  ],
  "conclusion": "approved",
  "score": 85,
  "dimensions": {
    "alignment_with_requirement": {"score": 90, "issues": []},
    "module_decomposition": {"score": 85, "issues": []},
    "tech_choice_rationale": {"score": 85, "issues": []},
    "scalability": {"score": 80, "issues": []},
    "integration_with_existing": {"score": 80, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null
}
EOF

# detail-design
cat <<EOF | bash scripts/save-review.sh --req REQ-2099-200 --phase detail-design --reviewer detail-design-quality-reviewer
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2099-200-detail-design-001",
  "requirement_id": "REQ-2099-200",
  "phase": "detail-design",
  "reviewer": "detail-design-quality-reviewer",
  "reviewed_at": "$(date '+%Y-%m-%d %H:%M:%S')",
  "reviewed_commit": "$HEAD",
  "reviewed_artifacts": [
    {"path": "artifacts/detailed-design.md", "sha256": "$(printf '0%.0s' {1..64})"},
    {"path": "artifacts/features.json", "sha256": "$(printf '0%.0s' {1..64})"},
    {"path": "artifacts/outline-design.md", "sha256": "$(printf '0%.0s' {1..64})"}
  ],
  "conclusion": "approved",
  "score": 85,
  "dimensions": {
    "consistency_with_outline": {"score": 90, "issues": []},
    "interface_completeness": {"score": 85, "issues": []},
    "data_model_soundness": {"score": 80, "issues": []},
    "sequence_correctness": {"score": 85, "issues": []},
    "feature_granularity": {"score": 85, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": null,
  "supersedes": null
}
EOF

# code F-001
cat <<EOF | bash scripts/save-review.sh --req REQ-2099-200 --phase code --reviewer code-quality-reviewer --scope feature_id=F-001
{
  "schema_version": "1.0",
  "review_id": "REV-REQ-2099-200-code-F-001-001",
  "requirement_id": "REQ-2099-200",
  "phase": "code",
  "reviewer": "code-quality-reviewer",
  "reviewed_at": "$(date '+%Y-%m-%d %H:%M:%S')",
  "reviewed_commit": "$HEAD",
  "reviewed_artifacts": [
    {"path": "artifacts/features.json", "sha256": "$(printf '0%.0s' {1..64})"}
  ],
  "conclusion": "approved",
  "score": 88,
  "dimensions": {
    "design_consistency": {"score": 90, "issues": []},
    "security": {"score": 90, "issues": []},
    "concurrency": {"score": 90, "issues": []},
    "complexity": {"score": 85, "issues": []},
    "error_handling": {"score": 85, "issues": []},
    "auxiliary_spec": {"score": 90, "issues": []},
    "performance": {"score": 85, "issues": []},
    "history_context": {"score": 90, "issues": []}
  },
  "required_fixes": [],
  "suggestions": [],
  "scope": {"feature_id": "F-001"},
  "supersedes": null
}
EOF
```

Expected：4 次写入全 `✓ 已写入 ...`；`requirements/REQ-2099-200/reviews/` 下有 4 个文件；`meta.yaml.reviews` 含 4 段。

### Step 3：gate 余 3 段端到端

```bash
# outline-design 切到 detail-design 应过
bash scripts/check-reviews.sh --req REQ-2099-200 --target-phase detail-design; echo "exit=$?"

# detail-design 切到 task-planning 应过
bash scripts/check-reviews.sh --req REQ-2099-200 --target-phase task-planning; echo "exit=$?"

# 切到 testing 触发 R007（F-001 done 已覆盖，F-002 pending 不计）
bash scripts/check-reviews.sh --req REQ-2099-200 --target-phase testing; echo "exit=$?"
```

Expected：3 个都 `exit=0`。

### Step 4：R007 反例（把 F-002 改 done 但无 review）

```bash
python3 -c "
import json
d = json.load(open('requirements/REQ-2099-200/artifacts/features.json'))
for f in d['features']:
    if f['id'] == 'F-002':
        f['status'] = 'done'
json.dump(d, open('requirements/REQ-2099-200/artifacts/features.json', 'w'), indent=2)
"
bash scripts/check-reviews.sh --req REQ-2099-200 --target-phase testing; echo "exit=$?"
```

Expected：`exit=1`，stderr 含 `R007: feature F-002 status=done 但 reviews.code.by_feature.F-002.latest 为空`。

### Step 5：D7-1 protect-branch 拦截试

```bash
bash .claude/hooks/tests/test-protect-reviews.sh
```

Expected：4 个 case 全过。

### Step 6：D7-2 pre-commit 三种情形（已在 Task 7 Step 2 跑过；这里复测一遍 sandbox 上下文）

```bash
git status   # 应该是无 staged 文件（沙箱目录还没 add）

# 故意 add 整个沙箱目录（meta.yaml + reviews/*.json + artifacts）
git add requirements/REQ-2099-200/
bash scripts/git-hooks/pre-commit; echo "exit=$?"
# 预期：通过——meta + reviews 同时 staged
git reset HEAD requirements/REQ-2099-200/

# 单独 add reviews 文件
git add requirements/REQ-2099-200/reviews/definition-001.json
bash scripts/git-hooks/pre-commit; echo "exit=$?"
# 预期：拒
git reset HEAD requirements/REQ-2099-200/
```

### Step 7：清理

```bash
rm -r requirements/REQ-2099-200
git status   # 应该是 nothing to commit
```

> 全部 step 通过后，PR3 才进入 Task 9 推分支。

---

## Task 9: 索引注册 + plan 状态切到执行中

**Files:**
- Modify: `context/team/engineering-spec/plans/INDEX.md`

- [ ] **Step 1: 在「进行中的 Plan」表格新增本 plan 行**

```markdown
| 2026-04-27 | Reviewer verdict 结构化 PR3（全量切换） | [2026-04-27-reviewer-verdict-pr3-rollout](2026-04-27-reviewer-verdict-pr3-rollout.md) | `feat/reviewer-verdict-pr3-rollout` | 🔄 执行中 |
```

- [ ] **Step 2: 跑 check-index 验证**

```bash
bash scripts/check-index.sh --strict
```

- [ ] **Step 3: Commit**

```
docs(plans): 注册 PR3（reviewer-verdict-pr3-rollout）+ 状态切到执行中
```

---

## Task 10: 最终回归 + 推分支 + 开 PR

- [ ] **Step 1: 三件套全套绿**

```bash
bash scripts/check-meta.sh --all --strict
bash scripts/check-index.sh --strict
bash scripts/check-sourcing.sh --all --strict
```

- [ ] **Step 2: 跑 PR2 通的 sandbox（不应被 PR3 改动破坏）**

挑历史已有 REQ（如 REQ-2026-001）跑：

```bash
bash scripts/check-reviews.sh --req REQ-2026-001 --target-phase completed; echo "exit=$?"
```

REQ-2026-001 当前应仍为 R001 fail（没 reviews 字段）——CI non-strict 兜住，PR4 才挂。

- [ ] **Step 3: 看 commit 历史**

```bash
git log --oneline develop..HEAD
```
Expected：约 8-9 个 commit（Task 2/3/4/5/6/7/8/9 各一个，Task 8 试点不 commit）

- [ ] **Step 4: 推分支**

```bash
git push -u origin feat/reviewer-verdict-pr3-rollout
```

- [ ] **Step 5: 开 PR**

```
gh pr create --base develop --title "feat: reviewer verdict 结构化 PR3（全量切换 + D7 写保护）" --body ...
```

PR body 要点：
- Summary：3 reviewer 切结构化 + gate 余 3 段切 check-reviews.sh + D7 双层写保护 + 沙箱端到端通过
- Out of Scope：PR4 升 strict + legacy: true 治理 + roadmap G3 done
- Test Plan：Task 8 全部 step 通过 + 三件套绿 + 4 个 protect 测试通过 + 3 个 pre-commit 情形通过

- [ ] **Step 6: 合入后由 PR merger 把本 plan `git mv` 到 `plans/history/`**（参照 PR1/PR2 模式）

---

## 验证清单（提交 PR 前必跑）

- [ ] `scripts/check-meta.sh --all --strict` → ✓
- [ ] `scripts/check-index.sh --strict` → ✓
- [ ] `scripts/check-sourcing.sh --all --strict` → ✓
- [ ] Task 8 沙箱 7 个 step 全过
- [ ] `.claude/hooks/tests/test-protect-reviews.sh` 4 case 全过
- [ ] pre-commit 3 个情形全过（同步通过 / 缺 reviews 拒 / 缺 meta 拒）
- [ ] 无遗留 `requirements/REQ-2099-*` 临时目录
- [ ] 4 reviewer Agent / gate-checklist / 2 hook 文件 7 处改动一致
- [ ] CI workflow 在 PR 上跑通（non-strict 不挂）

---

## 风险与回滚

| 风险 | 触发条件 | 缓解 / 回滚 |
|---|---|---|
| code-quality-reviewer 双输出 conclusion 不一致 | reviewer 主对话输出 vs 14 字段 verdict 漂移 | 写在 Step 5 的禁止行为里；test plan 沙箱跑一次 happy path；如真实 review 出现，立刻人工修两侧并补 spec |
| dimensions 8 维 vs 当前 8 checker 不完全对齐（auxiliary_spec / history_context 是辅助类，不一定每次有评价） | reviewer 给假分（issues=[] but score=90） | 接受这一妥协；critic 抽查机制（PR4 之后）能扫到 |
| protect-branch.sh 路径解析对 MultiEdit 多文件不稳 | MultiEdit 的 file_path 可能是多个 | 现版只看 file_path 单字段（足够 80% case）；如出现 MultiEdit 漏拦，PR3.1 单独修 |
| pre-commit awk + grep 误判 reviews: 段 diff | yaml 格式变化 / 缩进微调 | 沙箱 Step 2 反复跑；上线后第一周观察日志；如误判率高，改为 python3 + ruamel 解析对比 |
| 历史 REQ-2026-001 没 reviews 字段 → PR3 后 dev→testing 段 check-reviews 报 R001 | 当前是 completed，CI non-strict 跳过；活跃需求未来落到 PR4 治理 | 不改本 PR；roadmap PR4 含 legacy: true 一键豁免 |
| 整 PR 出问题 | 真实需求被卡住 | `git revert` PR；4 reviewer / gate / hook 全部回滚；PR1/PR2 基础设施仍在 |
