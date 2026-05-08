# REQ-2026-009 · 自定义工作流改造 — 详细设计

## 文档定位

本文档把 outline-design §7 锁定的 9 项 detail-design 待办落到「接口签名 / 数据结构 / 时序 / 实现要点 / 单测覆盖 / 影响域」六类机读细节，作为 development 阶段实施的唯一蓝图。

- **上游**（来源：requirements/REQ-2026-009/artifacts/outline-design.md:454）9 项待办映射为本文 §1 ~ §9
- **上游 ADR**（来源：requirements/REQ-2026-009/plan.md:51）D-001 ~ D-010 闭合本阶段范围；本文不引入新决策
- **上游 spec**（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md）v2.2 修订点 §5 / §11.2 / §11.3 在本文 §6 / §7 落地
- **下游**：本阶段同步产出 `features.json`；task-planning 阶段再拆 `tasks/<fid>.md`
- **章节编号约定**：§1 ~ §9 与 outline-design.md §7 待办表 # 1 ~ # 9 一一对应；§10 ~ §12 为收尾段；本文档采用「先写章节 stub + 待澄清清单」的骨架风格，逐项细化在 detail-design 阶段后期完成

---

## 1. 11 个 `/workflow:*` 命令接口签名（对应 outline §7 待办 #1，主责 D-008）

### 1.1 命令清单与 ARGUMENTS

来源：requirements/REQ-2026-009/artifacts/outline-design.md:458 锁定 11 个命令名称；本节给出 ARGUMENTS 形态与触发条件的初版骨架。

| # | 命令 | ARGUMENTS 形态 | 触发条件 | 主要副作用 |
|---|---|---|---|---|
| 1 | `/workflow:new` | `<template-id> [<title>]` | 用户主动 | bootstrap run 目录 + jsonl + 初始 prompt |
| 2 | `/workflow:continue` | `[<run-id>]`（缺省=匹配当前分支） | 用户主动 / launcher | 重建 RunState 进 main loop |
| 3 | `/workflow:next` | 无 | 当前节点完成 | 推进到下一拓扑节点 |
| 4 | `/workflow:save` | `[note]` | 用户主动 | jsonl 追加 `[save]` 事件 |
| 5 | `/workflow:status` | `[<run-id>]` | 用户主动 | 只读输出（含父子树） |
| 6 | `/workflow:list` | `[--filter=...]` | 用户主动 | 只读输出 |
| 7 | `/workflow:approve` | 无 | approval_pending 状态 | 状态机 → approved（hook 拦 AI） |
| 8 | `/workflow:reject` | `<reason>` | approval_pending 状态 | 状态机 → rejected + on_reject 路径 |
| 9 | `/workflow:rollback` | `<to-node>` | 用户主动 | mv 产物到 `.archived/<ts>/` + jsonl 截断 |
| 10 | `/workflow:cancel` | 无 | 用户主动 | 父 jsonl 写 `cancel_requested` |
| 11 | `/workflow:submit` | `[--draft]` | 当前 run 进入 testing | submit gate + 推分支 + 开 PR |

### 1.2 每命令的接口模板（六字段）

每命令在 `.claude/commands/workflow/<cmd>.md` + `.claude/skills/managing-workflow-runs/SKILL.md` 中给出固定字段：ARGUMENTS 解析规则、入参约束、前置条件（当前 RunState 状态集合）、副作用（jsonl 事件 tag）、返回 / 输出（主对话回报模板）、失败模式（错误码 → 文案）、决策回引（D-XXX）。模板参考既有 `.claude/skills/managing-requirement-lifecycle/SKILL.md` 的 8 子动作派发结构。详细字段表与状态机交互矩阵见 `## 待澄清清单` OQ-DD-A1 / OQ-DD-A2。

### 1.3 单测覆盖

测试落 `tests/skills/test_workflow_commands.py`，按命令×状态矩阵生成用例；用例数量与覆盖度阈值见 OQ-DD-A3。

---

## 2. 节点级 prompt 文件清单（对应 outline §7 待办 #2，主责 D-001）

### 2.1 目录结构（v2.2 spec 落地）

来源：requirements/REQ-2026-009/artifacts/outline-design.md:459 锁定节点级 prompt 抽到 `.claude/workflows/prompts/`。

```
.claude/workflows/prompts/
  standard-8phase/      # 8 阶段对应 prompt
  code-review-embedded/ # 8 critic + critic 对抗 + 综合裁决
```

### 2.2 frontmatter 与 ARGUMENTS 注入约定

每个 prompt 文件 frontmatter 字段集合、ARGUMENTS 透传规则、`$ARTIFACTS_DIR` 父子隔离约定、jsonl 中 `$LOOP_OUTPUT` 读取协议——见 `## 待澄清清单` OQ-DD-A4。

### 2.3 单测覆盖

测试落 `tests/workflows/test_prompt_structure.py`：每文件 frontmatter 解析 + input 占位符与 yaml 节点 inputs 一致性。

---

## 3. `features.json` 拆分（对应 outline §7 待办 #3）

### 3.1 schema 引用

来源：context/team/engineering-spec/features-schema.yaml 作为 `id` / `title` / `description` 必填的事实源；可选机读字段（`complexity` / `depends_on_features` / `touches` / `interfaces_frozen`）来源：.claude/skills/task-context-builder/reference/extract-rules.md。

### 3.2 feature_id 编号空间分组

骨架分组前缀提案（数量精确点见 OQ-DD-A5）：`F-NODE-XXX`（节点）/ `F-CMD-XXX`（命令）/ `F-ALIAS-XXX`（兼容期别名）/ `F-CLEAN-XXX`（Plan 7 清理任务）。

### 3.3 依赖关系

骨架级 DAG 关键边（精确表见 OQ-DD-A6）：

- `F-NODE-engine-core` 是 `F-NODE-*` / `F-CMD-*` 的前置
- `F-CMD-rollback` 依赖 `F-NODE-archived-state`（D-010 `.in_progress` 标记前置）
- `F-CMD-approve/reject` 依赖 `F-NODE-hook-guard`（D-006 hook 拦截前置）
- `F-CLEAN-PHASE_REQUIREMENTS-delete` 依赖 `F-CLEAN-migration-test`（D-009 顺序约束，来源：requirements/REQ-2026-009/plan.md:128）

### 3.4 features.json 校验

来源：scripts/gates/registry.yaml 已注册 GATE-FEATURES-SCHEMA（在 phase-transition / submit / pre-commit / ci 四触发点生效）；本阶段仅"承接"该 gate，不引入新规则。

---

## 4. `keyword-matching.md` 关键词长度排序表（对应 outline §7 待办 #4，主责 D-008）

### 4.1 6 类基础关键词

来源：requirements/REQ-2026-009/artifacts/outline-design.md:201 列出 6 类（new / continue / review / release / approve / reject）；具体关键词字面量与字符长度排序表见 OQ-DD-A7（含汉字 1 字符 + ASCII 1 字符 的统一计数规则）。

### 4.2 state tiebreaker 规则

来源：requirements/REQ-2026-009/plan.md:120 D-008 第 1 步——若有 run 处于 `approval_pending` 状态，优先匹配 approve / reject，绕过最长匹配。

### 4.3 ≥2 等长冲突的 ask 兜底

主 Claude 应 ask 用户消歧；prompt 模板见 OQ-DD-A7。

### 4.4 单测覆盖

测试落 `tests/skills/test_keyword_matching.py`：每类基础关键词、等长冲突、state tiebreaker、空匹配兜底各覆盖；具体用例数见 OQ-DD-A7。

---

## 5. `pre-tool-use-guard.sh` case 分支详细脚本（对应 outline §7 待办 #5，主责 D-006）

### 5.1 现状定位

- 旧 isatty 校验位于 scripts/lib/code_review_signoff.py:61
- spec §15 决策删除该校验（来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md）
- 新拦截点：`.claude/hooks/pre-tool-use-guard.sh` 同构搬到 hook 层（D-006，来源：requirements/REQ-2026-009/plan.md:101）

### 5.2 patch 形态

新增 case 分支拦截 `/workflow:approve` / `/workflow:reject` / `python3 scripts/lib/workflow_approve.py` / `python3 scripts/lib/workflow_reject.py` 四个入口；命中且非 tty 进程时通过 fd 3 写拒绝消息后 exit 2（与 hook 既有约定一致）。完整 shell 片段见 OQ-DD-A8。

### 5.3 fd 3 / exit 码约定

来源：scripts/lib/check_reviews.py 中既有 hook 调用模式；本 patch 不引入新约定。

### 5.4 兜底 isatty

新增 `scripts/lib/workflow_approve.py` / `scripts/lib/workflow_reject.py` 仍 fail-closed 校验 `sys.stdin.isatty()`，避免 hook 漏拦。

### 5.5 单测覆盖

测试落 `tests/hooks/test_pre_tool_use_guard.py`：覆盖 4 入口 × {tty / 非 tty} × {直接调用 / python 包装路径} 矩阵；具体用例与 fixture 见 OQ-DD-A8。

### 5.6 ai-collaboration.md 规则三 patch

来源：context/team/ai-collaboration.md 现规则三仅写 sign-off 是人类专属；patch 后扩展到 sign-off / approval / reject 三类，列出新入口 `/workflow:approve` / `/workflow:reject`。

---

## 6. `workflow_rollback.py` 4 场景单测设计（对应 outline §7 待办 #6，主责 D-010）

### 6.1 公开 API 签名

来源：requirements/REQ-2026-009/plan.md:138 D-010 锁定的 mv 语义。

```python
def rollback_run(run_id: str, to_node: str, target_id: Optional[str] = None) -> RollbackResult:
    """
    把 run_id 从当前节点回滚到 to_node：
    - 拓扑序找产物路径集合 → shutil.move 到 .archived/<ts>/
    - 父 run 跨 sub_workflow 节点时，递归 mv 子 run 整目录
    - 写 .in_progress atomic 标记保护中断
    - 截断 jsonl 尾部 mv 为 <archived>/run-state.jsonl.tail
    """
```

`RollbackResult` 字段表 + 异常契约见 OQ-DD-A9。

### 6.2 4 场景测试矩阵

| 场景 | 描述 | 关键断言 |
|---|---|---|
| R1 单层 | 单 run 内回滚到中间节点 | 原路径删 / `.archived/<ts>/<相对路径>` 存在 / jsonl 尾部 mv 为 `.tail` |
| F1 跨父子 | 父 run 回滚越过 sub_workflow 节点 | 子 run 整目录 mv / 子 id 释放 |
| T1 多次 | 同 run 第二次回滚 | 两个 timestamp 目录互不覆盖 / `.in_progress` 各自独立 |
| 到 root | rollback 到首个节点 | 全部产物归档 / jsonl 仅留 init |

每场景 fixture 数据 + 期望文件树 + 期望 jsonl 行数见 OQ-DD-A9。

### 6.3 中断保护

`.in_progress` 标记 + 续跑流程：检测残留 → 完成 mv 收尾或回退；并发互斥用 `fcntl.flock` 或 `os.O_EXCL`（具体选型见 OQ-DD-A9）。

---

## 7. `sub_workflow` 父子状态联动 e2e 测试设计（对应 outline §7 待办 #7，主责 D-005 / D-010）

### 7.1 cancel graceful 路径

来源：requirements/REQ-2026-009/plan.md:92 D-005 锁定"子自检父"模式：父 jsonl 写 `cancel_requested` → 子 subagent poll 检测 → 子写 `parent_cancelled` graceful 退出 → 父等子返回或 30s 超时调 `TaskStop` forceful 兜底。

### 7.2 rollback 跨父子路径

父 N+5 → N+1 节点产物归档 + 子 run 整目录 mv 到 `sub_runs/<child-id>/` + 子 id 释放（D-010，来源：requirements/REQ-2026-009/plan.md:138）。

### 7.3 测试运行环境

子 subagent 在测试中的模拟方式（mock subprocess vs 真派 Agent）、poll 间隔可调缩短到 100ms 加速测试——具体方案见 OQ-DD-A10。

### 7.4 单测覆盖

测试落 `tests/e2e/test_sub_workflow_lifecycle.py`：2 条端到端 + 边界（父进程崩 / 子崩 / 网络分区 / TaskStop graceful 不明确兜底）。

---

## 8. migration 测试设计（对应 outline §7 待办 #8，主责 D-009 / R-3）

### 8.1 旧门禁规则与新引擎等价语义对照

来源：scripts/lib/check_reviews.py 现有 R001 ~ R006 规则；本节列骨架对照表，每条规则的"新引擎等价点"见 OQ-DD-A11。

| 规则 | 含义 | 新引擎等价点（骨架占位） |
|---|---|---|
| R001 | 各阶段必备 review latest != null | 见 OQ-DD-A11 |
| R002 | 评审 conclusion ≠ rejected | 见 OQ-DD-A11 |
| R003 | tty 签字 | D-006 hook 层（已锁定，§5） |
| R004 | hash 一致性（sha256 与当前 commit） | 见 OQ-DD-A11 |
| R005 | 无自引用循环（reviews/* 黑名单） | 见 OQ-DD-A11 |
| R006 | features.json schema valid | GATE-FEATURES-SCHEMA（已存在，仅迁移触发点） |

### 8.2 测试运行约定

双跑对照（旧引擎 + 新引擎跑同 fixture，比对结论），落 `tests/migration/test_phase_requirements_equivalence.py`；通过门槛见 OQ-DD-A11。

### 8.3 顺序约束

来源：requirements/REQ-2026-009/plan.md:128 D-009——本测试通过是 Plan 7 删除 `PHASE_REQUIREMENTS` 的前置条件。

---

## 9. `requirements/` → `runs/` 批量 rename 工具（对应 outline §7 待办 #9，主责 D-002）

### 9.1 path 引用扫描范围

来源：requirements/REQ-2026-009/artifacts/outline-design.md:466 列出扫描类别。骨架级覆盖：`*.py` / `*.sh` / `*.md` 全文 grep；`.claude/skills/` / `.claude/commands/` / `.claude/agents/` 引用；`scripts/gates/registry.yaml` changed_files 模式；`context/team/engineering-spec/` 文档；历史 commit message（不改 git history，但需在迁移说明文档中说明）。

### 9.2 工具签名

```python
def migrate_requirements_to_runs(
    dry_run: bool = True,
    include_history_comments: bool = False,
) -> MigrationReport:
    """扫描 → 列出引用清单 → 修改 → 自检"""
```

`MigrationReport` 字段表（`files_changed[]` / `references_found[]` / `risky_unmapped[]` / `pre_commit_added[]`）见 OQ-DD-A12。

### 9.3 pre-commit hook 拦截规则

Plan 7 后新增 pre-commit hook：拒绝任何新增的 `requirements/` 字面量引用，白名单 = 历史 ADR / 迁移文档；详细规则见 OQ-DD-A12。

### 9.4 自动 vs 人工 review

字面量 path 自动改；含变量拼接（`f"requirements/{req_id}"`）的代码必须 grep 出来人工 review，改为 `_resolve_run_dir` 调用。

### 9.5 单测覆盖

测试落 `tests/tools/test_migrate_requirements.py`：dry_run 报告精确 / 实际改写后 grep 全仓再无 `requirements/` 字面量（除白名单）/ pre-commit hook 拦截新引用。

### 9.6 与 D-007 协同

来源：requirements/REQ-2026-009/plan.md:110 D-007——rename 工具运行**之前**双路径 loader 必须存在；rename 完成后 loader 中"探测 `requirements/`"分支才能删（D-007 锁定 1 行清理）。

---

## 10. 接口契约的兼容性

### 10.1 yaml workflow schema v2

来源：context/team/engineering-spec/specs/2026-05-08-workflow-unified-redesign.md v2 → v2.1 → v2.2 修订点（§5 / §11.2 / §11.3）；schema 新增字段需在 `SUPPORTED_VERSIONS` 列表标注。

### 10.2 `/requirement:*` 别名兼容期

来源：requirements/REQ-2026-009/plan.md:128 D-009：8 个别名 3 月兼容期内输出 deprecation warning + 转 `/workflow:*` ARGUMENTS 透传；`/requirement:next` 例外保留实际实现到 Plan 6 自举验证通过。具体 warning 文案模板见 OQ-DD-A13。

### 10.3 `PHASE_REQUIREMENTS` 删除顺序约束

时序：

```
Plan 6 自举验证通过（本需求自身用新引擎跑通）
  ↓
migration 测试 6/6 全 pass（§8.2）
  ↓
Plan 7 真删 PHASE_REQUIREMENTS / phase_enum.py / code_review_signoff.py / /requirement:next
  ↓
Plan 7+1 删 8 个别名（兼容期到期人工触发）
```

---

## 11. 验收对齐（AC ↔ 接口 / 测试 ID 双向追溯）

继承 outline-design.md §6 的 AC ↔ 模块映射，本阶段补充 AC ↔ 测试 ID 映射；完整 AC 表见 requirements/REQ-2026-009/artifacts/requirement.md。骨架示例如下，完整表见 OQ-DD-A14。

| AC | 验证测试 ID | 主责章节 |
|---|---|---|
| AC-01 yaml schema v2 | tests/workflows/test_yaml_schema.py | §3.4 |
| AC-09 兼容期别名 | tests/skills/test_alias_passthrough.py | §10.2 |
| AC-CLEAN 旧路径清理 | tests/tools/test_migrate_requirements.py | §9 |

---

## 待澄清清单

> 详细设计阶段后期需逐一闭合。每条按「内容 / 依据 / 风险 / 验证时机」四要素填写；闭合后从清单删除并合并到对应 §N。

- **OQ-DD-A1（命令字段表）**：[待补充]
  - 内容：11 个 `/workflow:*` 命令的六字段（ARGUMENTS 解析、入参约束、前置条件、副作用、返回输出、失败模式）逐一展开
  - 依据：参考 requirements/REQ-2026-008/artifacts/detailed-design.md §1 ~ §7 的字段模板风格
  - 风险：篇幅压力 ~600 行；如需可拆 `command-implementations/<cmd>.md` 多文件
  - 验证时机：detail-design 评审前完成 11 条接口冻结（标记 `interfaces_frozen: true`）

- **OQ-DD-A2（命令×状态机矩阵）**：[待补充]
  - 内容：状态 × 命令 → 是否允许调用 + 副作用
  - 依据：覆盖状态集合 = {pending, running, paused, approval_pending, cancel_requested, cancelled, completed, failed}
  - 风险：状态 8 × 命令 11 = 88 个格子，需筛选有意义组合
  - 验证时机：与 OQ-DD-A1 同期完成

- **OQ-DD-A3（命令单测用例数）**：[待补充]
  - 内容：每命令 happy path + 非法状态拒绝的最小用例数
  - 依据：参考既有 `tests/skills/` 覆盖密度
  - 风险：测试过密拖慢 CI；过疏漏边界
  - 验证时机：detail-design 评审前

- **OQ-DD-A4（prompt frontmatter + 注入）**：[待补充]
  - 内容：frontmatter 字段集合（`name`/`node_id`/`model`/`tools_allowed`/`inputs[]`/`outputs[]`/`context_budget`）+ ARGUMENTS 注入 + `$ARTIFACTS_DIR` 父子隔离 + `$LOOP_OUTPUT` 读取协议
  - 依据：spec §6.4 已提到节点级 prompt 抽离
  - 风险：mustache 占位语法与 yaml 字段未对齐会运行时报错
  - 验证时机：detail-design 评审前需给 1 张时序图 + frontmatter 解析单测

- **OQ-DD-A5（features.json 拆分粒度）**：[待补充]
  - 内容：38 节点（standard-8phase 22 + code-review-embedded 16，含综合裁决，待精确点数）+ 11 命令 + 8 别名 + Plan 7 清理任务（约 10 项）→ feature_id 总数 65 ~ 75
  - 依据：outline §1.2 改动一览表
  - 风险：单文件超过同规模需求经验值（REQ-2026-008 约 13 个 feature），需评估拆 `features-A.json` / `features-B.json`
  - 验证时机：detail-design 评审前与用户确认是否拆多文件

- **OQ-DD-A6（features 依赖 DAG 完整表）**：[待补充]
  - 内容：所有 `depends_on` / `blocks` 边的精确列表
  - 依据：outline §3 模块划分 + ADR D-005 ~ D-010 的"前置条件"语义
  - 风险：循环依赖未检出会让 task-planning 拓扑排序死锁
  - 验证时机：features.json 提交前用 `tools/check_features_dag.py`（Plan 1 已合并工具）跑一遍

- **OQ-DD-A7（关键词字面量 + 长度表 + 单测）**：[待补充]
  - 内容：6 类关键词的字面量集合 / 字符长度数字 / 排序后顺序 / 等长冲突的 ask 兜底文案 / 单测用例数
  - 依据：outline §2.4 锁定 3 步仲裁
  - 风险：汉字与 ASCII 字符长度计数不统一会让排序错乱
  - 验证时机：detail-design 评审前 + Plan 5 实现期间持续校准

- **OQ-DD-A8（hook patch + 单测矩阵）**：[待补充]
  - 内容：完整 case 分支 shell 片段 + 4 入口 × {tty / 非 tty} × {直接调用 / python 包装路径} 测试矩阵
  - 依据：scripts/lib/code_review_signoff.py:61 现有 isatty 校验作同构参考
  - 风险：python 包装路径漏拦会让 AI 绕过 sign-off
  - 验证时机：detail-design 评审前

- **OQ-DD-A9（rollback API + RollbackResult + 中断保护）**：[待补充]
  - 内容：`RollbackResult` 字段表 + 异常契约 + 4 场景 fixture / 期望文件树 / jsonl 行数 + 并发互斥选型（fcntl.flock vs os.O_EXCL）
  - 依据：D-010 锁定的 mv 语义 + `.in_progress` 标记
  - 风险：并发 rollback 数据损坏；中断后状态无法恢复
  - 验证时机：detail-design 评审前需给 4 场景单测设计文档

- **OQ-DD-A10（sub_workflow e2e 测试运行环境）**：[待补充]
  - 内容：子 subagent 模拟方式（mock subprocess vs 真派 Agent）+ poll 间隔可调机制 + 边界场景列表（父崩 / 子崩 / 网络分区 / TaskStop graceful 不明确兜底）
  - 依据：D-005 子自检父模式 + D-010 跨父子归档
  - 风险：mock 模式覆盖不到真 subagent 的并发 race；真派模式 CI 时长爆
  - 验证时机：detail-design 评审前 + Plan 4 实现期间 smoke test 落地

- **OQ-DD-A11（migration 测试 R001 ~ R006 等价点 + 通过门槛）**：[待补充]
  - 内容：每条规则在新引擎中的等价 hook / yaml 节点 / gate；通过门槛（如 6/6 规则全 pass + 0 false-pass / false-fail）
  - 依据：D-009 自举硬阈值 + R-3 风险（PHASE_REQUIREMENTS 删除时机）
  - 风险：等价语义判定不严会让 Plan 7 删除时引入门禁空洞
  - 验证时机：Plan 6 自举验证 + Plan 7 删除前必须 6/6 通过

- **OQ-DD-A12（rename 工具 MigrationReport + pre-commit 规则）**：[待补充]
  - 内容：`MigrationReport` 字段（`files_changed[]` / `references_found[]` / `risky_unmapped[]` / `pre_commit_added[]`）+ pre-commit hook 拦截白名单
  - 依据：D-002 双轨共存 + D-007 双路径 loader 协同
  - 风险：变量拼接 path 漏改 → 运行时找不到 run 目录；白名单过宽会让旧引用永久残留
  - 验证时机：detail-design 评审前需给设计文档；Plan 7 实施时跑 dry_run 自检

- **OQ-DD-A13（别名 deprecation warning 文案）**：[待补充]
  - 内容：8 个 `/requirement:*` 别名的精确 warning 文案模板 + ARGUMENTS 透传规则
  - 依据：D-009 兼容期保留实现 + 3 月到期人工清理
  - 风险：警告过密扰民；过宽会让用户无意识依赖旧入口
  - 验证时机：detail-design 评审前

- **OQ-DD-A14（AC ↔ 测试 ID 完整映射表）**：[待补充]
  - 内容：requirement.md AC-01 ~ AC-CLEAN 全部 12 ~ 15 条逐一映射到 §1 ~ §9 中的某个测试 ID
  - 依据：outline-design.md §6 已给 AC ↔ 模块映射作上游
  - 风险：未映射的 AC 会在 testing 阶段成为追溯链断点（GATE-TRACEABILITY 拦）
  - 验证时机：detail-design 评审前

- **OQ-DD-B1（output_threshold 字节 vs 行数语义，继承 outline §7 提示性）**：[待用户确认]
  - 内容：spec §6.11 `output_threshold` 字段语义按字节还是按行数
  - 依据：默认建议字节（避免多字节字符行数偏差），假设阈值 16KB
  - 风险：触发 truncate 后丢上下文；按行数易被超长行打穿
  - 验证时机：detail-design 评审前与用户确认

- **OQ-DD-B2（loop 节点 $LOOP_OUTPUT 多变量场景，继承 outline §7 提示性）**：[待补充]
  - 内容：单 `$LOOP_OUTPUT` 字符串 vs 多 outputs 字段
  - 依据：默认假设单字符串；如需多需 yaml schema 加 `loop_outputs[]` 字段
  - 风险：loop 节点输出耦合度增加 schema 演化压力
  - 验证时机：Plan 2 loop 节点实现期间确认

- **OQ-DD-B3（sub_workflow inputs 透传约束，继承 outline §7 提示性）**：[待用户确认]
  - 内容：白名单（显式列必传字段）vs 黑名单 vs 全透
  - 依据：默认建议白名单 + 显式 `inputs:` 段
  - 风险：父子 run 数据耦合度难评估；全透会让父 run 大对象进子 run 上下文
  - 验证时机：detail-design 评审前与用户确认

- **OQ-DD-B4（8 critic 文件名约定）**：[待用户确认]
  - 内容：`.claude/workflows/prompts/code-review-embedded/cr-checker-*.md` 是否照搬现有 `.claude/agents/*-checker.md` 8 个文件名
  - 依据：现有 8 个 checker 已稳定 = security / performance / complexity / concurrency / error-handling / design-consistency / auxiliary-spec / history-context
  - 风险：重命名会让既有 review 报告引用断链；不变会让命名不一致
  - 验证时机：detail-design 评审前与用户确认

---

## 不在本设计范围

继承 outline-design.md §"不在本设计范围"：

- **Post-MVP 第一批**：`lite-3phase` / `hotfix` / `release-cut` / `codex-review-loop` / `pr-feedback-handle` / `extract-experience` / `generate-sop` / `general-assist` 模板
- **Post-MVP 其他**：多 provider 共存 / git worktree 强制隔离 / 独立 daemon / HTTP API server / Web Dashboard / Postgres 持久化 / `maxBudgetUsd` 节点级硬熔断 / 多步连接词串行执行
- **不引入**：兼容期到期后旧别名的自动清理 CI 门禁（D-003 锁定为人工清理）
- **不引入**：双重确认链路（cli + tty 两处校验，spec §15 反对）；本设计 §5 仅单一 hook 层

detail-design 阶段额外裁定：

- **不冻结接口实现代码**：本骨架仅给签名 + 数据结构 + 测试设计；具体函数体落 development 阶段
- **不写 features.json 实际内容**：features.json 由本阶段后期产出，"分组规则"与 DAG 关键边在 §3 锁定即可
