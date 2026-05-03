---
id: REQ-2026-005
title: 门禁系统加固 · 详细设计
created_at: "2026-05-01 19:40:00"
refs-detail-design: true
---

# REQ-2026-005 · 详细设计

> 本文聚焦"接口签名 + 数据契约 + 错误处理 + reviewer 强收口的两项防护设计"。架构上下文见 outline-design.md。

## 1. FG-001 详细设计：strict 模式 + CI 兜底

### 1.1 接口签名

修改 `_legacy_to_report(gate_id: str, legacy: LegacyReport) -> Report` 的语义（来源：scripts/gates/plugins/plan_freshness.py:133）：

```python
# 修改前（错误）：errors → FAIL，纯 warnings → PASS
# 修改后（正确）：errors → FAIL，纯 warnings → FAIL（让 has_warning_fail 触发）
def _legacy_to_report(gate_id: str, legacy: LegacyReport) -> Report:
    findings = legacy.findings()
    errors = [f for f in findings if f[1] == LegacySeverity.ERROR]
    warnings = [f for f in findings if f[1] == LegacySeverity.WARNING]
    if errors:
        # ... 同前 ...
        return Report(decision=Decision.FAIL, code="...", ...)
    if warnings:  # 新增分支
        first = warnings[0]
        return Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code="R-WARNING-ONLY",  # 新错误码
            message=f"{first[0]}: {first[2]}: {first[3]}",
            fix_hint="该 gate 仅含 warning；strict 模式下视为失败",
            vars={"warnings": [list(f) for f in warnings]},
        )
    return Report(decision=Decision.PASS, vars={})
```

应用于 3 个 plugin：`meta_schema._legacy_to_report`（来源：scripts/gates/plugins/meta_schema.py:130）、`sourcing._legacy_to_report`（来源：scripts/gates/plugins/sourcing.py:122）、`plan_freshness._legacy_to_report`（来源：scripts/gates/plugins/plan_freshness.py:133）。

`index_integrity` 经核查同样使用 `_legacy_to_report` 模式（来源：scripts/gates/plugins/index_integrity.py:113），同步修改。

### 1.2 reviews_consistency CI 路径

修改 `precheck`（来源：scripts/gates/plugins/reviews_consistency.py:57）：

```python
def precheck(self, ctx: GateContext) -> Skip | None:
    if ctx.trigger == "ci":
        return None  # CI 路径走全量扫描，不依赖 staged
    if ctx.trigger != "pre-commit":
        return Skip(...)
    return None
```

新增 `run_ci_full_scan(ctx)`：

```python
def _run_ci_full_scan(self, ctx: GateContext) -> Report:
    """CI trigger：扫全量 requirements/*/meta.yaml 与 reviews/*.json 一致性。"""
    inconsistent: list[str] = []
    for meta_path in REPO_ROOT.glob("requirements/*/meta.yaml"):
        meta = yaml.safe_load(meta_path.read_text())
        for phase, info in (meta.get("reviews") or {}).items():
            latest = info.get("latest") if isinstance(info, dict) else None
            if not latest:
                continue
            verdict = REPO_ROOT / "requirements" / meta["id"] / "reviews" / f"{phase}-001.json"  # 简化：实际遍历 history 找匹配
            if not verdict.exists():
                inconsistent.append(f"{meta['id']}/{phase}: meta.latest={latest} 但 verdict 文件缺失")
    if inconsistent:
        return Report(decision=Decision.FAIL, code="R-REVIEWS-INCONSISTENT", message="\n".join(inconsistent), ...)
    return Report(decision=Decision.PASS)
```

### 1.3 错误码

| 错误码 | 严重度 | 触发场景 |
|---|---|---|
| `R-WARNING-ONLY` | 由 registry severity 决定（warning gate → warning，error gate → error） | plugin 仅含 warnings 但无 errors |
| `R-REVIEWS-INCONSISTENT` | error | CI 全量扫发现 reviews 字段与 verdict 文件不一致 |

## 2. FG-002 详细设计：Hook matcher

### 2.1 修改

`.claude/settings.json:29`：

```jsonc
// 修改前
"matcher": "Bash|Edit|Write"
// 修改后
"matcher": "Bash|Edit|Write|MultiEdit"
```

无代码层改动。`protect_branch.py:27` `WRITE_TOOLS` 已含 `MultiEdit`，本次不动。

## 3. FG-003 详细设计：registry SoR + phase 相邻

### 3.1 `filter_gates` 升级签名

```python
def filter_gates(
    registry_data: dict, ctx: GateContext, *, ignore_changed_files: bool = False
) -> list[dict]:
    """按 trigger + applies_when 全部 5 字段过滤。

    新增字段消费：
      - applies_when.changed_files: list[str] (gitignore-style)
      - applies_when.target_phase: str | null
      - applies_when.current_phase_in: list[str]
      - applies_when.transition: str (格式 "from->to")
      - applies_when.requires: list[str] (meta.<field> 必须非空)

    legacy grandfather: ctx.meta.get("legacy") is True 时跳过 tags 含
    "legacy-bypass" 的 gate（含 GATE-TRACEABILITY）。
    """
```

来源：scripts/gates/run.py:281

### 3.2 phase 相邻表

`scripts/lib/phase_enum.py` 新增：

```python
def load_adjacent_phases() -> frozenset[tuple[str, str]]:
    """从 enums.phase 有序列表推导相邻关系，仅前进方向。

    返回如 {("bootstrap","definition"), ("definition","tech-research"), ...}
    """
    canonical = list(_load_phase_enum_list())
    return frozenset((canonical[i], canonical[i+1]) for i in range(len(canonical)-1))
```

修改 `_validate_phase_args`（来源：scripts/gates/run.py:333）：

```python
def _validate_phase_args(args, canonical: frozenset) -> tuple[int, str] | None:
    # 已有：phase 在 canonical 集合
    # 新增：from 和 to 都非空时，前进方向必须相邻
    if args.from_phase and args.to_phase:
        adjacent = phase_enum.load_adjacent_phases()
        from_idx = list(canonical).index(args.from_phase)
        to_idx = list(canonical).index(args.to_phase)
        if to_idx > from_idx:  # 前进方向
            if (args.from_phase, args.to_phase) not in adjacent:
                return (2, f"非法 phase 跳跃 {args.from_phase}→{args.to_phase}（必须相邻前进）")
        # 回退方向（to_idx <= from_idx）不校验
    return None
```

### 3.3 错误码

| 错误码 | 严重度 | 触发场景 |
|---|---|---|
| `R-INVALID-PHASE-TRANSITION` | error | 前进方向 from→to 不相邻 |

## 4. FG-004 详细设计：escape hatch + submit 链路

### 4.1 registry tags 字段（schema 扩展）

```yaml
gates:
  - id: GATE-REVIEW-VERDICT
    severity: error
    triggers: [phase-transition, submit, ci]
    tags: [review-verdict]   # 新增可选字段（gate entry 之前不带 tags 字段）
    ...
escape_hatches:
  force-with-blockers:
    triggers: [submit, phase-transition]
    skips_gates_with_tag: [review-verdict]   # 新增（复用 legacy-requirement 既有字段语义）
    require_reason: true
```

**关键约束**：`registry.yaml:313` 的 force-with-blockers entry 当前**不含** `skips_gates_with_tag` 字段，本次必须新增；不加则 `_handle_escape_hatch` 的 tags 交集判定永远空集 → 永远不放行 → 该 escape hatch 实际失效。

`skips_gates_with_tag` 字段本身**不是新概念**——`registry.yaml:309` 的 `legacy-requirement` 已使用同字段（来源：scripts/gates/registry.yaml:309）；本次只是把它扩到 `force-with-blockers`，并在 gate entry 上新增 `tags: list[str]` 可选字段做绑定。

**S1-S10 兼容性已确认**：经核查 `_validate_one_entry`（来源：scripts/gates/registry.py:157），S1-S10 仅做"必填字段 + 枚举值 + 格式"正向校验，**无白名单严格模式**，因此 entry 多写一个 `tags` 字段不会被拒绝——本需求不需要改 `registry.py` 的 schema 校验代码。

### 4.2 `_handle_escape_hatch` 升级

```python
def _handle_escape_hatch(...):
    # 已有：检查 force_reason + trigger
    # 新增：失败 gate 必须命中 skips_gates_with_tag 才能放行
    failed_tags = set(failed_gate_entry.get("tags") or [])
    skips_tags = set(escape_entry.get("skips_gates_with_tag") or [])
    if not (failed_tags & skips_tags):
        # 不命中标签 → 不放行
        return False, False  # 走正常 fail 路径
    return True, False  # 放行
```

### 4.3 argparse alias

```python
# scripts/gates/run.py:143 parse_args
p.add_argument(
    "--bypass-review-blockers",
    dest="force_with_blockers",
    default=None,
    metavar="REASON",
    help="（推荐）绕过 review-blocker 类 gate；等价于 --force-with-blockers",
)
p.add_argument(
    "--force-with-blockers",
    dest="force_with_blockers",
    default=None,
    metavar="REASON",
    help="[DEPRECATED 2026-11-01] 请使用 --bypass-review-blockers",
)

# main() 内 parse_args 之后
if any(a.startswith("--force-with-blockers") for a in (argv or sys.argv[1:])):
    print("[DEPRECATED] use --bypass-review-blockers instead, removed at 2026-11-01",
          file=sys.stderr)
```

### 4.4 三个新 plugin

```python
# scripts/gates/plugins/branch_match.py
from .base import Gate, GateContext, Report, Decision, Severity

class GateBranchMatch(Gate):
    id = "GATE-BRANCH-MATCH"
    triggers = {"submit"}
    severity = Severity.ERROR  # 类型必须是 Severity 枚举（base.py:110）不是字符串

    def run(self, ctx: GateContext) -> Report:
        current = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=REPO_ROOT, text=True
        ).strip()
        expected = ctx.meta.get("branch")
        if current != expected:
            return Report(
                gate_id=self.id, decision=Decision.FAIL,
                code="R-BRANCH-MISMATCH",
                message=f"当前分支 {current!r} 与 meta.branch {expected!r} 不一致",
                fix_hint=f"git switch {expected}",
            )
        return Report(decision=Decision.PASS)
```

类似 `GateBypassPhaseInSet`（`R-PHASE-NOT-SUBMITTABLE`）和 `GateAheadOfOrigin`（`R-NOTHING-TO-PUSH`）—— 三 plugin 均 `severity = Severity.ERROR`、`triggers = {"submit"}`、`Report.vars = {}` 不写额外字段（仅 fail-or-pass，无需向 reporter 传递信息）。

### 4.5 `base_reachable._resolve_base_branch` 修复

```python
# scripts/gates/plugins/base_reachable.py:58
def _resolve_base_branch(ctx: GateContext) -> str:
    target = ctx.cli_flags.get("target") if ctx.cli_flags else None
    if target:
        return target
    return ctx.meta.get("base_branch") or _FALLBACK_BRANCHES[0]
```

`triggers/submit.py:74-89` 同步透传 `--target`：

```python
parser.add_argument("--target", dest="target", help="目标 base 分支（覆盖 meta.base_branch）")
# build_runner_argv 时：
if args.target:
    runner_argv.extend(["--target", args.target])
```

run.py 也需新增 `--target` argparse 参数（`dest=target`），并在 `build_context` 时塞到 `cli_flags["target"]`。

### 4.6 错误码汇总

| 错误码 | 严重度 | 触发场景 |
|---|---|---|
| `R-BRANCH-MISMATCH` | error | 当前分支 ≠ meta.branch |
| `R-PHASE-NOT-SUBMITTABLE` | error | meta.phase ∉ {development, testing} |
| `R-NOTHING-TO-PUSH` | error | 本地相对 origin/<base> 无新 commit |

## 5. FG-005 详细设计：降级路径收紧 + CI lint

### 5.1 traceability 升级

```python
# scripts/gates/plugins/traceability.py:39
def precheck(self, ctx: GateContext) -> Skip | None:
    if ctx.trigger == "phase-transition" and ctx.to_phase == "testing":
        return None
    if ctx.trigger == "submit" and ctx.requirement_id:
        return None  # 新增
    return Skip(...)

# scripts/gates/plugins/traceability.py:160
def _feature_mentioned(text: str, feature_id: str) -> bool:
    pattern = r"(?<![A-Za-z0-9-])" + re.escape(feature_id) + r"(?![A-Za-z0-9-])"
    return re.search(pattern, text) is not None
```

### 5.2 pr_state 降级

```python
# scripts/gates/plugins/pr_state.py:82
def _fetch_pr_state(branch: str) -> tuple[str | None, dict]:
    try:
        out = subprocess.check_output(["gh", "pr", "view", branch, "--json", "state"], ...)
    except subprocess.CalledProcessError:
        # 新增 fallback：本地 git ls-remote
        try:
            subprocess.check_call(["git", "ls-remote", "origin", branch], ...)
            return None, {"gh_call_failed": True, "ls_remote_ok": True}
        except subprocess.CalledProcessError:
            return None, {"gh_call_failed": True, "ls_remote_failed": True}
    ...

# scripts/gates/plugins/pr_state.py:124
if state == "CLOSED":
    return Report(
        gate_id=self.id, decision=Decision.PASS,
        vars={"pr_state_closed": True, "severity_hint": "info"},
        message=f"PR {branch} 状态 CLOSED；用户应确认是否需要重开 PR",
    )
```

### 5.3 ruff 集成（含强收口阈值表）

`pyproject.toml` 新增：

```toml
[tool.ruff]
select = ["E", "W", "F"]
line-length = 120
```

`.github/workflows/quality-check.yml:25` 加入 ruff：

```yaml
- name: Install dependencies
  run: pip install pyyaml ruamel.yaml pathspec ruff
```

`.github/workflows/quality-check.yml:37` 之后追加 step：

```yaml
- name: pytest
  run: pytest tests/gates/ -v

- name: ruff lint
  run: ruff check scripts/ --select=E,W,F
```

**ruff 历史问题预扫量化阈值表**（reviewer 强收口）：

```bash
# 实施前本地预扫
ruff check scripts/ --select=E,W,F --statistics
```

| 历史问题数 | 处理策略 |
|---|---|
| ≤ 50 | `ruff check scripts/ --fix` 一次性修复，与 CI step 合入同一 PR |
| 51 ~ 200 | 独立 auto-fix PR 先行（仅 fix，不加 CI step）；CI step 在 fix PR 合入后单独 PR |
| > 200 | 降级 `select=["F"]` 起步（仅 pyflakes），auto-fix 后再分 PR 渐进收紧到 [E,W,F] |
| 含手动修复（auto-fix 不能解）| 拆 5~10 个 commit 按文件分批，确保每个 commit ≤ 20 行差异，便于 review |

### 5.4 meta.legacy 误用防护（reviewer 强收口）

`scripts/gates/plugins/meta_schema.py` 新增校验规则：

```python
def _check_legacy_misuse(meta: dict, report) -> None:
    """legacy=true 仅当 phase ∈ {completed, archived} 才合法。"""
    if meta.get("legacy") is True:
        if meta.get("phase") not in {"completed", "archived"}:
            report.add(
                "meta.yaml",
                Severity.ERROR,
                "R-LEGACY-MISUSE",
                f"legacy=true 不允许在 phase={meta.get('phase')!r} 阶段使用；"
                f"仅 completed/archived 阶段可标记历史豁免",
                fix_hint="移除 meta.legacy 字段，或确认需求确实已 completed/archived",
            )
```

### 5.5 错误码汇总

| 错误码 | 严重度 | 触发场景 |
|---|---|---|
| `R-LEGACY-MISUSE` | error | meta.legacy=true 但 phase ∉ {completed, archived} |
| `R-LS-REMOTE-FAILED`（仅 vars 标记） | warning | gh+ls-remote 双失败 |

## 6. 跨组数据契约（vars 字段命名约定）

防止 5 组 FG 修改后 `Report.vars` 字段冲突：

| vars 字段 | 用途 | 写入方 | 读取方 |
|---|---|---|---|
| `warnings` | warning finding 详情列表 | FG-001 修改后的 plugin | audit 渲染 |
| `severity_hint` | "info" / "warning" / "error" 提示 | FG-005 pr_state 等 | reporter 渲染（CLOSED 用 info） |
| `pr_state_closed` | bool | FG-005 pr_state | UI 提示 |
| `gh_call_failed` | bool | FG-005 pr_state | log + reporter |
| `ls_remote_ok` / `ls_remote_failed` | bool | FG-005 pr_state | log |
| （无）| FG-004 三个新 plugin（branch_match / phase_in_set / ahead_of_origin）**不写** Report.vars | — | — |

无字段冲突；`severity_hint` 不参与 strict 升级判定（参见本文 §1 FG-001 设计：strict 升级仅判 `decision != PASS`）。FG-004 三 plugin 仅做 fail-or-pass 判定，无需向下游传递额外字段。

## 7. 时序图：phase-transition gate 执行流（FG-003 + FG-004 组合）

```
user: /requirement:next
  → run.py main()
    → parse_args (alias deprecation 检测)
    → _validate_phase_args (FG-003 相邻校验)
      ├─ 非法 → exit 2
      └─ 合法
        → build_context (cli_flags["target"] 透传)
        → filter_gates (FG-003: applies_when 5 字段消费 + legacy grandfather)
          → 对每个候选 gate 跑 plugin.run
            → 若 FAIL 且 force_with_blockers + tags 命中
              → escape_hatch 放行
            → 否则正常 fail
        → calc_exit_code (audit.py:111 不变)
          → strict + has_warning_fail → exit 1
```

## 8. 测试矩阵

| Test ID | FG | 类型 | 命令 |
|---|---|---|---|
| TC-FG1-1 | FG-001 | unit | `pytest tests/gates/test_legacy_to_report_warning_fail.py` |
| TC-FG1-2 | FG-001 | integration | `python3 scripts/gates/run.py --trigger=ci --req=REQ-2026-005 --strict` exit=1 |
| TC-FG2-1 | FG-002 | manual | develop 分支 MultiEdit 被拦 |
| TC-FG3-1 | FG-003 | unit | `pytest tests/gates/test_filter_gates_applies_when.py` |
| TC-FG3-2 | FG-003 | integration | `bootstrap → testing` exit=2 |
| TC-FG3-3 | FG-003 | perf | baseline +20% 内 |
| TC-FG4-1 | FG-004 | unit | `pytest tests/gates/test_branch_match.py test_phase_in_set.py test_ahead_of_origin.py` |
| TC-FG4-2 | FG-004 | integration | escape hatch tag 限定（workspace dirty 不放过） |
| TC-FG4-3 | FG-004 | integration | deprecation warning 出现 |
| TC-FG5-1 | FG-005 | unit | `pytest tests/gates/test_traceability_word_boundary.py test_pr_state_fallback.py` |
| TC-FG5-2 | FG-005 | unit | `pytest tests/gates/test_legacy_misuse.py` |
| TC-FG5-3 | FG-005 | integration | CI workflow pytest + ruff 全绿 |

## 待澄清清单

（无未决项；原 S1-S10 schema 兼容性问题已在本阶段 grep 收口——见 §4.1 关键约束段：S1-S10 仅做正向必填校验，无白名单严格模式，新增 `tags` 字段天然兼容，本需求不需要改 `registry.py` 校验代码。）
