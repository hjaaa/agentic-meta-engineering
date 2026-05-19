---
id: 20260519-remove-human-signoff
phase: detail-design
created_at: 2026-05-19T03:50:00Z
---

# 详细设计 · 20260519-remove-human-signoff

> 权威单源同 requirement.md（来源：requirements/20260519-remove-human-signoff/plan.md:62）。本文档把 outline-design 的 10 个 feature 落实为接口契约 + 数据结构 + features.json 的 hash 锚点。

## 1. 接口契约的退化点（按 feature 列）

### F-001 review-schema.yaml 删除点（接口契约）

**删除前接口**（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:85）：

```yaml
enums:
  signoff_decision: [approved, approved-trivial, rejected, ...]
  signoff_source:   [user, ai, ...]

fields:
  human_signoff:
    type: object
    properties: { decision, source, signed_by, signed_at, ... }
```

**删除后接口**：仅保留 `review_id` / `conclusion` / `score` / `reviewed_artifacts` / `required_fixes` / `suggestions` / `dimensions` 等机器结论字段（不含 human_signoff）。CR-1 / CR-4 中保留的子条件仅校验：required_fixes 非空 → conclusion ∈ {needs_attention, blocked}；score < 阈值 → conclusion ≠ looks_clean；blocker issue → conclusion = blocked（来源：docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:94）。

### F-002 check_reviews.py / save_review.py 函数签名变更

**删除的公开符号**：
- `check_reviews.SIGNOFF_PASS`（常量）
- `check_reviews.is_signed_off(verdict: dict) -> bool`（函数）
- `save_review` CLI 子命令 `signoff`（argparse subparser；含 --rev-id / --decision / --trivial 等 flag）

**保留的公开符号**：`save_review.save(...)` / `check_reviews.run_rules(...)`（接口签名不变；内部判定逻辑去签字依赖）。

**外部调用方更新**：本仓库内调用方（`scripts/gates/plugins/review_verdict.py` / `review_verdict_ci.py` / `.claude/skills/feature-lifecycle-manager` 等）由 F-004 / F-005 同步更新。

### F-003 文件级删除（无接口意义）

7 项文件整删除（详 features.json F-003.touches）。

### F-006 workflow yaml 节点 ID 改名

```
旧 ID                              新 ID
────────                            ────────
req-signoff                  →     req-confirm
tech-research-signoff        →     tech-research-confirm
outline-design-signoff       →     outline-design-confirm
detail-design-signoff        →     detail-design-confirm
task-signoff                 →     task-confirm
test-final-signoff           →     test-final-confirm
pr-merged-gate               →     pr-merged-gate（不动）
```

依赖链替换：所有 `depends_on:` 中的旧 ID 同步替换。

### F-009 ID 校验扩展（公开 helper）

**新增公开符号**（在 `scripts/lib/requirement_naming.py`）：

```python
def is_new_requirement_key(key: str) -> bool:
    """识别 YYYYMMDD-<slug>[-NN] 新格式 key。"""
    return bool(_NEW_REQUIREMENT_KEY_RE.match(key))
```

**修改的入口**：
- `scripts/gates/run.py:127` `_REQ_ID_PATTERN` 删；`_validate_requirement_id` 函数体改为：

```python
def _validate_requirement_id(req_id: str) -> bool:
    from scripts.lib.requirement_naming import is_legacy_requirement_key, is_new_requirement_key
    return is_legacy_requirement_key(req_id) or is_new_requirement_key(req_id)
```

- `scripts/gates/plugins/features_schema.py:106` 错误文案同步反映新规则
- `context/team/engineering-spec/features-schema.yaml` 中 `format.requirement_id` 扩为 `'^(REQ-\d{4}-\d{3}|\d{8}-[a-z0-9]+(?:-[a-z0-9]+)*(?:-\d{2})?)$'`

## 2. 数据结构变更

### 2.1 review JSON schema 字段集

```
变更前                            变更后
───────                            ───────
review_id                          review_id
conclusion                         conclusion
score                              score
reviewed_artifacts                 reviewed_artifacts
required_fixes                     required_fixes
suggestions                        suggestions
dimensions                         dimensions
human_signoff   ← 本期删除         （字段消失）
```

迁移策略（F-008）：active 需求做机械字段删除；archived completed 需求保留字段 + schema 改"忽略未知字段"——本期 `check_reviews` 已不再读取 `human_signoff`，archived JSON 的多余字段不影响新 gate（C-2 工作假设）。

### 2.2 features.json schema requirement_id 字段

- 当前 regex：`'^REQ-\d{4}-\d{3}$'`
- 扩展为：`'^(REQ-\d{4}-\d{3}|\d{8}-[a-z0-9]+(?:-[a-z0-9]+)*(?:-\d{2})?)$'`
- 兼容两种格式；旧需求 features.json 仍合法

### 2.3 workflow run-state.jsonl 节点 ID 集合

旧 jsonl 中 `*-signoff` 节点 ID 在新 yaml 中不存在，但已 completed 的 jsonl 不再回放，无 break 面（C-3 工作假设；详 outline-design §选型 3）。

## 3. 时序图：代码审查后软确认（场景 1）

```
User                main agent           reviewer agents         feature-lifecycle-manager
 │                     │                       │                          │
 │ /code-review        │                       │                          │
 │ ─────────────────► │                       │                          │
 │                     │  scope + dispatch     │                          │
 │                     │ ───────────────────► │                          │
 │                     │                       │  8 checker + critic +    │
 │                     │                       │  judge 并行 + 串行       │
 │                     │  ◀──── verdict.json   │                          │
 │                     │       Markdown 报告   │                          │
 │                     │  （不含 human_signoff）│                          │
 │  ◀─── 报告展示 + 提示                       │                          │
 │       approve / reject ?                    │                          │
 │                                             │                          │
 │  approve            │                       │                          │
 │ ─────────────────► │                       │                          │
 │                     │  根据 conclusion 推进  │                          │
 │                     │ ───────────────────────────────────────────────► │
 │                     │                                                  │
 │                     │              ├─ looks_clean + no required → done│
 │                     │              ├─ needs_attention + 显式接受 → done│
 │                     │              └─ blocked → fail-closed            │
 │  ◀─ 状态反馈        │                                                  │
```

无 verdict 字段写入；软确认仅作用于当前流程动作。

## 4. 实施顺序（与 features.json depends_on_features 对齐）

```
F-001 (schema) ──► F-002 (judge)   ──► F-003 (delete files)
                                  ──► F-004 (plugins)
                                  ──► F-005 (skills/agent)
F-001 ────────► F-008 (data migration)
                                                                ──► F-007 (docs)
F-006 (workflow yaml)  ─────────────────────────────────────► F-007 (docs)
F-009 (D-001) 与主链解耦                                       ──► F-010 (testing)
F-007 / F-009 全完成 ──────────────────────────────────────► F-010 (testing)
```

每个 feature 完成即触发 /code-review scoped 到该 feature；done 转换前需用户软确认（不再 sign-off）。

## 5. 验收 hash 锚点

本文件 + features.json 视为 detail-design 阶段的 hash 锚点对：

- `requirements/20260519-remove-human-signoff/artifacts/detailed-design.md` ← 本文件
- `requirements/20260519-remove-human-signoff/artifacts/features.json`

任何后续 review 的 `reviewed_artifacts` 必须包含上述两文件路径与 hash；development 阶段开始后任何对 features.json 的修改都触发 hash drift，需要新一轮 detail-design reviewer 评审。

## 6. 开放问题最终决策

| ID | 内容 | 决策 |
|---|---|---|
| C-1 | needs_attention 软确认转 done | 允许"显式接受风险"路径转 done；feature-lifecycle SKILL.md 写清两条分支 |
| C-2 | 历史 completed review JSON 全量迁移 | 仅迁移 active；archived 保留字段；review schema 改忽略未知字段 |
| C-3 | workflow 节点改名兼容旧 run-state | 不兼容；旧 completed run 不再回放，无 break 面 |
| C-4 | 残留扫描白名单 | `context/team/experience/*.md` + 历史 spec（加废弃声明）+ `requirements/*/notes.md` 三类 |
| AC-A1 | F-008 迁移脚本是否入仓 | 不入仓；一次性脚本；commit message 留 trail |
| AC-A2 | F-009 新 helper 是否同步发布到 workflow_run.py / common.py | 本期仅 gate 层；其它入口后续 follow-up |
