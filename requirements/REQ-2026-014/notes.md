- [2026-05-17 23:38:08] [bootstrap] 设计来源：context/team/engineering-spec/specs/2026-05-17-worktree-isolation-migration-design.md v0.2（DRAFT，huangjian + Codex 起草于 2026-05-17）。spec 已覆盖目标 / D-001~D-015 决策 / 架构（worktree_manager.py + requirement_naming.py）/ bootstrap 顺序与 rollback / meta.yaml 扩展 / submit&archive 语义 / 测试计划 / Phase 1-4 迁移步骤 / 风险表 / 验收 9 条。开发以 spec 为权威单源；阶段产出物对照抽取并补缺口（见 plan.md D-000）。
- [2026-05-17 23:58:42] [definition] reviewer feedback 4 条处理：P3 6 类已修；P2 场景 2 dirty workspace fail-closed 已加；P1 范围 /workflow:submit 改为 /requirement:submit + 新增不包含项 + 待澄清 #5；P1 章节名仅采纳"验收 → 验收标准"，"用户场景"/"待澄清清单"保留（模板权威 + check_sourcing 硬约束 + 历史一致）
- [2026-05-18 00:03:37] [definition] /workflow:save 用 workflow_save.py 失败：infer_run_id_from_branch 从 feat/req-2026-014 推出 2026-014（丢 REQ- 前缀），_resolve_run_dir 在 requirements/2026-014/ 找不到 → exit 1。这正是本 REQ 验收 #7 要修的 case，spec §11 Phase 3 已列入 infer_run_id_from_branch 兼容工作。退化到 process.txt [save] 兜底，不在 definition 阶段提前 patch common.py。
- [2026-05-18 09:10:00] [outline-design] artifacts/outline-design.md 起草完成（≈ 480 行）：架构方案 4 层 + 模块切分（既有改造点 6 / 新增 2 / 配置 3 + 无环依赖图）+ 7 条架构级选型（D-001/003/004+005/006/009/010/013+014）+ 4 关键流程（policy×state 4×4 决策矩阵 / external 复用 + dirty fail-closed / setup baseline / archive cleanup 三重保护）+ 状态机两张（worktree.state 主 + bootstrap policy 子）+ 3 条架构关注点（AC-A1~A3：feature 粒度 / harness 行为差异 / 历史目录迁移）+ 4 条结构级开放项。check_sourcing --strict 通过（首版命中 2 条 W002：选型二/五标题"默认"/"必须"+D-003/D-009 数字断言；改写标题去掉强约束动词后 0 issue）。
- [2026-05-18 09:10:14] [outline-design] reviewer-001 verdict needs_attention/score 86，4 条 issue 全闭环（2 required + 2 suggestion + 1 architectural concern 全部落地到文档）：(R1) baseline_failed 状态机回边箭头补全（line 386-394 redraw 加 ◀── retry 边）；(R2) 选型四 D-006 字段范围 9 字段枚举改为 6 类抽象（line 222 去 schema 强度）；(S1) 选型筛选标准段落显式化（line 194：模块边界 / 数据流向 / 状态机字段三类）；(S2) 待澄清编号 #1~#4 → OD-1~OD-4 避命名空间撞车；(AC concern) AC-A1 加 detail-design schema 注释提示。修复中引入 2 次回归（reviews/ 路径相对位置错 → E002 + 筛选标准多个"默认+digit" → W002），均已二次修正；check_sourcing --strict 0 issue。
- [2026-05-18 09:13:49] [outline-design] reviewer-002 looks_clean/92 supersedes -001：5 条修复全 verified（R1/R2/S1/S2/AC-A1）；维度评分 alignment 90→93 / module 80→92 / tech_choice 88→93 / scalability 86→92 / integration 85→90，加权 86→92 跨越门槛；无新增 P0；下一步走人工 signoff（save_review.py signoff --rev-id REV-REQ-2026-014-outline-design-002）→ phase-transition outline-design → detail-design。


## 会话经验（2026-05-18 00:11）

_本轮无新经验_

## F-004 派发前必读 · F-003 regression 修复挂载（2026-05-18）

F-008 review 时发现 F-003 改造的副作用 regression（决议：F-004 一并修）：

**Symptom**：`tests/skills/test_workflow_bootstrap.py` 7 用例失败
- 5 处 `FileNotFoundError` on `mkdir(...)` — 因 F-003 `_generate_req_id` 取消 mkdir-as-lock，测试假设 `requirements/<key>/artifacts/` 自动建目录已不成立
- 2 处 `TypeError: cannot unpack non-iterable RunArgs object` — 因 F-003 `_parse_args` 返 RunArgs dataclass 替代 3-tuple

**Root cause**：F-003 改造时 `tests/lib/test_workflow_run_worktree_args.py`（F-003 touches）作了适配，但 `tests/skills/test_workflow_bootstrap.py`（不在任一 feature touches）的 API 漂移未同步；F-003 review scope 是 touches 限定，所以也没看到这些失败。

**F-004 派发时必做**（在 F-004 task.md / dispatch 上下文中显式说明）：
1. 测试文件 `tests/skills/test_workflow_bootstrap.py` 需补到 F-004 临时 touches（理由：F-004 重写 `_setup_worktree_or_branch` + `_bootstrap_requirement` 必然要更新这批 caller-side 测试）
2. 5 处 `mkdir` 失败：测试 setup 段补 `(requirements/<key>/artifacts/).mkdir(parents=True, exist_ok=True)` 或调用 `_run_requirement` 走完整路径
3. 2 处 `RunArgs unpack`：改 `RunArgs(template_id, template_args, title, slug=None, no_worktree=False, worktree_policy=None)` 构造而非 tuple unpack
4. 跑 `pytest tests/skills/test_workflow_bootstrap.py -v` 确认 12/12 全过

**不在 F-004 主线（仅扩 touches）**：上述 7 用例的失败属 F-003 regression cleanup，与 F-004 自身改造解耦记录在 commit message。

## workflow run 与 lifecycle 路径并存说明（2026-05-18）

本需求 `run-state.jsonl` 在 bootstrap 阶段写入 8 行事件后停在 `awaiting_claude_action`（末位 `node_ready` for skill `requirement-input-normalizer`）。后续 phase 推进（definition / tech-research / outline-design 共 3 次门禁）全部走 `managing-requirement-lifecycle` Skill 的 legacy 路径，未接 `save_node_result.py` handoff，jsonl 自此与 `meta.yaml.phase` 脱钩。

- ❌ 不要对本需求执行 `/workflow:continue`（会被 state matrix 拦下：`awaiting_claude_action` ∉ {running, paused, failed}）
- ✅ 继续推进用 `/requirement:continue` 或常规阶段切换
- ℹ️ F-012（`/workflow:next` 统一阶段切换入口）落地后双轨会收敛，届时再决定 jsonl 是否需要回补或主动废弃

