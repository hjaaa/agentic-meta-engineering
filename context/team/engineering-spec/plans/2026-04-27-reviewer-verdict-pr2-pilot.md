# Reviewer Verdict 结构化 · PR2 试点 · 实施计划

**Branch:** `feat/reviewer-verdict-pr2-pilot`
**Base:** `develop`（PR1 已合入；PR #37 归档 PR 合入后 rebase 一次）
**Goal:** 在 PR1 落地的基础设施之上，把 **第一个 reviewer Agent**（`requirement-quality-reviewer`）切到结构化 verdict 通道；把 `gate-checklist.md` 中 `definition → tech-research` 段从"读文本"改为"跑脚本"；把 `/requirement:next` 执行体从"对照清单"改为"逐条跑命令"；用真实需求跑通 write→read→drift 全链路，作为 PR3 全量切换前的金丝雀。

**Scope（本 PR 必做）：**
- 改 `.claude/agents/requirement-quality-reviewer.md` 输出契约（A）
- 改 `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md` 第 23-32 行 `definition → tech-research` 段（B）
- 改 `.claude/skills/managing-requirement-lifecycle/SKILL.md` + `.claude/commands/requirement/next.md` 的 next 执行体描述（C）
- 试点验证：临时 REQ 走 phase 1→2，跑通 write→read→drift（D）

**显式不做（Out of Scope，留给 PR3/4）：**
- 不改其他 3 个 reviewer Agent（design / detail-design / code-quality）
- 不改 `gate-checklist.md` 其他段（outline → detail / detail → task / dev → testing 仍走旧文本）
- 不加 `protect-branch` 禁写规则
- 不加 `pre-commit` diff 校验（D7 第二道防线）
- 不升 CI `--strict`
- 不写 `legacy: true` 治理

**风险闸门：** 仅 1 个 Agent 切换；其他 3 reviewer 行为零变化；CI 仍 non-strict。可独立回滚（`git revert` PR）。

---

## File Structure

```
.claude/
  agents/
    requirement-quality-reviewer.md          ← 改输出契约
  skills/managing-requirement-lifecycle/
    SKILL.md                                  ← 改 next 执行体表述
    reference/gate-checklist.md              ← 改 definition → tech-research 段
  commands/requirement/
    next.md                                   ← 改 next 委托表述
context/team/engineering-spec/plans/
  2026-04-27-reviewer-verdict-pr2-pilot.md  ← 本文件
  INDEX.md                                  ← 注册本 plan
```

不新增脚本（PR1 已沉淀 `save-review.sh` / `check-reviews.sh`）；不动 `meta-schema.yaml`（PR1 已加 `reviews` 顶层字段）。

---

## Task 1: 切分支 + 验证前置

**Step 1.1**: 已在 `feat/reviewer-verdict-pr2-pilot` 分支（基于 develop，PR1 已合入）。

**Step 1.2**: 验证 PR1 基础设施可用，跑：
```bash
ls scripts/save-review.sh scripts/check-reviews.sh context/team/engineering-spec/review-schema.yaml
bash scripts/check-reviews.sh --help 2>&1 | head -5  # 至少能加载
bash scripts/save-review.sh --help 2>&1 | head -5
```

**Step 1.3**: 跑一次三件套确认 baseline 绿：
```bash
bash scripts/check-meta.sh --all --strict
bash scripts/check-index.sh --strict
bash scripts/check-sourcing.sh --all --strict
```

---

## Task 2: 改 `requirement-quality-reviewer.md` 输出契约（A）

**改动点：** `.claude/agents/requirement-quality-reviewer.md` 第 21-41 行「输出契约」段。

**目标：** 不删除 JSON schema 描述（reviewer 仍要组装该 JSON），但**追加一段强制执行步骤**——必须把 JSON 通过 stdin 传给 `save-review.sh`，而**不是直接打印给主对话**。

**新增内容（追加在「输出契约」之后、「行为准则」之前）：**

```markdown
## 输出方式（强制）

完成评审、组装好上述 JSON 后，**必须通过 `save-review.sh` 写入**，而不是把 JSON 文本贴回主对话：

\`\`\`bash
bash scripts/save-review.sh \
  --req <REQ-ID> \
  --phase definition \
  --reviewer requirement-quality-reviewer \
  <<'EOF'
{ ...你的 verdict JSON... }
EOF
\`\`\`

- `<REQ-ID>` 从输入参数 `requirement_md_path` 中解析（例如 `requirements/REQ-2026-007/artifacts/requirement.md` → `REQ-2026-007`）
- 退出码非 0：按 stderr 提示修正 JSON（违反 CR-1~CR-6 之一）后重提，**不要把错误 JSON 反给主对话当结论**
- 退出码 0：仅向主对话回报「verdict 已写入 `requirements/<REQ-ID>/reviews/<filename>.json`，conclusion=<...>」一行确认；详细 JSON 主对话不再读
```

**对应 commit message：**
```
feat(requirement-quality-reviewer): 切到结构化 verdict 通道（save-review.sh）

- 输出契约追加「强制走 save-review.sh」段
- reviewer 不再把 JSON 文本贴回主对话，主对话只读「conclusion 已写入」一行确认
- 配合 PR1 的 R001-R007 校验，verdict 进入持久化 + drift 检测体系
```

---

## Task 3: 改 `gate-checklist.md` definition → tech-research 段（B）

**改动点：** `.claude/skills/managing-requirement-lifecycle/reference/gate-checklist.md` 第 23-32 行。

**当前文本：**
```markdown
## definition → tech-research

- [ ] `artifacts/requirement.md` 存在
- [ ] `bash scripts/check-sourcing.sh --requirement <REQ-ID>` 退出码 = 0
  - 依据 ...
- [ ] 需求评审结论 ≠ `rejected`（由 `requirement-quality-reviewer` Agent 产生，Phase 2 可先跳过此校验，标记 "reviewer pending"）
- [ ] 所有"待用户确认"项已处理（无 `[待用户确认]` 遗留标记）
```

**改为：**
```markdown
## definition → tech-research

- [ ] `artifacts/requirement.md` 存在
- [ ] `bash scripts/check-sourcing.sh --requirement <REQ-ID>` 退出码 = 0
  - 依据 ...（保持原说明）
- [ ] `bash scripts/check-reviews.sh --req <REQ-ID> --target-phase tech-research` 退出码 = 0
  - 依据 PR1 落地的 R001~R007 规则——R001 兜底：phase=definition 之后切阶段必须有 `requirement-quality-reviewer` 的 latest verdict
  - R003 规则：verdict.conclusion ≠ `rejected`（rejected 直接阻断切换）
  - R005 规则：requirement.md 自评审后未变更（drift 兜底）
  - 该校验取代旧版「需求评审结论 ≠ rejected（Phase 2 可先跳过）」——PR2 起不再允许"reviewer pending"逃生口
- [ ] 所有"待用户确认"项已处理（无 `[待用户确认]` 遗留标记）
```

**关键变化：**
- 删除「Phase 2 可先跳过此校验」的逃生口——这是 reviewer verdict 结构化的核心动机
- 该条改为脚本调用，主 Agent 必须真跑一次（配合 Task 4 的执行体改造）

**对应 commit message：**
```
feat(gate-checklist): definition → tech-research 段切到 check-reviews.sh

- 「需求评审结论 ≠ rejected」改为 `scripts/check-reviews.sh ... --target-phase tech-research` 调用
- 移除「Phase 2 可先跳过」逃生口
- 其他 3 段（outline/detail/dev→testing）维持原样，留给 PR3 统一切换
```

---

## Task 4: 改 `/requirement:next` 执行体表述（C）

**改动点 C-1：** `.claude/commands/requirement/next.md` 第 14-23 行「委托」段。

**当前文本（关键两行）：**
```markdown
- 查 `reference/gate-checklist.md` 中"当前阶段 → 下一阶段"段的全部检查项
- 依次执行每条检查
- 任一失败 → 列出缺口并终止（不修改 phase）
```

**改为：**
```markdown
- 查 `reference/gate-checklist.md` 中"当前阶段 → 下一阶段"段的全部检查项
- **逐条执行**：
  - 凡是 `- [ ] bash scripts/...` 形式的检查项，**必须用 Bash 工具真实执行该命令**并以退出码判定通过/失败，不允许"看清单自答通过"
  - 凡是 `- [ ] <文件> 存在` / `- [ ] <字段> 非空` 形式的，必须 Read 或 grep 验证，不允许凭印象
- 任一失败 → 列出缺口（包含失败命令的 stderr 关键行）并终止（不修改 phase）
```

**改动点 C-2：** `.claude/skills/managing-requirement-lifecycle/SKILL.md` 第 15 行 + 第 24 行的 next 流程表述。

跟进同样的措辞修正：把"门禁校验（见 gate-checklist.md）"扩成"逐条执行 gate-checklist.md 中的命令型检查项（凡 `bash scripts/...` 形式必须真跑）"。具体改法在实现时按上下文微调。

**对应 commit message：**
```
feat(next): 把门禁执行体从「对照清单」改为「逐条跑命令」

- next.md 委托段明确：bash 形式检查项必须真实执行 Bash 工具
- SKILL.md next 流程同步措辞修正
- 配合 Task 3 的 check-reviews.sh 接入，关闭 LLM 自答通过的逃生口
```

---

## Task 5: 试点验证 · write→read→drift 全链（D）

**目的：** 不依赖现有需求（避免污染历史 REQ），用一个临时需求跑通新链路。

**Step 5.1**: 临时建 REQ-2099-pr2-pilot

```bash
mkdir -p requirements/REQ-2099-pr2-pilot/{artifacts,reviews,notes}
cat > requirements/REQ-2099-pr2-pilot/meta.yaml <<'YAML'
id: REQ-2099-pr2-pilot
title: PR2 试点需求（write→read→drift 验证）
phase: definition
branch: feat/reviewer-verdict-pr2-pilot
created_at: 2026-04-27
business_value: 验证 PR2 试点链路；不进入正式需求生命周期
acceptance_criteria:
  - reviewer 调 save-review.sh 写入成功
  - check-reviews.sh 能在切阶段时读到 verdict
  - 修改 requirement.md 后 R005 drift 触发
YAML

cat > requirements/REQ-2099-pr2-pilot/artifacts/requirement.md <<'MD'
# 试点需求
（来源：plans/2026-04-27-reviewer-verdict-pr2-pilot.md）

## 业务价值
验证 PR2 链路。

## 验收标准
- write 成功
- read 成功
- drift 触发
MD
```

**Step 5.2**: write 验证

模拟 reviewer 输出，跑：
```bash
bash scripts/save-review.sh \
  --req REQ-2099-pr2-pilot \
  --phase definition \
  --reviewer requirement-quality-reviewer \
  <<'EOF'
{
  "conclusion": "approved",
  "score": 88,
  "dimensions": {
    "completeness": {"score": 90, "issues": []},
    "consistency": {"score": 85, "issues": []},
    "traceability": {"score": 90, "issues": []},
    "clarity": {"score": 88, "issues": []},
    "testability": {"score": 85, "issues": []},
    "business_rationale": {"score": 90, "issues": []}
  },
  "project_specific_issues": ["项目索引未声明特殊约束"],
  "required_fixes": [],
  "suggestions": []
}
EOF
```

**预期：** 退出码 0；`requirements/REQ-2099-pr2-pilot/reviews/` 下生成 JSON；`meta.yaml.reviews.requirement.latest` 指向该 JSON。

**Step 5.3**: read 验证

```bash
bash scripts/check-reviews.sh --req REQ-2099-pr2-pilot --target-phase tech-research
```

**预期：** 退出码 0（R001 通过：reviewer 已写入；R003 通过：approved≠rejected；R005 通过：requirement.md 未变更）。

**Step 5.4**: drift 验证

```bash
echo "## 新增章节" >> requirements/REQ-2099-pr2-pilot/artifacts/requirement.md
bash scripts/check-reviews.sh --req REQ-2099-pr2-pilot --target-phase tech-research
```

**预期：** 退出码非 0；stderr 含 R005 信息（artifacts/requirement.md hash 变化，要求 reviewer 重跑）。

**Step 5.5**: rejected 验证

重写 review JSON（conclusion=rejected）再跑 save → check：
```bash
# save-review.sh 应内部 CR-? 校验 rejected 必须有 required_fixes 非空（按 PR1 schema）
# check-reviews.sh 应触发 R003，退出码非 0
```

**Step 5.6**: 清理

```bash
rm -rf requirements/REQ-2099-pr2-pilot
```

**全部 step 通过后**，PR2 才能进入 Task 6。

---

## Task 6: 索引注册 + plan 状态切到执行中

**Step 6.1**: 在 `context/team/engineering-spec/plans/INDEX.md` "进行中的 Plan" 表格里新增一行：
```markdown
| 2026-04-27 | Reviewer verdict 结构化 PR2（试点） | [2026-04-27-reviewer-verdict-pr2-pilot](2026-04-27-reviewer-verdict-pr2-pilot.md) | `feat/reviewer-verdict-pr2-pilot` | 🔄 执行中 |
```

**Step 6.2**: 跑 `bash scripts/check-index.sh --strict` 确认 INDEX 引用合法。

**Step 6.3**: commit
```
docs(plans): 注册 PR2（reviewer-verdict-pr2-pilot）+ 状态切到执行中
```

---

## Task 7: 最终回归 + 推分支 + 开 PR

**Step 7.1**: 全套 CI 校验
```bash
bash scripts/check-meta.sh --all --strict
bash scripts/check-index.sh --strict
bash scripts/check-sourcing.sh --all --strict
bash scripts/check-reviews.sh --req REQ-2026-001 --target-phase completed  # PR1 接入后应仍为 warning（non-strict）
```

**Step 7.2**: 推分支
```bash
git push -u origin feat/reviewer-verdict-pr2-pilot
```

**Step 7.3**: 开 PR
```
gh pr create --base develop --title "feat: reviewer verdict 结构化 PR2（试点 · requirement-quality-reviewer）" --body ...
```

PR body 关键段：
- Summary：1 个 reviewer 切换 + gate 1 段切换 + next 执行体加固 + 试点链路通过
- Out of Scope：PR3 全量切换 / D7 写保护 / PR4 strict
- Test Plan：5 项试点 step 全过 + 三件套 CI 绿

**Step 7.4**: 合入后由 PR merger 把本 plan `git mv` 到 `plans/history/` 并在历史 INDEX 追加 PR2 行（参照 PR #37 模式）。

---

## 验证清单（提交 PR 前必跑）

- [ ] `scripts/check-meta.sh --all --strict` → ✓
- [ ] `scripts/check-index.sh --strict` → ✓
- [ ] `scripts/check-sourcing.sh --all --strict` → ✓
- [ ] Task 5 全部 5 个 step 退出码符合预期
- [ ] 无遗留 `requirements/REQ-2099-*` 临时目录
- [ ] reviewer-quality-reviewer.md / gate-checklist.md / next.md / SKILL.md 4 处文本改造一致
- [ ] CI workflow 在 PR 上跑通

---

## 风险与回滚

| 风险 | 触发条件 | 回滚 |
|---|---|---|
| reviewer Agent 改了输出契约后忘记调 save-review.sh | LLM 漏读输出方式段 | R001 兜底——切阶段时 latest=null 直接 ERROR；reviewer 不调 → 切不了阶段 → 主对话被迫回头让 reviewer 重跑 |
| 主 Agent 仍然"对照清单"自答通过 bash 项 | next.md 措辞被 LLM 忽略 | 试点期由用户人工抽查；如规律性发生，PR3 把执行体改造再加强（例如 next 流程改成 Skill 内置 bash 循环） |
| 试点 REQ-2099 没清理干净 | Step 5.6 漏跑 | `git status` 会显示，CI check-meta 也会报错（id 不在 schema 范围）；PR 不能合 |
| C 项（执行体改造）和 B 项（gate 文本改造）不同步落地 | 分两个 commit 但只合一个 | 同一 PR 内提交，CI 整体把关 |
| 整 PR 出问题 | 试点期间真实需求被卡住 | `git revert` PR 即可——其他 3 reviewer 与 gate 6 段未改 |
