# reviewer artifact_hashes 不应钉到 dev 期会演进的 task.md frontmatter

**沉淀原因**：跨需求重复（任何走"detail-design reviewer 钉 task.md → dev 多 feature 串行推进"模式的需求都会撞）、AI 反复错（D-010 已记录但本需求 dev 6 个 feature 仍每次都触发 6 次 R005）、跨会话需保留（涉及 reviewer Agent 实现 + R005 校验规则，需未来 hotfix 设计者快速复用上下文）。

## 问题

REQ-2026-012 detail-design reviewer 把 `meta.yaml.reviews.detail-design.artifact_hashes` 钉到 7 个 `tasks/F-NNN.md`。dev 阶段每个 feature 派发会推 `status: pending → in-progress → done` + `updated_at` 时间戳，触发 R005 hash drift。本需求 6 个 feature 串行推进 → 6 次 R005 报错 → 每次必须 refresh hash 才能解锁 phase-transition / submit。

## 根因

reviewer Agent 选 artifact 时把 task.md 整文件 hash 钉死，没区分 frontmatter（dev 期必然演进的状态字段）vs body（设计内容）。这是「reviewer artifact 选择过度收敛」——把 review 边界扩到不属于"设计"的运行时状态字段，造成 hash 与 review 语义错配。

## 解法

**两条候选改造方向**（择一）：

1. **reviewer Agent 排除 frontmatter**：写 verdict 时，对 task.md / features.json 等含 frontmatter 的文件，只 hash `body`（frontmatter 分隔符后段），不 hash 整文件。
2. **R005 校验放宽**：`scripts/lib/check_reviews.py` 的 hash 对比对 task.md 文件特殊处理，去掉 frontmatter `status` / `updated_at` 字段再算 hash。

**短期 workaround**（已在 D-010 ADR 落地）：手动 `meta.yaml.reviews.detail-design.artifact_hashes` 刷新到当前值，配套 plan.md ADR 注明"refresh 不视为重审"。

**禁止**：把 task.md frontmatter `status` 改为不变（强行 freeze 在 pending），会破坏派发链 B-1 precheck（`feature-lifecycle-manager` 要求 `status == pending` 才放派发）。

## 验证方法

- 跑模拟：在某测试需求把 task.md `status` 从 pending 改 done，重跑 `python3 scripts/gates/run.py --trigger=phase-transition --req=<id> --from=development --to=testing`，理想结果：无 R005 stale 报错（解法 1/2 都该满足）
- 跨需求验证：未来任何「detail-design → dev 多 feature」需求实测 phase-transition 一次过，无需 hash refresh
- 经验落地后：本需求级 D-010 ADR 转「历史归档」状态，不作为通用建议

## 引用来源

- `requirements/REQ-2026-012/notes.md:13-17` — 原 follow-up 候选
- `requirements/REQ-2026-012/plan.md` D-010 ADR — refresh 决策与理由
- 邻居：`detail-design-stale-after-development-needs-pre-testing-rev.md`（侧重 detail-design.md 本身 stale；本经验侧重 reviewer artifact 选择层面的结构性 bug）
