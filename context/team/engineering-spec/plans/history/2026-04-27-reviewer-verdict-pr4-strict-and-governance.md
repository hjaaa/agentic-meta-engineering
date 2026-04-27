# Reviewer Verdict 结构化 PR4 · CI 升 strict + 历史治理 · 实施计划

**Branch:** `feat/reviewer-verdict-pr4-strict-and-governance`
**Base:** `develop`（PR1 #36 / PR2 #38 / PR3 #40 已合入）
**Goal:** 收尾 reviewer-verdict 结构化体系——把 `.github/workflows/quality-check.yml` 中 `Check reviews` step 升 `--strict`（从 PR1 留下的 non-strict 兜底正式转为阻断式门禁）；引入 `legacy: true` REQ 级豁免标记并实现到 `meta-schema.yaml` / `check_reviews.py`；给历史需求 `REQ-2026-001` 标 `legacy: true` 让其豁免新校验；在 `roadmap.md` 把 G3 状态从 `brainstorming 中` 推到 `✅ done` 并补 C 升级触发信号。

**Scope（本 PR 必做）：**
- 扩 `context/team/engineering-spec/meta-schema.yaml`：把 `legacy` 加到 `optional_fields`（A1）
- 扩 `scripts/lib/check_reviews.py`：`main()` 入口检测 `meta.get('legacy') is True` → INFO 提示 + exit 0 短路（A2）
- 改 `requirements/REQ-2026-001/meta.yaml`：加 `legacy: true` + 注释说明（B）
- 改 `.github/workflows/quality-check.yml`：`Check reviews` step 加 `--strict`，step 名从 `(non-strict, PR1)` 改为 `(strict, PR4)`，移除 `|| echo ::warning::` 兜底（C）
- 改 `context/team/engineering-spec/roadmap.md`：G3 行状态切到 `✅ done`，时间戳标 2026-04-27；补一段 C 升级触发信号（D）
- 沙箱试点 `REQ-2099-NNN`：legacy 跳过链路 + 缺省正常校验 + 模拟 strict 跑 REQ-2026-001（E）
- 注册 plan 到 `plans/INDEX.md`（F）

**显式不做（Out of Scope）：**
- 不写 `scripts/mark-legacy.sh` 一键工具——当前活跃 REQ 只有 1 个（REQ-2026-001 已 completed），手工标即可；将来活跃 REQ 多了再加
- 不动 4 个 reviewer Agent / gate-checklist / hooks（PR3 已稳）
- 不引入 design-critic Agent（C5 决策维持现状；触发信号写入 roadmap 但不实施）
- 不批量回填活跃需求的 reviews 字段（REQ-2026-001 是 completed 唯一一例；其他活跃 REQ 后续按新流程产出即可）

**风险闸门：** strict 一开 CI 在所有 PR 上跑真阻断；唯一历史 REQ 已用 legacy 豁免。可独立回滚（`git revert` PR）；如紧急回滚仅去掉 `--strict` 即可恢复 PR3 行为。

---

## File Structure

```
.github/workflows/
  quality-check.yml                                    ← step 升 --strict（C）
context/team/engineering-spec/
  meta-schema.yaml                                     ← optional_fields 加 legacy（A1）
  roadmap.md                                           ← G3 标 done + C 升级触发信号（D）
  plans/
    2026-04-27-reviewer-verdict-pr4-strict-and-governance.md  ← 本文件
    INDEX.md                                           ← 注册本 plan（F）
requirements/REQ-2026-001/
  meta.yaml                                            ← 加 legacy: true（B）
scripts/lib/
  check_reviews.py                                     ← legacy 短路（A2）
```

不新增脚本、不动 reviewer Agent、不动 gate-checklist、不动 hooks（PR3 已稳定）。

---

## 关键决策（PR4 内）

### D-A · legacy 字段语义边界

- **legacy 只豁免 `check_reviews.py`**，不豁免 `check_meta.py` / `check_index.py` / `check_sourcing.py`——这些与 reviewer-verdict 体系无关，历史需求该过的还得过
- **legacy 是 boolean**：`true` / `false` / 缺省（视为 false）；不引入更复杂的 reason / scope 字段
- **legacy 标在 meta.yaml 顶层**，与现有 `id / title / phase / project` 同级——不嵌入到 `reviews:` 段（否则 PR1 设计的"reviews 段由脚本自动维护"边界被打破）
- **legacy 的应用粒度是「整个 REQ」**，不细分到 phase——一旦标了，所有 phase 切换 / submit / CI 都跳过 review 校验

### D-B · CI strict 升级时机

- 唯一可能挂的历史 REQ 是 REQ-2026-001（completed，无 reviews 字段，本来切到 completed 阶段时 R001 必然 fail）
- **本 PR 内顺序必须是**：`先实现 legacy 短路 → 再标 REQ-2026-001 → 最后升 strict`，否则 strict 一开 CI 立即红
- 顺序在 commit 历史里也要严格按这个顺序——避免 git bisect 时穿插绿/红边界

### D-C · CI shell 是否做 `legacy` 短路

- **不做**——legacy 跳过完全在 `check_reviews.py` 内部处理；shell 只调脚本、看退出码
- 理由：避免 yaml 解析逻辑分散在两处（设计文档 §6.4 给的示例 `legacy=$(yq '.legacy // false')` 反而是反模式——CI 又跑 yq 又跑 python，重复且易漂移）
- 副效果：legacy 跳过时 stdout 仍打 INFO 日志，CI 步骤里能看到「跳过哪个 REQ、为什么」

### D-D · roadmap G3 收尾粒度

- 把 G3 行的"状态"列改为 `✅ done`，并在末尾补一行 `落地 PR：#36 / #38 / #40 / 本 PR`
- §"推进原则" 段不动（已写"任何门禁强化必须先 non-strict 1~2 周"——现实是 PR1~PR3 跨度 1 天，但试点足以验证；如团队想严格遵守，PR4 可延后两周再合，本 PR 不卡这个）
- §"次级缺陷"段补一行 C 升级触发信号：「3 个或以上 review 出现『全维度 ≥ 80 分但实际推进时发现 blocker 漏报』→ 启动 C4（design-critic Agent）」（设计文档 §10）

---

## Task 1: 切分支 + 验证前置 baseline

**Files:** 无

- [ ] **Step 1: 已切到 `feat/reviewer-verdict-pr4-strict-and-governance`（基于 develop）**

```bash
git branch --show-current
```
Expected：`feat/reviewer-verdict-pr4-strict-and-governance`

- [ ] **Step 2: 验证 PR3 已合入**

```bash
git log --oneline develop -8 | grep -E "PR3|reviewer-verdict"
```
Expected：能看到 `27af77f feat: reviewer verdict 结构化 PR3`

- [ ] **Step 3: 三件套 baseline 绿**

```bash
bash scripts/check-meta.sh --all --strict
bash scripts/check-index.sh --strict
bash scripts/check-sourcing.sh --all --strict
```
Expected：3 个都 `✓ 无问题`

- [ ] **Step 4: 验证当前 CI step 行为**

```bash
grep -n "Check reviews" .github/workflows/quality-check.yml
```
Expected：第 37 行 `name: Check reviews (non-strict, PR1)`

- [ ] **Step 5: 验证 REQ-2026-001 当前在 strict 下会挂（这是 PR4 要解决的问题）**

```bash
bash scripts/check-reviews.sh --req REQ-2026-001 --target-phase completed --strict; echo "exit=$?"
```
Expected：`exit=1`（R001 fail：completed 需要 definition / outline-design / detail-design 三段 review，全部 latest=null）

---

## Task 2: 实现 legacy 字段（A · meta-schema + check-reviews）

**Files:**
- Modify: `context/team/engineering-spec/meta-schema.yaml`
- Modify: `scripts/lib/check_reviews.py`

- [ ] **Step 1: meta-schema 加 legacy**

在 `optional_fields` 段（当前第 129-130 行）扩展：

```yaml
optional_fields:
  - reviews
  - legacy   # PR4 新增；boolean，true 表示豁免 reviewer-verdict 校验（仅 check_reviews 跳过）
```

并在文件底部补一段说明（紧跟 reviews 段注释之后）：

```yaml
# ---------- legacy 字段（v2 新增，PR4 引入） ----------
# 用途：标记历史需求豁免 reviewer-verdict 体系的 review 校验
#   - 仅影响 scripts/lib/check_reviews.py 的入口短路
#   - 不影响 check_meta / check_index / check_sourcing
#   - 适用场景：completed 阶段的历史 REQ（PR3 之前产出，meta.yaml 无 reviews 字段）
# 语义：
#   - true：跳过所有 R001~R007 校验
#   - false / 缺省：正常校验
# 引入新字段后切忌泛滥使用；新增 REQ 必须走结构化 reviewer 通道。
```

- [ ] **Step 2: check_reviews.py 加 legacy 短路**

在 `main()` 函数 `try / except FileNotFoundError` 块之后、调用 `_r001_review_exists` 之前插入：

```python
# PR4: legacy=true 的需求豁免所有 review 校验（历史治理用）
if meta.get("legacy") is True:
    print(paint(f"ℹ️  {args.req} legacy=true，跳过 reviewer-verdict 校验（R001~R007）", "cyan"))
    return 0
```

不加 `--strict` 互动——legacy 是 REQ 级硬豁免，strict 也不应改其行为。

- [ ] **Step 3: 单测 legacy 短路**

先建一个最小 sandbox：

```bash
mkdir -p requirements/REQ-2099-300/{artifacts,reviews}
cat > requirements/REQ-2099-300/meta.yaml <<'EOF'
id: REQ-2099-300
title: PR4 legacy 短路 sandbox
phase: completed
created_at: "2026-04-27 15:00:00"
branch: feat/reviewer-verdict-pr4-strict-and-governance
base_branch: develop
project: agentic-meta-engineering
services: []
feature_area: hooks
change_type: feature
affected_modules: []
outcome: shipped
completed_at: "2026-04-27 15:00:00"
legacy: true
EOF

# 应短路成功
bash scripts/check-reviews.sh --req REQ-2099-300 --target-phase completed --strict
echo "exit=$?"
```
Expected：`exit=0`，stdout 含 `ℹ️  REQ-2099-300 legacy=true，跳过 reviewer-verdict 校验`

```bash
# 反例：去掉 legacy 行
sed -i.bak '/^legacy:/d' requirements/REQ-2099-300/meta.yaml
bash scripts/check-reviews.sh --req REQ-2099-300 --target-phase completed --strict
echo "exit=$?"
```
Expected：`exit=1`（R001 fail）

清理：

```bash
rm -r requirements/REQ-2099-300
```

- [ ] **Step 4: check-meta 不受影响**

```bash
# 重建 sandbox 验证 check-meta 不会因为 legacy 字段未声明而报错
mkdir -p requirements/REQ-2099-300/artifacts
cat > requirements/REQ-2099-300/meta.yaml <<'EOF'
id: REQ-2099-300
title: PR4 legacy meta 校验 sandbox
phase: completed
created_at: "2026-04-27 15:00:00"
branch: feat/reviewer-verdict-pr4-strict-and-governance
base_branch: develop
project: agentic-meta-engineering
services: []
feature_area: hooks
change_type: feature
affected_modules: []
outcome: shipped
completed_at: "2026-04-27 15:00:00"
legacy: true
EOF
bash scripts/check-meta.sh requirements/REQ-2099-300/meta.yaml --strict
echo "exit=$?"
rm -r requirements/REQ-2099-300
```
Expected：`exit=0`（legacy 在 optional_fields 内，不报 unknown field）

- [ ] **Step 5: Commit**

```
feat(legacy): 引入 REQ 级 legacy 标记 + check-reviews 短路

- meta-schema.yaml 把 legacy 加到 optional_fields，附用途说明
- check_reviews.py main() 入口检测 legacy=true → INFO 短路 exit 0
- 仅影响 reviewer-verdict 体系（R001~R007）；check-meta/index/sourcing 不受影响
- legacy 是 REQ 级硬豁免，--strict 也不互动（严格语义）
- 为 PR4 升 CI strict 与历史 REQ-2026-001 治理铺路
```

---

## Task 3: 给 REQ-2026-001 标 legacy: true（B）

**Files:**
- Modify: `requirements/REQ-2026-001/meta.yaml`

- [ ] **Step 1: 在 meta.yaml 顶层加 legacy 字段**

加在 `pr_url` / `pr_number` 段之后、`log_layout` 之前（保持流程组语义紧凑）：

```yaml
pr_number: 32
log_layout: split

# PR4 引入：本需求在 reviewer-verdict 结构化体系（PR1~PR3）之前已 completed，
# 无 reviews 字段；标 legacy=true 让 check-reviews.sh 跳过 R001~R007 校验。
# 新需求必须走结构化 reviewer 通道，不要复用此豁免。
legacy: true
```

- [ ] **Step 2: 验证 check-reviews 现在跳过**

```bash
bash scripts/check-reviews.sh --req REQ-2026-001 --target-phase completed --strict
echo "exit=$?"
```
Expected：`exit=0`，stdout 含 `ℹ️  REQ-2026-001 legacy=true，跳过`

- [ ] **Step 3: 验证 check-meta 仍正常通过（legacy 是 optional）**

```bash
bash scripts/check-meta.sh requirements/REQ-2026-001/meta.yaml --strict
echo "exit=$?"
```
Expected：`exit=0`

- [ ] **Step 4: Commit**

```
chore(REQ-2026-001): 标 legacy: true 豁免 reviewer-verdict 校验

- 本 REQ 在 PR1~PR3 结构化 reviewer 体系前已 completed
- 无 reviews 字段，CI strict 后会 R001 fail
- 标 legacy=true 让 check-reviews.sh 短路（PR4 已实现）
- 不回填历史 review JSON——已 ship 的不动
```

---

## Task 4: CI workflow 升 --strict（C）

**Files:**
- Modify: `.github/workflows/quality-check.yml`

- [ ] **Step 1: 改第 37-47 行 step**

```diff
-      - name: Check reviews (non-strict, PR1)
+      - name: Check reviews (strict, PR4)
         run: |
           for dir in requirements/*/; do
             req=$(basename "$dir")
             [ -f "$dir/meta.yaml" ] || continue
             phase=$(python3 -c "import yaml; print(yaml.safe_load(open('$dir/meta.yaml')).get('phase', ''))")
             [ -z "$phase" ] && continue
-            # PR1：不强制 strict；仅打日志，不挂 CI
-            bash scripts/check-reviews.sh --req "$req" --target-phase "$phase" || \
-              echo "::warning::check-reviews failed for $req (non-strict, PR1)"
+            # PR4：strict 模式真阻断；legacy=true 由 check-reviews.sh 内部短路（不在 shell 处理）
+            bash scripts/check-reviews.sh --req "$req" --target-phase "$phase" --strict
           done
```

- [ ] **Step 2: 用 act 或 GitHub Actions 上跑（推 PR 时验证）**

本地用 yamllint 兜底：

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/quality-check.yml'))" && echo "yaml OK"
```

- [ ] **Step 3: Commit**

```
feat(ci): 把 Check reviews step 升到 --strict（PR4）

- 替代 PR1 留下的 non-strict 兜底；CI 真阻断 R001~R007 fail
- legacy=true 的 REQ 由 check-reviews.sh 内部短路 INFO，不在 shell 处理
- 历史 REQ-2026-001 已在前一 commit 标 legacy；CI 应能在 develop 跑通
- 紧急回滚：去掉 --strict 即可恢复 PR3 行为
```

---

## Task 5: roadmap G3 标 done（D）

**Files:**
- Modify: `context/team/engineering-spec/roadmap.md`

- [ ] **Step 1: 改第 140 行 G3 状态**

```diff
-| G3 | **Reviewer verdict 仅在主对话，未持久化为机器可读结构；阶段切换"verdict ≠ rejected"靠 LLM 自觉** | 高——评审形同虚设 | **brainstorming 中** |
+| G3 | **Reviewer verdict 仅在主对话，未持久化为机器可读结构；阶段切换"verdict ≠ rejected"靠 LLM 自觉** | 高——评审形同虚设 | ✅ done（PR #36 / #38 / #40 / 本 PR；2026-04-27） |
```

- [ ] **Step 2: §"次级缺陷" 段补 C 升级触发信号**

在该段末尾追加：

```markdown
- C5 → C4 升级触发信号（PR4 沉淀；设计文档 §10）：3 个或以上 review 出现"全维度 ≥ 80 分但实际推进时发现 blocker 漏报"→ 启动 C4（design-critic Agent）；当前不实施，依靠 reviewer 自评 + CR-1~CR-6 schema 兜底
```

- [ ] **Step 3: Commit**

```
docs(roadmap): G3 标 ✅ done + 补 C5→C4 升级触发信号

- G3 状态从 brainstorming 中切到 done（PR1~PR4 全链落地）
- 次级缺陷段补 C5→C4 触发信号（设计文档 §10 决策）
- reviewer-verdict 结构化体系收尾
```

---

## Task 6: 沙箱端到端验证（E）

**目的：** 端到端验证 legacy 跳过链路 / strict 真阻断 / 历史 REQ 治理。

### Step 1：legacy 短路的正反例（在 Task 2 Step 3-4 已跑过；这里复测保证 Task 4 升 strict 后不退化）

```bash
mkdir -p requirements/REQ-2099-400/artifacts
cat > requirements/REQ-2099-400/meta.yaml <<'EOF'
id: REQ-2099-400
title: PR4 端到端 sandbox（legacy=true）
phase: completed
created_at: "2026-04-27 15:30:00"
branch: feat/reviewer-verdict-pr4-strict-and-governance
base_branch: develop
project: agentic-meta-engineering
services: []
feature_area: hooks
change_type: feature
affected_modules: []
outcome: shipped
completed_at: "2026-04-27 15:30:00"
legacy: true
EOF

# 1) legacy=true 短路
bash scripts/check-reviews.sh --req REQ-2099-400 --target-phase completed --strict
echo "exit=$? (expect 0, INFO 跳过)"

# 2) legacy=false 应 R001 fail
sed -i.bak 's/^legacy: true/legacy: false/' requirements/REQ-2099-400/meta.yaml
bash scripts/check-reviews.sh --req REQ-2099-400 --target-phase completed --strict
echo "exit=$? (expect 1, R001 fail)"

# 3) legacy 字段不存在 应 R001 fail
sed -i.bak '/^legacy:/d' requirements/REQ-2099-400/meta.yaml
bash scripts/check-reviews.sh --req REQ-2099-400 --target-phase completed --strict
echo "exit=$? (expect 1, R001 fail)"

# 清理
rm -r requirements/REQ-2099-400
```

### Step 2：模拟 CI workflow 全 REQ 循环（按 Task 4 改后的 shell 走一遍）

```bash
for dir in requirements/*/; do
  req=$(basename "$dir")
  [ -f "$dir/meta.yaml" ] || continue
  phase=$(python3 -c "import yaml; print(yaml.safe_load(open('$dir/meta.yaml')).get('phase', ''))")
  [ -z "$phase" ] && continue
  echo "=== $req (phase=$phase) ==="
  bash scripts/check-reviews.sh --req "$req" --target-phase "$phase" --strict
  echo "  exit=$?"
done
```

Expected：唯一在跑的 REQ-2026-001 应短路 INFO + exit=0；其他若有沙箱残留先清干净。

### Step 3：清理验证

```bash
ls requirements/ | grep REQ-2099 || echo "无残留 ✓"
git status
```

Expected：无 `REQ-2099-*`；git status 干净（或仅 task 1-5 改的文件）。

---

## Task 7: 注册 plan 到 INDEX.md（F）

**Files:**
- Modify: `context/team/engineering-spec/plans/INDEX.md`

- [ ] **Step 1: 在「进行中的 Plan」表格新增本 plan 行**

```markdown
| 2026-04-27 | Reviewer verdict 结构化 PR4（CI 升 strict + 历史治理） | [2026-04-27-reviewer-verdict-pr4-strict-and-governance](2026-04-27-reviewer-verdict-pr4-strict-and-governance.md) | `feat/reviewer-verdict-pr4-strict-and-governance` | 🔄 执行中 |
```

- [ ] **Step 2: check-index 验证**

```bash
bash scripts/check-index.sh --strict
echo "exit=$?"
```
Expected：`exit=0`

- [ ] **Step 3: Commit**

```
docs(plans): 注册 PR4（reviewer-verdict-pr4-strict-and-governance）+ 状态切到执行中
```

---

## Task 8: 三件套全套绿 + 推分支 + 开 PR

- [ ] **Step 1: 三件套全套绿**

```bash
bash scripts/check-meta.sh --all --strict
bash scripts/check-index.sh --strict
bash scripts/check-sourcing.sh --all --strict
```
Expected：全 `✓ 无问题`

- [ ] **Step 2: 模拟 CI workflow 关键 step**

```bash
for dir in requirements/*/; do
  req=$(basename "$dir")
  [ -f "$dir/meta.yaml" ] || continue
  phase=$(python3 -c "import yaml; print(yaml.safe_load(open('$dir/meta.yaml')).get('phase', ''))")
  [ -z "$phase" ] && continue
  bash scripts/check-reviews.sh --req "$req" --target-phase "$phase" --strict
done
echo "all REQ check-reviews exit=$?"
```
Expected：全 `exit=0`（含 REQ-2026-001 legacy 短路）

- [ ] **Step 3: commit 历史检查**

```bash
git log --oneline develop..HEAD
```
Expected：约 6 个 commit（Task 2/3/4/5/7 各 1 + Task 1 plan 文件 1）

- [ ] **Step 4: 推分支**

```bash
git push -u origin feat/reviewer-verdict-pr4-strict-and-governance
```

- [ ] **Step 5: 开 PR**

PR title：`feat: reviewer verdict 结构化 PR4（CI 升 strict + 历史治理）`

PR body 要点：
- Summary：legacy 字段实现 + REQ-2026-001 标 legacy + CI Check reviews 升 strict + roadmap G3 done
- Out of Scope：mark-legacy.sh 一键工具 / 批量回填活跃需求 / design-critic Agent
- Test Plan：Task 6 沙箱 3 个情形（true 短路 / false fail / 缺省 fail）+ 全 REQ CI 循环模拟通过 + 三件套绿
- 关联：闭合 G3；落地 PR #36 / #38 / #40 / 本 PR

- [ ] **Step 6: 合入后由 PR merger 把本 plan `git mv` 到 `plans/history/`**（参照 PR1/PR2/PR3 模式）

---

## 验证清单（提交 PR 前必跑）

- [ ] `scripts/check-meta.sh --all --strict` → ✓
- [ ] `scripts/check-index.sh --strict` → ✓
- [ ] `scripts/check-sourcing.sh --all --strict` → ✓
- [ ] `scripts/check-reviews.sh --req REQ-2026-001 --target-phase completed --strict` → exit=0 + INFO
- [ ] Task 6 Step 1 三个情形全过（true 短路 / false fail / 缺省 fail）
- [ ] Task 6 Step 2 全 REQ 循环 exit=0
- [ ] 无遗留 `requirements/REQ-2099-*` 临时目录
- [ ] CI workflow yaml 解析合法（python3 yaml.safe_load）
- [ ] roadmap G3 行展示 ✅ done + 引用 4 个 PR

---

## 风险与回滚

| 风险 | 触发条件 | 缓解 / 回滚 |
|---|---|---|
| 升 strict 后某个忘了治理的活跃 REQ 突然挂 CI | 当前 develop 上仅 REQ-2026-001 是历史 REQ，已治理；未来若有遗漏 | 临时给该 REQ 标 legacy=true 兜住 → 后续按需求生命周期补 reviewer-verdict 落盘 |
| legacy=true 被滥用（新 REQ 也标） | reviewer / 主对话偷懒 | meta-schema 注释明确"新需求必须走结构化 reviewer 通道"；code review 时人工把关；后续可加 check_meta 规则：phase < completed 且 legacy=true → WARN |
| check_reviews.py 的 legacy 短路顺序错（应在 _load_meta 之后立刻判，否则 R001 已先跑） | 实现 bug | Task 2 Step 3 沙箱测试覆盖；strict 模式下手测必跑 |
| CI step 改后 yaml 缩进 / shell 引号错 | 编辑失误 | Task 4 Step 2 用 python3 yaml.safe_load 兜底；提 PR 后看 GitHub Actions 第一次跑 |
| roadmap G3 标 done 后被人重新打开 | 后续真发现"3 个 review 全维度虚高" | §次级缺陷的 C5→C4 触发信号已写明；按信号开新 PR 即可，不影响本 PR |

---

## 关联

- 设计文档：[`specs/2026-04-27-reviewer-verdict-structuring-design.md`](../specs/2026-04-27-reviewer-verdict-structuring-design.md) §7 PR4 行
- 前置 PR：#36（PR1 基础设施）/ #38（PR2 试点）/ #40（PR3 全量切换）
- 关联 roadmap 项：G3
