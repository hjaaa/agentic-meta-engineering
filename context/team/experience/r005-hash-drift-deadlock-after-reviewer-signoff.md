# reviewer looks_clean 后改主产出会触发 R005 hash drift 死循环

**沉淀原因**：跨需求重复（每个 REQ 走完 review 后都可能想再改文档）、AI 反复错（自动响应 reviewer finding 时直接改文件没意识到代价）、跨会话保留（必须形成"评估再改"的肌肉记忆）。

## 问题

REQ-2026-005 已完成 detail-design / outline-design / definition 三轮 reviewer sign-off，发现 3 处文档问题想清理（P-04 孤儿「待补充」标记 / D-008 ruff 偏离 / 详设字面 `--select=E,W,F` vs 实际 `select=F`）。

但这些文件全在 `meta.yaml.reviews.{phase}.artifact_hashes` 中。一旦修改 → R005 hash drift 报警 → `stale: true` → GATE-REVIEW-VERDICT FAIL → submit / phase-transition 被卡 → 唯一恢复路径是回退阶段重走 3 轮评审 + 3 次 sign-off。

## 根因

`scripts/lib/check_reviews.py:_r005_hash_drift` 把 review 时刻的 sha256 作为"业务信号未变"的代理。但工具层无法区分"业务字段"vs"措辞 / 元数据"——任何 byte 改都触发 stale。

`completed` 阶段会全量校验 definition / outline-design / detail-design 三轮（`PHASE_REQUIREMENTS["completed"]`），改任一上游文档都会让链式重审。修一处文档的边际收益（清孤儿标记 / 措辞）远低于 3 轮 review + 3 次 sign-off 的代价。

## 解法

**reviewer sign-off 后的文档修改决策树**：

1. **能不能不改？** — 优先级最高：把"想改的内容"作为 ADR 写入 `plan.md`（D-NNN 段）而不是改 spec 文档。详设字面与实现不一致是**临时承担**，ADR 即唯一决策记录。
2. **必须改？** — 评估"改的收益 vs 重审成本"：
   - 影响合规 / 误导后续开发 / 阻断功能 → 改，接受重审
   - 措辞 / 注释 / 历史孤儿标记 → **不改**，记入 traceability-report 的 follow-up，留给下游需求一并处理
3. **批量改？** — 开专项 REQ 一次性回退 + 改 + 重审，避免散点 churn

**hot-fix 例外**：plugin / 代码 bug 修复不影响 review hash（因 review hash 只盯 spec 文档），可以直接 commit。

## 验证方法

- 改 spec 文档前先 `python3 scripts/gates/run.py --trigger=submit --req=<id>` 看 GATE-REVIEW-VERDICT 是否过——过则评估改后是否还过
- 检查 `meta.yaml.reviews.{phase}.artifact_hashes` 列出的文件清单：在列表里 = hash 敏感，不在 = 安全

## 引用来源

- `scripts/lib/check_reviews.py:203-256`（`_r005_hash_drift` + `completed` 全量校验）
- `requirements/REQ-2026-005/plan.md` D-008（ADR 不改详设的实例）
- `requirements/REQ-2026-005/artifacts/traceability-report.md` P-04（不改决策的实例）
- 相关已沉淀经验：`dry-run-sourcing-before-reviewer.md`（评审前预检）/ `lint-rule-spec-vs-derived-docs.md`（衍生文档豁免）
