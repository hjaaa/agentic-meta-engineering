## Follow-up：把 /requirement:submit + codex-review-loop 流程迁移到 standard-8phase workflow

**背景**（来源：用户 2026-05-19 反馈 + 当前 PR 落地体验）：
- 本期 PR #82 创建走的是手工渲染 PR body + `gh pr create` + 后调 `scripts/lib/submit_codex.py` 的两步骤
- `/requirement:submit` 命令链中的 `scripts/lib/workflow_submit.py` 当前对新格式 ID `YYYYMMDD-<slug>` 不兼容（与 F-009 修的 gates/run.py 同根问题）
- standard-8phase.yaml 现在止于 `pr-merged-gate`（人工触发合并确认），未把"开 PR + codex review-loop"作为一等节点表达

**建议在下个 REQ 落地**：
1. `scripts/lib/workflow_submit.py` 同步 F-009 的 ID 复合校验（统一调 `requirement_naming.is_legacy + is_new_requirement_key`）
2. `scripts/lib/submit_codex.py` help 描述更新 `req_id: REQ-YYYY-NNN` → 兼容新格式说明
3. `.claude/workflows/requirement/standard-8phase.yaml` 增加：
   - 节点 `submit-create-pr`：调 `workflow_submit.py` 推分支 + 开 PR + 回写 meta
   - 节点 `submit-codex-review-loop`：调 `submit_codex.py` 轮询 codex bot；output `verdict=passed|not_passed|timeout`
   - 节点 `submit-codex-fix-loop`（条件 `verdict=not_passed`）：循环到 main agent 修复 + 重新 push + 重跑 codex；上限 3 轮
   - `submit-codex-review-loop` 通过后衔接现有 `pr-merged-gate`
4. 触发条件：testing 阶段完成 + 用户软确认（人工 approve 当前 review）后进入 submit-create-pr

**Reference**：
- 当前 PR 实际命令：`gh pr create --base develop --head feat/req-... --body "..."` + `python3 scripts/lib/submit_codex.py 20260519-remove-human-signoff`
- 已有 spec：`context/team/engineering-spec/specs/2026-05-04-submit-codex-loop-and-archive-design.md`（早期设计；新需求需补 yaml 落地章节）
- workflow loader 节点 schema 参考 `scripts/lib/workflow_loader.py`
