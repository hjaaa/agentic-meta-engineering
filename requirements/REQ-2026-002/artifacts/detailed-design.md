---
id: REQ-2026-002
title: 统一门禁系统 · 详细设计
created_at: "2026-04-27 21:35:00"
refs-detail-design: true
---

# REQ-2026-002 · 详细设计

## 1. registry.yaml 字段精确定义

```yaml
schema_version: "1.0"

gates:
  - id: GATE-META-SCHEMA              # 全局唯一；格式 ^GATE-[A-Z][A-Z0-9-]+$
    plugin: meta_schema               # plugins/<plugin>.py（蛇形）
    severity: error                   # error | warning | info
    triggers:                         # 该 gate 在哪些事件下生效
      - pre-commit
      - phase-transition
      - submit
      - ci
      - post-dev
    applies_when:                     # 触发后是否真跑（boolean 表达式简集）
      changed_files:                  # 任一 glob 命中 → 生效（pre-commit 用）
        - "requirements/*/meta.yaml"
      target_phase: null              # 目标 phase（phase-transition 用，null = 任意）
      current_phase_in: []            # 当前 phase（submit 用，空 = 任意）
      transition: null                # "from->to" 字符串（精确匹配）
      requires:                       # 路径或字段非空（任意条件均可）
        - "meta.pr_number"
    dependencies:                     # gate id 列表，必须先跑
      - GATE-WORKSPACE-CLEAN
    side_effects: none                # none | write_state；write_state 必须实现 rollback
    failure_message: |                # 失败时给用户看的多行 hint，支持 {var} 占位
      {gate_id} 失败：{message}
      修复建议：{fix_hint}
    escape_hatch:                     # 可空；本 gate 是否允许豁免
      cli_flag: --skip-meta           # null 或 CLI 标志；只有 submit/phase-transition 接受
      env_var: null                   # null 或环境变量名
      requires_reason: true           # true 时必须填 reason，写入 audit
      audit: true                     # 写 audit log
    tests:                            # 强制；指向 tests/gates/test_<plugin>.py 的 fixture 名
      fixtures: [pass, fail, skip]

escape_hatches:                       # 全局 escape 策略（非 gate 级，是流程级）
  - id: legacy-requirement
    field: meta.legacy
    skips_gates_with_tag: [review-verdict]
    requires_reason: true
    audit: true

  - id: force-with-blockers
    cli_flag: --force-with-blockers
    triggers: [submit]
    requires_reason: true             # CLI 形式：--force-with-blockers="<reason>"
    audit: true

  - id: bypass-bash-write
    env_var: CLAUDE_GATES_BYPASS
    requires_reason_var: CLAUDE_GATES_BYPASS_REASON
    audit: true
```

**Schema 校验规则**（registry 加载期跑，违反即拒绝启动 runner）：

| 规则 | 描述 |
|---|---|
| S1 | `id` 必须满足 `^GATE-[A-Z][A-Z0-9-]+$` 且全局唯一 |
| S2 | `plugin` 对应 `plugins/<plugin>.py` 必须存在且导出 `Gate` 子类 |
| S3 | `triggers` 中每个值必须 ∈ {pre-tool-use, pre-commit, phase-transition, submit, ci, post-dev} |
| S4 | `severity` 必须 ∈ {error, warning, info} |
| S5 | `dependencies` 中每个 id 必须存在（不允许悬挂引用） |
| S6 | `dependencies` 拓扑排序无环（graphlib.CycleError） |
| S7 | `side_effects=write_state` 时 plugin 必须实现 `rollback()` 方法 |
| S8 | `tests.fixtures` 至少含 `[pass, fail, skip]` 三个用例（来源：requirements/REQ-2026-002/artifacts/requirement.md:54） |
| S9 | `applies_when.requires` 中每项必须以 `meta.` 前缀引用 meta.yaml 已知字段（dot path），非 file glob |
| S10 | `escape_hatch.cli_flag` 非 null 时，gate.triggers 必须包含 `submit` 或 `phase-transition`（CLI flag 仅这两类 trigger 接受） |

## 2. Python 接口签名

### 2.1 plugins/base.py

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Decision(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class GateContext:
    trigger: Literal["pre-tool-use", "pre-commit", "phase-transition",
                     "submit", "ci", "post-dev"]
    requirement_id: Optional[str] = None
    from_phase: Optional[str] = None
    to_phase: Optional[str] = None
    changed_files: list[str] = field(default_factory=list)
    cli_flags: dict = field(default_factory=dict)
    env: dict = field(default_factory=dict)        # 显式注入需要的环境变量
    actor: Literal["claude-code", "human", "ci"] = "claude-code"
    meta: dict = field(default_factory=dict)       # meta.yaml 解析结果
    extra: dict = field(default_factory=dict)      # trigger 特定字段：tool_name / file_path / command
    staged_writes: list[tuple[str, str, object]] = field(default_factory=list)
    # 暂存待写：(path, dot_key, value)；由 side_effects=write_state 的 plugin 在 run() 中 append；
    # runner 在所有 gate pass 后调 plugin.commit_staged_writes() 落盘；fail 路径直接丢弃。


@dataclass
class Report:
    gate_id: str
    decision: Decision
    code: Optional[str] = None                     # 如 R005、E001、CR-3、PR-MERGED
    message: Optional[str] = None
    fix_hint: Optional[str] = None
    vars: dict = field(default_factory=dict)


@dataclass
class Skip:
    reason: str


class Gate(ABC):
    """Gate 抽象基类。

    注意：applies_when / dependencies 仅由 registry.yaml 承载，Gate 类不重复声明。
    runner 在 filter / topo 阶段直接读 registry，不通过 Gate 实例查询。
    """
    id: str
    severity: Severity
    triggers: set[str]
    side_effects: Literal["none", "write_state"] = "none"

    @abstractmethod
    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """返回 Skip 即跳过；None 即继续 run。"""

    @abstractmethod
    def run(self, ctx: GateContext) -> Report:
        """主体检查逻辑，必须返回 Report。
        side_effects=write_state 的 plugin 在此 append ctx.staged_writes，
        不直接落盘；落盘由 runner 在所有 gate pass 后统一调 commit_staged_writes()。
        """

    def commit_staged_writes(self, ctx: GateContext) -> None:
        """side_effects=write_state 时实现；把暂存写落盘。runner 在 try 块成功结束后调用。"""
        pass

    def rollback(self, ctx: GateContext) -> None:
        """side_effects=write_state 时实现：清理暂存或回滚已 commit 的写。"""
        pass
```

### 2.2 run.py 主入口

```python
def main(argv: list[str]) -> int:
    args = parse_args(argv)                            # --trigger / --req / --from / --to / --strict / --dry-run / ...
    ctx = build_context(args)                          # 构造 GateContext，加载 meta.yaml
    registry = load_registry()                         # YAML → 内存对象 + S1~S8 校验
    candidates = filter_gates(registry, ctx)           # trigger + applies_when 过滤
    plan = topological_sort(candidates)                # 依赖拓扑

    snapshots = stash_state(ctx)                       # shutil.copy2 备份 meta.yaml
    executed: list[Gate] = []
    reports: list[Report] = []
    rollback_failed = False

    try:
        for gate in plan:
            skip = gate.precheck(ctx)
            if skip:
                reports.append(Report(gate.id, Decision.SKIP, message=skip.reason))
                continue
            executed.append(gate)
            r = gate.run(ctx)              # plugin 可能 append ctx.staged_writes
            reports.append(r)
            if r.decision == Decision.FAIL and gate.severity == Severity.ERROR:
                raise GateFailed(r)
        # 所有 gate pass：把 staged_writes 落盘（H1 事务化关键步骤）
        for g in executed:
            if g.side_effects == "write_state":
                g.commit_staged_writes(ctx)
    except GateFailed as e:
        # fail 路径：staged_writes 直接丢弃（无需写盘 → 无需 rollback 写盘）；
        # 仅对已 commit 的（理论上不存在，因 commit 在所有 gate pass 之后）调 rollback
        for g in reversed(executed):
            try:
                g.rollback(ctx)
            except Exception as ex:
                rollback_failed = True
                log_blocker(ctx, f"gate-rollback-failed: {g.id}: {ex}")
        restore_state(ctx, snapshots)
        ctx.staged_writes.clear()

    audit = build_audit(ctx, reports, rollback_failed)
    write_audit(audit)
    return calc_exit_code(reports, args.strict)
```

### 2.3 audit JSON schema

写入路径 `scripts/gates/audit/<YYYY-MM>/<trigger>-<timestamp>.json`：

```json
{
  "schema_version": "1.0",
  "trigger": "phase-transition",
  "timestamp": "2026-04-27 21:35:00",
  "actor": "claude-code",
  "requirement_id": "REQ-2026-002",
  "from_phase": "outline-design",
  "to_phase": "detail-design",
  "passed": ["GATE-META-SCHEMA", "GATE-PLAN-FRESH"],
  "failed": [
    {
      "gate_id": "GATE-REVIEW-VERDICT-R005",
      "code": "R005",
      "message": "...",
      "fix_hint": "..."
    }
  ],
  "skipped": [{"gate_id": "GATE-PR-MERGED-STATE", "reason": "no pr_number recorded"}],
  "escape_used": null,
  "rollback_failed": false,
  "exit_code": 1
}
```

## 3. Plugin 详细规格

### 3.1 plugins/review_verdict.py（关 H1）

承载 R001~R007 全部规则。**关键改造**：R005 的 stale 写回从原 `check_reviews.py:152` 直接 `meta.yaml.dump` 改为：

```python
class ReviewVerdictGate(Gate):
    side_effects = "write_state"

    def run(self, ctx):
        report = self._run_all_R(ctx)
        # R005 命中时仅在 ctx.staged_writes 暂存待写内容，不立即落盘
        if self._r005_drift_detected:
            ctx.staged_writes.append(("meta.yaml", "reviews.<phase>.stale", True))
        return report

    def commit_staged_writes(self, ctx):       # runner 在所有 gate pass 后调
        for path, key, value in ctx.staged_writes:
            atomic_yaml_update(path, key, value)

    def rollback(self, ctx):
        # ctx.staged_writes 自动丢弃；若 commit 后才 fail，由 runner.restore_state 恢复
        ctx.staged_writes.clear()
```

**单测三路径**（来源：requirements/REQ-2026-002/plan.md:40）：
- `test_r005_drift_then_pass_commits_stale`：drift 触发 → 后续 R 全过 → meta.yaml stale=true 落盘
- `test_r005_drift_then_fail_rolls_back`：drift 触发 → 后续某 R fail → meta.yaml 不变
- `test_r005_alone_fails_no_partial_write`：仅 R005 fail → meta.yaml 不变

### 3.2 plugins/pr_state.py（关 H4）

```python
class PrMergedStateGate(Gate):
    id = "GATE-PR-MERGED-STATE"
    triggers = {"submit"}
    side_effects = "none"

    def precheck(self, ctx):
        if not ctx.meta.get("pr_number"):
            return Skip("no pr_number recorded")
        return None

    def run(self, ctx):
        pr_num = ctx.meta["pr_number"]
        # gh CLI 调用：gh pr view <num> --json state,mergedAt
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_num), "--json", "state,mergedAt"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        if data["state"] == "MERGED":
            return Report(
                gate_id=self.id, decision=Decision.FAIL, code="PR-MERGED",
                message=f"PR #{pr_num} 已合并（mergedAt={data['mergedAt']}）",
                fix_hint="跑 /requirement:next 推进 phase；如需新 PR，先清空 meta.pr_number",
                vars={"pr_number": pr_num, "merged_at": data["mergedAt"]},
            )
        return Report(gate_id=self.id, decision=Decision.PASS)
```

### 3.3 plugins/bash_write_protect.py（关 H5）

```python
RE_PROTECTED_PATH = re.compile(r"requirements/[^/]+/reviews/[^/]+\.json")

# 覆盖所有 shell 写法：> / >> / tee / mv / cp / python -c 的 open(...,'w') /
# heredoc（cat <<EOF > file / cat <<-EOF >> file）/ printf 重定向 / dd of=
RE_WRITE_OPS = re.compile(
    r"("
    r">>?\s*['\"]?[^|;&]*?requirements/.+/reviews/.+\.json"          # > / >>
    r"|tee\s+(-a\s+)?['\"]?[^|;&]*?requirements/.+/reviews/.+\.json"  # tee / tee -a
    r"|mv\s+\S+\s+['\"]?[^|;&]*?requirements/.+/reviews/.+\.json"     # mv
    r"|cp\s+\S+\s+['\"]?[^|;&]*?requirements/.+/reviews/.+\.json"     # cp
    r"|python3?\s+-c\s+['\"].*open\(.*?requirements/.+/reviews/.+\.json.*?['\"]w['\"]"
    r"|cat\s+<<-?\s*['\"]?\w+['\"]?\s+>>?\s*['\"]?[^|;&]*?requirements/.+/reviews/.+\.json"  # heredoc
    r"|printf\s+.*?>\s*['\"]?[^|;&]*?requirements/.+/reviews/.+\.json"  # printf >
    r"|dd\s+.*?of=['\"]?[^|;&]*?requirements/.+/reviews/.+\.json"       # dd of=
    r")"
)

class BashWriteProtectGate(Gate):
    id = "GATE-BASH-WRITE-PROTECT"
    triggers = {"pre-tool-use"}

    def precheck(self, ctx):
        if ctx.extra.get("tool_name") != "Bash":
            return Skip("not Bash tool")
        return None

    def run(self, ctx):
        cmd = ctx.extra.get("command", "")
        if not RE_WRITE_OPS.search(cmd):
            return Report(gate_id=self.id, decision=Decision.PASS)

        # 双轨白名单（来源：requirements/REQ-2026-002/plan.md:96）
        if self._caller_is_save_review_sh():
            return Report(gate_id=self.id, decision=Decision.PASS,
                          vars={"whitelisted": "save-review.sh"})
        if ctx.env.get("CLAUDE_GATES_BYPASS") == "1":
            reason = ctx.env.get("CLAUDE_GATES_BYPASS_REASON", "")
            if not reason:
                return Report(gate_id=self.id, decision=Decision.FAIL,
                              code="BYPASS-NO-REASON",
                              message="CLAUDE_GATES_BYPASS=1 必须同时设置 CLAUDE_GATES_BYPASS_REASON")
            return Report(gate_id=self.id, decision=Decision.PASS,
                          vars={"whitelisted": "env-bypass", "reason": reason})

        return Report(
            gate_id=self.id, decision=Decision.FAIL, code="BASH-WRITE",
            message="Bash 试图写 reviews/*.json，但调用方不在白名单",
            fix_hint="reviews/*.json 由 save-review.sh 唯一通道维护；如需修订评审，请让 reviewer Agent 重审",
        )

    def _caller_is_save_review_sh(self) -> bool:
        # 父进程链识别：ps -p $PPID -o comm=
        # macOS comm 字段截断风险见 tech-feasibility.md 1.3 节
        try:
            ppid = os.getppid()
            for _ in range(5):                           # 向上追溯 5 层
                comm = subprocess.check_output(
                    ["ps", "-p", str(ppid), "-o", "comm="]
                ).decode().strip()
                if comm.endswith("save-review.sh"):
                    return True
                ppid_out = subprocess.check_output(
                    ["ps", "-p", str(ppid), "-o", "ppid="]
                ).decode().strip()
                ppid = int(ppid_out)
                if ppid <= 1:
                    break
        except (subprocess.CalledProcessError, ValueError):
            return False
        return False
```

### 3.4 其他 plugin

| Plugin | 对接 | 关键改造 |
|---|---|---|
| meta_schema | check_meta.py | 适配 Report API；逻辑零改 |
| index_integrity | check_index.py | 同上 |
| sourcing | check_sourcing.py | 同上 |
| plan_freshness | check_plan.py | W001/W002/W003 → severity warning |
| workspace_clean | post-dev-verify.sh 的 git status 检查 | 拆出独立 plugin |
| traceability | traceability-gate-checker Skill | 封装 Skill 调用，缓存 hash 防重复消耗 token |
| protect_branch | .claude/hooks/protect-branch.sh 的分支拦截部分 | 拆出独立 plugin，仅 pre-tool-use trigger 生效 |

## 4. 4 大触发器时序

### 4.1 phase-transition 时序

```
managing-requirement-lifecycle (next)
   │
   ├─→ python run.py --trigger=phase-transition --req=R --from=X --to=Y
   │      │
   │      ├─→ load registry → filter → topo
   │      ├─→ stash meta.yaml
   │      ├─→ for gate: precheck → run → (rollback if fail)
   │      ├─→ commit staged writes / restore on fail
   │      └─→ write audit log
   │
   └─→ exit code: 0 → 更新 meta.phase / 非 0 → 终止
```

### 4.2 submit 时序

```
/requirement:submit
   │
   ├─→ python run.py --trigger=submit --req=R [--force-with-blockers="..."]
   │      │
   │      ├─→ 复用 phase-transition 的所有 gate（review/sourcing/...）
   │      ├─→ 加 GATE-PR-MERGED-STATE / GATE-GH-AUTH / GATE-BASE-REACHABLE
   │      └─→ Report 同源（关 H3）
   │
   └─→ 若 PASS → push + open PR；若 PR-MERGED 命中 → 提示走 next
```

### 4.3 pre-tool-use 时序（关 H5）

```
Claude Code Hook (PreToolUse)
   │
   ├─→ stdin: {"tool_name": "Bash", "tool_input": {"command": "..."}}
   │
   ├─→ scripts/gates/triggers/pre_tool_use.sh 解析 stdin
   ├─→ python run.py --trigger=pre-tool-use --tool=$TOOL --command="$CMD"
   │      │
   │      ├─→ 仅跑 GATE-PROTECT-BRANCH + GATE-BASH-WRITE-PROTECT
   │      └─→ 任一 fail → exit 2（Hook 拒绝）
   │
   └─→ exit 0 放行 / exit 2 阻断
```

### 4.4 ci 时序

```
GitHub Actions (PR + push main/develop)
   │
   ├─→ python run.py --trigger=ci --strict
   │      │
   │      ├─→ for req in requirements/*/:
   │      │      ├─→ 加载 req 的 meta.yaml
   │      │      ├─→ 跑该 req 在 current_phase 应过的所有 gate
   │      │      └─→ 单需求失败不中断（来源：requirements/REQ-2026-002/artifacts/requirement.md:108）
   │      ├─→ 任一 req 含 error → exit 1
   │      └─→ 写 audit/<YYYY-MM>/ci-<timestamp>.json
   │
   └─→ CI step 单一：替代当前 5 step（来源：.github/workflows/quality-check.yml:28）
```

## 5. migration 工具

### 5.1 migration/normalize-stderr.sh

```bash
#!/usr/bin/env bash
# 用途：把 stderr 归一化以做 snapshot 对比（来源：requirements/REQ-2026-002/artifacts/requirement.md:122）
# 输入：stdin
# 输出：归一化后只保留关键前缀的行

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel)}"

sed -E \
  -e 's/\x1b\[[0-9;]*m//g'                                     `# 去 ANSI` \
  -e "s|$REPO_ROOT/||g"                                        `# 去绝对路径` \
  -e 's/[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}/<TS>/g'  `# 去时间戳` \
  -e 's/^.*?(ERROR|WARNING|✗|❌|E[0-9]+|W[0-9]+|R[0-9]+|CR-[0-9]+).*$/&/p; d'  `# 关键前缀过滤`
```

### 5.2 migration/capture-baseline.sh

```bash
#!/usr/bin/env bash
# 用途：迁移前抓旧入口的 exit code + 归一化 stderr
# 用法：capture-baseline.sh <old-entry> <input-fixture> > baseline.txt

OLD_ENTRY="$1"
INPUT="$2"

OUT=$(bash "$OLD_ENTRY" $INPUT 2>&1)
RC=$?

echo "exit=$RC"
echo "$OUT" | bash scripts/gates/migration/normalize-stderr.sh
```

### 5.3 migration/render-docs.py

```python
def render_gate_checklist(registry: dict) -> str:
    """从 registry 渲染 gate-checklist.md。
    输出文件头自动加 <!-- generated, do not edit --> 标记（来源：requirements/REQ-2026-002/plan.md:43）。
    """
    sections = group_by_trigger(registry["gates"])
    lines = ["<!-- generated by scripts/gates/migration/render-docs.py, do not edit -->", "", "# 阶段门禁检查清单", ""]
    for trigger, gates in sections.items():
        lines.append(f"## {trigger}")
        for g in gates:
            lines.append(f"- [ ] **{g['id']}** ({g['severity']}) — {g.get('failure_message', '').splitlines()[0]}")
    return "\n".join(lines)


def main():
    if "--check" in sys.argv:
        # CI 强校验（D-007）：重新渲染并 diff，diff 非空即 exit 1
        ...
```

## 6. 9 字段集合最终命名

锁定（替代 requirement.md L48 的占位假设记录）：

1. `id`
2. `plugin`
3. `severity`
4. `triggers`
5. `applies_when`
6. `dependencies`
7. `side_effects`
8. `failure_message`
9. `tests`

注：`escape_hatch` 在 registry 中是 gate 级可选段，不计入"必填 9 字段"。`rationale` 注释/owner/since_version 用 YAML 注释承载，不进 schema。

## 7. 验收对应

| 需求章节验收点 | detail-design 实现 |
|---|---|
| 行为契约等价 | §5.1 normalize-stderr + §5.2 capture-baseline 的 snapshot 对比 |
| 4 PR 灰度 | §3 各 plugin 独立测试 + §5 migration 脚本 |
| H1 R005 事务化 | §3.1 staged_writes 模式 + 三路径单测 |
| H3 submit 与 next 同源 | §4.2 submit 时序复用 phase-transition gate 集合 |
| H4 PR 合并状态闭环 | §3.2 pr_state plugin |
| H5 Bash 写保护 | §3.3 bash_write_protect plugin + 双轨白名单 |
| audit log | §2.3 audit JSON schema + §2.2 write_audit() |
| escape_hatch 强制 reason | §1 registry escape_hatches + plugin 内 BYPASS-NO-REASON 错误码 |

## 待澄清清单

无遗留问题。承袭 tech-feasibility 阶段的 2 项假设记录（macOS PPID 容器行为 / F-002 与 F-003 并行），由 development / task-planning 阶段闭环。
