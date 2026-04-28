---
id: REQ-2026-002
title: 统一门禁系统 · 概要设计
created_at: "2026-04-27 21:20:00"
refs-outline-design: true
---

# REQ-2026-002 · 概要设计

## 1. 总体架构

四层结构，单一目录承载：

```
scripts/gates/
├── registry.yaml          [SoR]      门禁元数据：id / triggers / 适配条件 / 严重度 / 失败提示 / 依赖 / 副作用 / escape_hatch / tests
├── run.py                 [Runner]   trigger 上下文构造 → 过滤 → 拓扑排序 → 事务执行 → 输出 Report → 写 audit log
├── plugins/               [Logic]    Gate 抽象类 + 各检查的具体实现
│   ├── base.py            Gate / Report / GateContext / Severity 抽象
│   ├── meta_schema.py     adapter → check_meta
│   ├── index_integrity.py adapter → check_index
│   ├── sourcing.py        adapter → check_sourcing
│   ├── review_verdict.py  adapter → check_reviews（含 R001~R007）
│   ├── plan_freshness.py  adapter → check_plan
│   ├── workspace_clean.py post-dev-verify 子项
│   ├── traceability.py    封装 traceability-consistency-checker Agent 调用
│   ├── pr_state.py        H4：gh api 查 PR state
│   └── bash_write_protect.py H5：解析 PreToolUse Bash command
├── triggers/              [Edge]     6 类触发入口的薄壳，仅做参数转发
│   ├── pre_tool_use.sh    替换 .claude/hooks/protect-branch.sh
│   ├── pre_commit.sh      替换 scripts/git-hooks/pre-commit
│   ├── phase_transition.py 由 managing-requirement-lifecycle 调用
│   ├── submit.py          由 /requirement:submit 调用
│   ├── ci.sh              CI workflow 单一 step
│   └── post_dev.sh        替换 scripts/post-dev-verify.sh
├── migration/             [Tools]    迁移期辅助工具
│   ├── capture-baseline.sh 抓旧入口行为快照
│   ├── normalize-stderr.sh 归一化时间戳/路径/ANSI
│   └── render-docs.py     从 registry.yaml 渲染 gate-checklist.md
└── audit/<YYYY-MM>/       [Output]   每次 trigger 执行的结构化审计 JSON（路径来源：requirements/REQ-2026-002/plan.md:82）
```

设计意图：**registry 是知识、runner 是流程、plugin 是逻辑、trigger 是边界**。这与 D-002（registry 仅元数据，逻辑在 plugin）一致（来源：requirements/REQ-2026-002/plan.md:64）。

## 2. 模块划分

### 2.1 registry.yaml（事实源）

承载 9 字段（候选集合见 requirements/REQ-2026-002/artifacts/requirement.md:48），detail-design 定稿。**不放业务逻辑**——仅声明 gate 是什么、何时跑、怎么报错。同时声明 `escape_hatches` 段（来源：requirements/REQ-2026-002/plan.md:88），任何逃生口必须在此显式注册。

### 2.2 run.py（编排层）

输入：`GateContext`（trigger / requirement_id / from_phase / to_phase / changed_files / cli_flags / actor）。

主流程：
1. 加载 + 校验 registry（schema + 依赖图无环，graphlib.CycleError 在加载期报）
2. 按 trigger + applies_when 过滤候选 gate
3. 拓扑排序得到执行顺序
4. 事务包裹（meta.yaml stash via shutil.copy2，来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:21）
5. 逐 gate 调 plugin.precheck / plugin.run；任一 error → 已运行 gate 的 plugin.rollback；rollback 自身失败 → 写 [blocker] gate-rollback-failed（来源：requirements/REQ-2026-002/artifacts/requirement.md:68）
6. 汇总 Report，写 audit log
7. 退出码：error → 1；warning（非 strict）→ 0；warning（strict）→ 1

### 2.3 plugins/base.py（契约）

```python
class Gate(ABC):
    id: str
    severity: Severity
    triggers: set[str]
    applies_when: dict
    dependencies: list[str]
    side_effects: Literal["none", "write_state"]

    @abstractmethod
    def precheck(self, ctx: GateContext) -> Skip | None: ...
    @abstractmethod
    def run(self, ctx: GateContext) -> Report: ...
    def rollback(self, ctx: GateContext) -> None: ...   # side_effects=none 可省
```

`Report` 字段：decision（pass/fail/skip）/ code / message / fix_hint / vars。

### 2.4 plugins/<name>.py（适配器）

每个现存 check 一个 plugin，**逻辑零改动**——只把 `Report` API 适配到统一契约。R001~R007 在 review_verdict.py 内拆为 7 个 sub-rule（共用一个 plugin，不拆 7 个文件，避免过度切碎）。

### 2.5 triggers/*（薄壳）

每个 trigger 是 ≤ 30 行的薄壳，仅做参数收集 + 调 run.py。例：

```bash
# pre_tool_use.sh
TOOL=${CLAUDE_HOOK_TOOL_NAME:-}
TARGET_PATH=${CLAUDE_HOOK_FILE_PATH:-}
exec python3 scripts/gates/run.py --trigger=pre-tool-use \
  --tool="$TOOL" --target-path="$TARGET_PATH" --command="$CLAUDE_HOOK_COMMAND"
```

### 2.6 migration/（迁移期工具，F-004 后部分可删）

- `capture-baseline.sh`：迁移前抓旧入口的 exit code + stderr，落盘到 `migration/baselines/<gate-id>.txt`
- `normalize-stderr.sh`：去 ANSI / 时间戳 / 绝对路径前缀，关键前缀过滤后输出（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:30）
- `render-docs.py`：渲染 gate-checklist.md（D-007 强校验，来源：requirements/REQ-2026-002/plan.md:106）

## 3. 数据流

```
        ┌──────────────┐
        │ trigger 入口 │ pre-commit / pre-tool-use / phase-transition / submit / ci / post-dev
        └──────┬───────┘
               │
               ▼
        ┌─────────────────────────────┐
        │ run.py: 构造 GateContext    │
        │  → 加载 registry.yaml       │
        │  → 过滤适用 gate            │
        │  → 拓扑排序                 │
        │  → 事务包裹（meta stash）   │
        └──────┬──────────────────────┘
               │
               ▼ 逐 gate 调用
        ┌──────────────────────┐
        │ plugin.precheck()    │ 决定是否 skip
        │ plugin.run()         │ 返回 Report
        │ （失败时） rollback  │
        └──────┬───────────────┘
               │
               ▼
        ┌──────────────────────────────┐
        │ Report 汇总                   │
        │  → 写 audit/<YYYY-MM>/*.json  │
        │  → 退出码                    │
        └──────────────────────────────┘
```

## 4. 与需求章节的对应

| requirement.md 场景 | 实现支点 |
|---|---|
| 场景 1（开发者新增门禁） | scaffold.py（migration/）+ Gate 基类 + tests/ 目录约定 |
| 场景 2（next 切阶段） | triggers/phase_transition.py + 事务包裹 + rollback 失败兜底 |
| 场景 3（CI 全量） | triggers/ci.sh：单 step 跑 `--trigger=ci`（替代 quality-check.yml 当前 5 step，来源：.github/workflows/quality-check.yml:28） |
| 场景 4（submit） | triggers/submit.py：复用 next gate 集合 + pr_state plugin |
| 场景 5（4 PR 灰度） | migration/capture-baseline.sh + normalize-stderr.sh + 旧入口薄壳 |
| 场景 6（H5 Bash 写保护） | plugins/bash_write_protect.py + triggers/pre_tool_use.sh + 双轨白名单（来源：requirements/REQ-2026-002/plan.md:96） |

## 5. 关键技术选型回顾

均承袭 tech-feasibility 阶段定稿（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:11）：

- **拓扑排序**：`graphlib.TopologicalSorter`（标准库，零依赖）
- **事务**：`shutil.copy2` stash + 失败 copy 回（不引数据库或 WAL）
- **stderr 归一化**：自写 bash（约 40-60 行）
- **进程链识别**：`ps -p $PPID -o comm=` 双轨（父进程链 + CLAUDE_GATES_BYPASS 环境变量）
- **文档渲染**：裸 Python str.format（不引 Jinja2）
- **schema 校验**：手写（与 check_meta.py / save_review.py 同模式，来源：scripts/lib/check_meta.py:1）

## 6. 可扩展性

- **新增门禁**：填 registry.yaml 一条 + 写一个 plugin（≤ 100 行）+ 写测试。脚手架 `scaffold.py new-gate` 减半工作量。**不需要**改 trigger / runner / CI yml / pre-commit。这是核心设计目标（来源：requirements/REQ-2026-002/artifacts/requirement.md:53）。
- **新增 trigger**：扩 `triggers/` + 在 registry.yaml 的 `triggers` 枚举加一项 + 在 `run.py` 加 dispatch 分支。属于"有意例外"（来源：requirements/REQ-2026-002/artifacts/requirement.md:55）。
- **跨需求 governance gate**：本轮不做（来源：requirements/REQ-2026-002/artifacts/requirement.md:142），未来通过新增 `--trigger=governance` 实现。
- **escape hatch 升级 RBAC**：本轮 D-005 决议不做（来源：requirements/REQ-2026-002/plan.md:88）；未来可在 plugin 层加 reviewer 字段验证。

## 7. 与现有系统集成

### 7.1 兼容期路径（F-001 ~ F-003）

旧入口 `scripts/check-*.sh` / `scripts/post-dev-verify.sh` 改写为薄壳：

```bash
#!/usr/bin/env bash
# 兼容入口，转调统一 runner（F-004 删除）
exec python3 "$(dirname $0)/gates/run.py" --trigger=adapter --legacy=check-meta "$@"
```

不双跑、不重复执行（来源：requirements/REQ-2026-002/plan.md:41）。验收靠 snapshot 行为契约（来源：requirements/REQ-2026-002/artifacts/requirement.md:122）。

### 7.2 替换路径（F-004）

- 删除 7 个 `scripts/check-*.sh` 薄壳
- 删除 `scripts/post-dev-verify.sh`
- 删除 `scripts/lib/check_*.py`（adapter 已在 plugins/ 下复用其逻辑）
- 留下 `scripts/lib/save_review.py`（reviewer Agent 仍调用）

### 7.3 与既有数据契约

- meta.yaml schema：完全不变（来源：requirements/REQ-2026-002/artifacts/requirement.md:101）
- review-schema.yaml：完全不变
- 既有 `requirements/*/reviews/*.json`：完全兼容
- 仅新增 `scripts/gates/audit/<YYYY-MM>/`，不污染现有目录

## 8. 不在概要设计范围

下列条目留待 detail-design：

- registry.yaml 的字段精确 schema（YAML 子键名、必填/可选）
- Gate 基类的 Python 类型签名（异常体系、上下文对象字段）
- audit JSON 的字段集（trigger / passed / failed / skipped / escape_used / actor / rollback_failed 等）
- normalize-stderr.sh 的具体正则
- pr_state plugin 调 gh api 的具体命令
- bash_write_protect plugin 的正则集合
- 9 字段集合的最终命名（来源：requirements/REQ-2026-002/artifacts/requirement.md:48）

## 9. 风险回顾

均承袭 tech-feasibility 风险表（来源：requirements/REQ-2026-002/artifacts/tech-feasibility.md:80），无新增。本阶段未发现需要新立的架构风险。

## 待澄清清单

无遗留问题。tech-feasibility 阶段的 2 项假设记录仍持有（详见 tech-feasibility.md 待澄清清单），由 detail-design / development 阶段闭环。
