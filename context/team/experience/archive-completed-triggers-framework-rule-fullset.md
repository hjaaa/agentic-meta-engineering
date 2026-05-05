# archive 命令链是 framework R-rule / 条件必填校验的最终汇总点

**沉淀原因**：跨需求会重复（A）+ AI 反复忽略（B）+ 跨会话需保留（C）

## 问题

REQ-2026-007 跑 V-04 自举 archive 后，PR #58 的 CI 在 `phase=completed` 转换处连续 fail 两次：

- **F-17**：GATE-META-SCHEMA 的 `conditional_required` 校验 `phase=completed` 时 `outcome` / `completed_at` 必须非空，但 `archive_runner` 旧实现只写 `phase` + `archived_at`，落地的 meta.yaml 这两字段空 → CI 第一次 fail
- **缺失 definition review**：GATE-REVIEW-VERDICT R001 校验 `phase=completed` 必须有 `{definition, outline-design, detail-design}` 三阶段评审，但 lifecycle skill 在 `definition → tech-research` 时跳过了 `requirement-quality-reviewer`，meta.yaml.reviews 缺 `definition` 段 → CI 第二次 fail

两条都是 testing 阶段沉默、要等 phase 切到 completed 才暴露的 framework 强约束。9 轮 codex review-loop 都没挖到（codex 只看 PR diff 不看 schema / R-rule 校验路径）。

## 根因

framework 的 `conditional_required` 和 R001~R007 按 `target_phase` 配映射：

```yaml
conditional_required:
  - when: { phase: completed }
    non_empty: [outcome, completed_at]

PHASE_REQUIREMENTS:
  testing:   [detail-design, code]
  completed: [definition, outline-design, detail-design]   # 全量
```

`phase=completed` 是终态，触发规则是**全集**。前面阶段没 trigger 的字段 / 规则会沉淀到 completed 一次性暴露。archive 命令是把 phase 推到 completed 的实际入口，所以 **archive 是这些规则的最终汇总点**——任何 testing 阶段没命中的强约束都会在 archive 实跑时集中爆发。

## 解法

**写盘契约**：archive_runner / lifecycle skill 必须把 `phase=completed` 触发的所有强约束字段写进 meta.yaml，不能只写"语义上属于 archive"的字段（`archived_at`）：

| 字段 | 来源 | 默认值 |
|---|---|---|
| `phase` | archive_runner 强制 | `completed` |
| `archived_at` | archive_runner | now() |
| `completed_at` | archive_runner | = archived_at（同动作内 phase 转换与 archive 同时发生） |
| `outcome` | archive_runner --outcome | `shipped`（默认；--force 路径需显式传） |
| `lessons_extracted` | `/knowledge:extract-experience` | 布尔，archive 前可为 false |

**评审契约**：lifecycle skill 在每次阶段切换时**必须**触发对应 reviewer，不要因"用户没明显要求"而跳过——`definition → tech-research` 必须 requirement-quality-reviewer，否则 R001 在归档时报警。

**预警机制**：扩展 framework 的 `conditional_required` 或 R-rule mapping 时，**同步检查 archive 命令链是否需要写盘新字段** + **添加 testing 阶段的 dry-run completed 阶段校验**（提前暴露缺口）。

## 验证方法

新需求归档前在 chore 分支上：

```bash
python3 scripts/gates/run.py --trigger=ci --strict
# exit 0 才 push PR；fail 则按 conditional_required / R001 报错补 meta.yaml 字段或回补迟到的 review verdict
```

## 引用来源

- `requirements/REQ-2026-007/process.txt`（19:21 + 19:30 两次 CI fail 修复）
- F-17 fix commit `4604333`：archive_runner 补 outcome + completed_at
- definition review 补救 commit `f6b7a34`
- 校验规则源：`context/team/engineering-spec/meta-schema.yaml` `conditional_required` + `scripts/lib/check_reviews.py` `PHASE_REQUIREMENTS`
- 关联经验：`squash-merge-archive-needs-second-pr.md`（archive 必须 chore PR 路径）+ `external-ai-reviewer-finds-internal-blindspots.md`（codex 看不到 schema 校验路径）
