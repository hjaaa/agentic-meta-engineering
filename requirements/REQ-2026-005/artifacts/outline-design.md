---
id: REQ-2026-005
title: 门禁系统加固 · 概要设计
created_at: "2026-05-01 19:15:00"
refs-outline-design: true
---

# REQ-2026-005 · 概要设计

> 本文聚焦"模块切分 + 跨组契约"，**不重复** `requirement.md` 已述的场景与决策、**不重复** `tech-feasibility.md` 已述的技术路径与工作量。仅整理 5 组 FG 之间的代码模块边界和共享接口。

## 1. 当前门禁系统四层架构（影响视图）

```
┌────────────────────────────────────────────────────────────┐
│ Layer 1: Hook 入口（PreToolUse / pre-commit）             │ ← FG-002
│   .claude/settings.json:29 matcher                         │
└────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────────┐
│ Layer 2: Trigger 薄壳（scripts/gates/triggers/）          │ ← FG-004 (submit.py)
│   pre_tool_use.sh / submit.py / ...                        │
└───────────────────────────┬────────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────────┐
│ Layer 3: Runner（scripts/gates/run.py）                   │ ← FG-003 (filter_gates / phase 相邻)
│   filter_gates / _validate_phase_args /                    │ ← FG-004 (_handle_escape_hatch / argparse)
│   _handle_escape_hatch / parse_args                        │
│   audit.py:calc_exit_code                                  │ （不改，FG-001 不动此层）
└───────────────────────────┬────────────────────────────────┘
                            │
┌───────────────────────────┴────────────────────────────────┐
│ Layer 4: Plugin（scripts/gates/plugins/）                 │ ← FG-001 (各 _legacy_to_report)
│   meta_schema / sourcing / plan_freshness /                │ ← FG-001 (reviews_consistency CI)
│   index_integrity / reviews_consistency /                  │ ← FG-003 (删 plugin 内 changed_files)
│   protect_branch（不动）/ pr_state / traceability /        │ ← FG-005 (traceability / pr_state)
│   base_reachable / + 三个新 plugin                         │ ← FG-004 (新增 3 plugin)
└────────────────────────────────────────────────────────────┘

外围：
  registry.yaml [SoR]    ← FG-001 (F8 加 ci) / FG-003 (applies_when 字段消费) / FG-004 (tags + escape hatch)
  pyproject.toml          ← FG-005 (ruff 配置)
  .github/workflows/quality-check.yml  ← FG-005 (pytest + ruff step)
```

来源：scripts/gates/run.py / scripts/gates/registry.yaml / .claude/settings.json:29 / .github/workflows/quality-check.yml:25

## 2. 5 组 FG 的模块切分

| FG | 主修改模块 | 新增/扩展 | 不动 |
|---|---|---|---|
| **FG-001** | `plugins/{meta_schema,sourcing,plan_freshness}.py` 的 `_legacy_to_report` | `plugins/reviews_consistency.py` 加 ci 路径全量扫描；`registry.yaml:190` triggers 加 `ci` | `audit.py:calc_exit_code` 不动（已正确） |
| **FG-002** | `.claude/settings.json:29` matcher（单行） | — | `plugins/protect_branch.py:27` `WRITE_TOOLS` 已就位 |
| **FG-003** | `run.py:281` `filter_gates`；`run.py:333` `_validate_phase_args`；4 个 plugin 删 changed_files precheck | `lib/phase_enum.py` 新增 `load_adjacent_phases()` | `registry.yaml` 各 gate 的 `applies_when` 字段（语义不变，消费方变） |
| **FG-004** | `run.py:516` `_handle_escape_hatch`；`run.py:143` `parse_args` (alias)；`triggers/submit.py:74-76`；`plugins/base_reachable.py:58` | `plugins/{branch_match,phase_in_set,ahead_of_origin}.py` 三新 plugin；`registry.yaml:313` escape hatch 加 `skips_gates_with_tag`；`registry.yaml` 各 gate entry 新增 `tags` 字段（可选） | — |
| **FG-005** | `plugins/traceability.py:39,160` precheck + `_feature_mentioned`；`plugins/pr_state.py:82,124` gh 失败 + CLOSED；`pyproject.toml`；`.github/workflows/quality-check.yml:31` | `[tool.ruff]` 新段；CI workflow 加 pytest/ruff step | `Decision` 枚举（来源：scripts/gates/plugins/base.py:43）不动，INFO 语义通过 `vars["severity_hint"]` 实现 |

## 3. 跨组接口契约（共享数据结构）

本节列出 5 组 FG **共享/扩展**的接口，避免重复定义或冲突。

### 3.1 `Report.vars["warnings"]` 语义变更（FG-001 引入，影响渲染层）

- **当前**：plugin warning-only 时返回 `Decision.PASS`，warnings 入 `vars["warnings"]`
- **修改后**：plugin warning-only 时返回 `Decision.FAIL`（让 audit 层 `has_warning_fail` 触发），warnings 仍入 `vars["warnings"]`
- **副作用**：audit log 渲染中"warning-only 现状"从 PASS 列改入 FAIL 列；非 strict 仍 exit 0 但显示位置变化（来源：requirements/REQ-2026-005/artifacts/tech-feasibility.md:18）
- **release notes 必须说明**

### 3.2 `registry.yaml` schema 扩展（FG-004 引入，FG-001/003/005 共用）

- 新增可选字段 `gates[*].tags: list[str]`（默认 `[]`）
- 新增可选字段 `escape_hatches[*].skips_gates_with_tag: list[str]`（已有 `legacy-requirement` 用法，复用，来源：scripts/gates/registry.yaml:308）
- 新增/扩展可选字段 `gates[*].applies_when.{changed_files,target_phase,current_phase_in,transition,requires}`（已有声明，本次仅扩展 runner 消费）
- S1-S10 schema 校验需同步更新允许 `tags` 字段（详见末尾待澄清清单第 1 条）

### 3.3 `meta.legacy` 字段语义扩展（FG-005 复用）

- 来源：context/team/engineering-spec/meta-schema.yaml:131 已定义 `legacy: optional boolean`
- **现有语义**：豁免 reviewer-verdict 体系（仅 `check_reviews` 短路）
- **新语义**（FG-005 D-007）：runner `filter_gates` 阶段额外检查；`legacy=true` 时也跳过 `GATE-TRACEABILITY`
- meta-schema.yaml 注释需补充新行为说明（无字段定义改动）

### 3.4 `Decision` 枚举不扩展（FG-005 接受现状）

- 来源：scripts/gates/plugins/base.py:43 仅 PASS/FAIL/SKIP 三态
- **决策**：不引入 INFO 态（避免影响所有插件契约）；INFO 语义用 `Decision.PASS + vars["severity_hint"] = "info"` 实现
- 影响 plugin：`pr_state.py`（CLOSED 状态）

### 3.5 `--bypass-review-blockers` argparse alias（FG-004，对外 CLI 契约）

- 新增 option string `--bypass-review-blockers`（dest `force_with_blockers`）
- 旧 option string `--force-with-blockers` 保留 alias，命中时 stderr 打 `[DEPRECATED] use --bypass-review-blockers instead, removed at 2026-11-01`
- 两 option string 不同，不触发 argparse `ArgumentError`（同 dest 不同 option 合法）
- `submit.py` 同步透传 `--bypass-review-blockers`

### 3.6 `[tool.ruff]` 配置（FG-005 引入）

```toml
[tool.ruff]
select = ["E", "W", "F"]
line-length = 120
```

- 不 ignore E501（与 line-length 配合生效）
- pyproject.toml 现有 `[tool.pytest.ini_options]` 段不动（来源：pyproject.toml:1）

## 4. 实施 DAG（含前置条件）

```
[前置 1] FG-003 baseline 抓取（本地 5 次取中位数）
            │
[前置 2] FG-005 ruff 历史问题预扫
            │
[前置 3] FG-004 escape hatch 现有调用清查
            │
[前置 4] FG-004 registry tags schema 兼容性确认
            │
            ▼
   ┌────────────────────────────────────────────────────┐
   │  实施顺序（5 组无强依赖，可并行；推荐串行视角）：   │
   │                                                    │
   │  FG-002 (单行 matcher)                             │
   │    └─→ FG-001 (strict + F8)                        │
   │          └─→ FG-005 (CI lint 加 step)              │
   │                                                    │
   │  FG-004 (escape hatch + submit) ─── 独立           │
   │  FG-003 (registry SoR + phase 相邻) ─── 独立      │
   │     （baseline 通过后实施，filter_gates 与         │
   │     plugin precheck 删除同 PR）                    │
   └────────────────────────────────────────────────────┘
```

## 5. 风险汇总（跨组）

| # | 类别 | 描述 | 缓解 |
|---|---|---|---|
| X1 | release | FG-001 修改后 audit log 渲染中"warning-only"位置变化，可能让 CI 监控误报 | release notes 显式说明；CI dashboard 提前对齐 |
| X2 | schema | FG-004 引入 `tags` 字段需 S1-S10 兼容；FG-003 让 `applies_when` 子字段从可选文档变为运行时消费 | 修改 schema 校验同 PR；新增 `test_registry_schema_compat.py` |
| X3 | 行为 | meta.legacy 语义扩展（豁免 traceability）后，REQ-2026-001~003 等历史完成态 REQ 的 submit 流程行为变化（之前会 stale-review 拦下，现在彻底跳过） | 仅历史 REQ 受影响，且都已 completed/PR-merged，不会主动 submit；新需求需明确不允许设 legacy=true |
| X4 | CI | FG-005 ruff 加入 CI 后首次跑可能扫出大量历史问题 | 严格按"前置 2"预扫 + auto-fix PR 先行 |

## 6. 验证矩阵（与 requirement.md §6 用户场景对应）

| 场景 | 涉及 FG | 验证手段 | 对应实施 §（tech-feasibility） |
|---|---|---|---|
| 1 CI strict 拦 warning | FG-001 | `python3 scripts/gates/run.py --trigger=ci --req=REQ-2026-005 --strict` exit=1 | §1.5 |
| 2 develop 分支 MultiEdit 被拦 | FG-002 | 人工 testing | §2.5 |
| 3 phase 跳跃被拦 | FG-003 | dry-run `--from=bootstrap --to=testing` exit=2 | §3.5 |
| 4 escape hatch 不放 workspace dirty | FG-004 | dry-run with `--bypass-review-blockers` | §4.5 |
| 5 submit 分支不匹配被拦 | FG-004 | `submit.py --dry-run` 显示 `GATE-BRANCH-MATCH` | §4.5 |
| 6 CI pytest + ruff 红灯 | FG-005 | quality-check workflow 跑 pytest/ruff | §5.5 |

## 待澄清清单

1. **S1-S10 registry schema 是否当前禁止额外字段**（决定 FG-004 引入 `tags` 字段是否需同步改 schema 校验）：S1-S10 校验代码位置 [待用户确认]——需在 detail-design 阶段查证 `scripts/gates/registry.py` 或 `scripts/lib/check_registry.py` 的具体实现路径
