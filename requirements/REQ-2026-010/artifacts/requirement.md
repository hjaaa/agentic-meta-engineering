---
id: REQ-2026-010
title: workflow 引擎 main loop 与 bootstrap 完整化
created_at: 2026-05-11T03:29:36Z
refs-requirement: true
---

# REQ-2026-010 · workflow 引擎 main loop 与 bootstrap 完整化

## 背景

REQ-2026-009 已完成自定义工作流改造的设计与脚手架（loader / state 文件 / 9 命令外壳 / rollback 工具 / 大量结构化测试），但**引擎核心 main loop 与 bootstrap 副作用未落地**。审阅结论：

- `/workflow:continue` 的 `_main_loop_stub` 仅打印当前状态，不执行任何节点；明确注释"F-006 待落地：节点执行 / main loop 完整实现"（来源：scripts/lib/workflow_continue.py:23）。
- `/workflow:run` 仅 glob 模板 + 写最薄 meta.yaml + 生成 `RUN-YYYYMMDD-NNN`（来源：scripts/lib/workflow_run.py:51）；与设计要求不符——详细设计 §1.2.1 明确 bootstrap 副作用应包括：load_workflow 校验、`REQ-YYYY-NNN` 生成、切 `feat/req-<id>` 分支、建 `requirements/<id>/{plan.md,artifacts/}`（来源：requirements/REQ-2026-009/artifacts/detailed-design.md:43）。
- `standard-8phase.yaml` 的第一个节点 `bootstrap-validate` 必校验 `meta.yaml` + `plan.md` 存在（来源：.claude/workflows/requirement/standard-8phase.yaml:51）——即使 main loop 实现，当前 bootstrap 不建 plan.md 也会立即失败。
- `archive-finalize` 节点硬编码 `runs/$RUN_ID/meta.yaml` 路径（来源：.claude/workflows/requirement/standard-8phase.yaml:703），与 D-007 双轨期（`requirements/<id>/` 也合法）冲突。
- 父子 run 路径分裂：status 走 `run_dir/nodes/<id>/run_id`（来源：scripts/lib/workflow_status.py:41），rollback 子 run 发现走 `run_dir/sub_runs/<node_id>`（来源：scripts/lib/workflow_rollback_subrun.py:79）；两种约定不互通会导致 rollback 与 status 看到的"子 run"不一致。

引擎在测试覆盖上"表面绿"，但 e2e 多为 mock：`test_code_review_embedded` 明确"不真启 subagent"，`test_sub_workflow_lifecycle` 明确"不真派 Agent" [待用户确认]——以上 2 条具体文件位置（注释行号）在阶段 3 技术预研时需 grep 二次定位，当前以 commit 7ffc8ad PR 描述为间接依据。

REQ-2026-009 已通过 PR-67 合并归档，phase=completed（来源：requirements/REQ-2026-009/meta.yaml）；不再回开旧需求，本需求作为 Window B 接续落地。Window A 一致性 hotfix 已经在 commit 7ffc8ad（PR-68）合并到 develop。

## 目标

- **主目标**：让 `/workflow:run standard-8phase "<title>"` + `/workflow:continue` 能真正驱动一个最小 standard-8phase run 跑过 bootstrap-validate 节点；让 7 类节点（agent / skill / prompt / bash / approval / loop / sub_workflow）的 dispatcher 框架可用（来源：requirements/REQ-2026-009/artifacts/detailed-design.md:366）。
- **次要目标**：
  - 把 `standard-8phase.yaml` 中硬编码的 `runs/$RUN_ID/...` 替换为 `$RUN_DIR` / `$META_PATH` 变量，引擎统一注入；
  - 父子 run 发现路径收敛到单一约定 `run_dir/sub_runs/<node_id>/`，status / rollback / continue 共用；
  - 用真 e2e 替换 2 条标注"不真派 Agent / 不真启 subagent"的占位测试。

## 用户场景

### 场景 1：用户用自然语言起新需求，引擎自动 bootstrap

- 角色：需求负责人（开发工程师）
- 前置：在 develop 分支，工作区干净
- 主流程：
  1. 用户敲 `/workflow:run standard-8phase "用户登录优化"`
  2. 引擎 load 模板（校验 schema 通过）
  3. 引擎生成 `REQ-2026-NNN`，切 `feat/req-2026-NNN`，建 `requirements/<id>/{plan.md,artifacts/}` + meta.yaml
  4. 引擎进入 main loop，跑 `bootstrap-validate` 节点的 `must_exist` 校验
  5. 节点 PASS，main loop 推进到 `req-input-normalize`（skill 类节点）
- 期望结果：用户在主对话看到 REQ-ID + 当前节点 + 下一步提示；目录与分支均已就绪

### 场景 2：用户用 `/workflow:continue` 续跑被暂停的 run

- 角色：需求负责人
- 前置：之前的 run state ∈ {running, paused, failed}
- 主流程：
  1. 用户敲 `/workflow:continue [<run-id>]`（缺省=按分支名推断）
  2. 引擎反扫 jsonl 重建 RunState
  3. 引擎从 `current_node` 继续 dispatcher 派发节点
  4. 遇到 approval 类节点 → 写 `approval_pending` 事件 → return（**不挂起进程**）
  5. 用户敲 `/workflow:approve` → main loop 由下次 `continue` 续跑（**方案 ii：jsonl 重建模型**）
- 期望结果：所有节点产物落到 `$ARTIFACTS_DIR`，jsonl 完整记录 node_started / node_completed / approval_pending 等事件

### 场景 3：子 workflow 跨父子 rollback

- 角色：需求负责人
- 前置：父 run 中已派发过 sub_workflow 节点，子 run 已完成
- 主流程：
  1. 用户敲 `/workflow:rollback <to-node>`，目标节点位于 sub_workflow 之前
  2. 引擎找到所有受影响子 run（统一走 `run_dir/sub_runs/<node_id>/`）
  3. 子 run 整目录归档 + 父 run jsonl 截断
- 期望结果：`/workflow:status` 输出的父子树与 rollback 看到的子 run 集合**完全一致**

## 非功能需求

- **性能**：单节点 dispatcher overhead ≤ 200ms（不计 LLM / bash 执行本身耗时）[待用户确认]——本指标用于 main loop 自身代码效率约束，验证在性能基准测试。
- **兼容性**：D-007 双路径必须支持——`runs/<id>/` 与 `requirements/<id>/` 都能被 `_resolve_run_dir` 解析（来源：requirements/REQ-2026-009/artifacts/detailed-design.md:338）。
- **安全/合规**：变量替换前必须做 `shellQuote` / JSON 序列化转义，防止注入（来源：requirements/REQ-2026-009/artifacts/detailed-design.md:336）；approval / cancel 命令的 tty 校验保持现有 `pre-tool-use-guard.sh` Hook 行为不变（来源：context/team/ai-collaboration.md）。

## 范围

### 包含

| AC | 内容 | 验证手段 |
|---|---|---|
| AC-01 | `/workflow:run` bootstrap 完整化：load_workflow 校验 + 需求类生成 `REQ-YYYY-NNN` + 切 `feat/req-<id>` 分支 + 建 `requirements/<id>/{plan.md, artifacts/}` | e2e：跑一次 `/workflow:run standard-8phase "<title>"`，断言 bootstrap-validate 节点 PASS |
| AC-02 | `/workflow:continue` main loop 真派发 7 类节点（agent / skill / prompt / bash / approval / loop / sub_workflow），写 `node_started` + `node_completed` 事件 | e2e：跑一个最小 standard-8phase run 至少穿过 2-3 节点；approval 节点写 `approval_pending` 后 return |
| AC-03 | 模板硬编码路径全部参数化：`standard-8phase.yaml` 中 `runs/$RUN_ID/...` 改为 `$RUN_DIR` / `$META_PATH`，引擎统一注入 | grep 校验 + bash 节点能在 D-007 双路径下都 PASS |
| AC-04 | 父子 run 路径收敛到 `run_dir/sub_runs/<node_id>/`；`workflow_status` / `workflow_rollback_subrun` / `workflow_continue` 共用同一发现策略 | 端到端：起 sub_workflow → status 显示子 run → rollback 跨父子归档；前后看到的子 run 集合相同 |
| AC-05 | 替换 2 条占位 e2e（`test_code_review_embedded` / `test_sub_workflow_lifecycle`）为真 e2e：真派 Agent / 真跑节点 | 新测试中至少 1 处断言 LLM 派发后 jsonl 含 `node_completed` 且 `output` 非空 |

### 不包含

- **不重写** REQ-2026-009 完成的模块：F-001（schema loader）/ F-007（rollback 核心 API）/ F-005（命令外壳）/ F-010（rollback 命令层 hotfix 已在 PR-68 完成）。
- **不动** `code-review-embedded.yaml` 模板自身逻辑（仅替换其 e2e）。
- **不做** `/workflow:next` 命令落地——F-012 阶段切换迁移作为独立 PR / 后续需求处理（来源：CLAUDE.md:23）。
- **不做** `requirements/` → `runs/` 历史目录物理迁移；D-007 双轨期延续。

## 关键决策记录

| 决策点 | 选项 | 选择 | 依据 |
|---|---|---|---|
| D-007 双路径处理 | A: 双轨期 + `_resolve_run_dir` 容忍；B: 统一 `runs/<id>/` + symlink | **A** | B 涉及历史目录迁移、超出 Window B 范围；与 REQ-2026-009 既有设计一致（来源：requirements/REQ-2026-009/artifacts/detailed-design.md:340） |
| approval_pending 交互模型 | i: 真挂起进程 + daemon；ii: 写 `approval_pending` → return → 下次 `continue` 续跑 | **ii** | 与"反扫 jsonl 重建 RunState"的现有设计天然契合，不引入进程常驻（来源：requirements/REQ-2026-009/artifacts/detailed-design.md:372） |
| 父子 run 路径 | `run_dir/nodes/<id>/run_id` 间接索引 vs `run_dir/sub_runs/<node_id>/` 直挂 | **`run_dir/sub_runs/<node_id>/` 直挂** | 与 rollback_subrun 现有默认 fixture 一致（来源：scripts/lib/workflow_rollback_subrun.py:79），后续只动 status 侧 |
| `/workflow:next` 是否纳入本 PR | 纳入 / 不纳入 | **不纳入** | F-012 工作量大且独立；本需求聚焦"main loop 框架 + bootstrap 完整化" |

## 待澄清清单

1. **NFR 单节点 dispatcher 延迟目标**（前文 200ms 数字 [待用户确认]）——是否作为硬指标？还是软约束（探针测，超阈值告警）？影响阶段 3 技术预研中是否需做 micro-benchmark。
2. **测试中 LLM 真派发的成本控制**——AC-05 的"真派 Agent" e2e 是否允许走 mock LLM（仅验证 dispatcher 链路）？还是必须用最小 prompt 走真实 LLM？影响 e2e 测试稳定性与 CI 时长。
3. **PR 描述间接引用问题**——审阅结论中提到的占位 e2e 测试（`test_code_review_embedded` / `test_sub_workflow_lifecycle` 注释明确"不真派"）具体行号需在阶段 3 技术预研时 grep 二次定位并补到本文档（当前以 commit 7ffc8ad 关联 PR 描述为间接来源）。
4. **NFR 性能基准的验证时机**——若延迟目标作为硬指标，验证时机是阶段 8 测试验收前的性能基准跑批？还是只在 CI 增量测？
