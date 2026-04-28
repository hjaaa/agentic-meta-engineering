"""统一门禁 runner 主入口。

设计文档：requirements/REQ-2026-002/artifacts/detailed-design.md §2.2

主要职责：
  1. 解析 CLI 参数 → 构造 GateContext（含 meta.yaml 解析）
  2. 加载 registry.yaml + S1~S10 schema 校验 + 拓扑无环（实现在 registry.py）
  3. 按 trigger + applies_when 过滤 gate
  4. 拓扑排序后顺序执行；side_effects=write_state 的 plugin 通过
     ctx.staged_writes 暂存，全 pass 后由 runner 调 commit_staged_writes 落盘
  5. 写 audit log 到 audit/<YYYY-MM>/<trigger>-<timestamp>.json（实现在 audit.py）
  6. 计算 exit code 返回（0 通过 / 1 存在 error / 2 自身异常）

F-012 round-2：registry / audit / schema 校验拆到独立模块（registry.py / audit.py），
本文件保留 re-export 以保持测试与外部代码的向后兼容。

使用：
  python scripts/gates/run.py --trigger=ci --dry-run
  python scripts/gates/run.py --trigger=phase-transition --req=REQ-2026-002 --from=X --to=Y
  python scripts/gates/run.py --validate-registry        # 仅校验 registry，不跑 gate
  python scripts/gates/run.py --trigger=adapter --legacy=check-meta requirements/REQ.../meta.yaml
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
import traceback
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any, Optional

import yaml

# 把 plugins 包加入 import 路径
_PKG_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_ROOT.parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from plugins.base import (  # noqa: E402
    TRIGGERS,
    Decision,
    Gate,
    GateContext,
    Report,
    Severity,
)

# F-012 round-2：registry / audit / state_io 拆分为独立模块；本文件 re-export 保持向后兼容
import registry as _registry  # noqa: E402
import audit as _audit  # noqa: E402
import state_io as _state_io  # noqa: E402

# Re-export：测试和 triggers/submit.py 通过 `import run as runner_mod` 访问以下符号
RegistryError = _registry.RegistryError
_validate_registry_schema = _registry._validate_registry_schema
_validate_one_entry = _registry._validate_one_entry
_validate_write_state_plugin = _registry._validate_write_state_plugin
ID_PATTERN = _registry.ID_PATTERN
SEVERITY_VALUES = _registry.SEVERITY_VALUES
SIDE_EFFECTS_VALUES = _registry.SIDE_EFFECTS_VALUES
REGISTRY_PATH = _registry.REGISTRY_PATH


def load_registry(
    path: Optional[Path] = None,
    validate_only_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    """re-export 包装：把 run 模块级 REGISTRY_PATH（被测试 monkeypatch 的入口）
    传给底层 registry.load_registry。

    F-012 round-2：测试代码通过 `monkeypatch.setattr(runner_mod, "REGISTRY_PATH", x)`
    改路径；本包装确保 monkeypatch 真正生效（否则 registry.py 模块级 REGISTRY_PATH
    保持原值，覆盖被忽略）。
    """
    return _registry.load_registry(
        path=path if path is not None else REGISTRY_PATH,
        validate_only_ids=validate_only_ids,
    )

write_audit = _audit.write_audit
_build_audit = _audit.build_audit
_calc_exit_code = _audit.calc_exit_code
AUDIT_DIR = _audit.AUDIT_DIR
SCHEMA_VERSION = _audit.SCHEMA_VERSION

_stash_state = _state_io.stash_state
_restore_state = _state_io.restore_state
_cleanup_snapshots = _state_io.cleanup_snapshots

# 安全校验：requirement_id 白名单正则，防止路径穿越（F-001 review 建议）
_REQ_ID_PATTERN = r"^REQ-\d{4}-\d{3}$"


class GateFailed(Exception):
    """某个 severity=error gate 的 Decision.FAIL 触发的中断信号。"""

    def __init__(self, report: Report) -> None:
        super().__init__(f"{report.gate_id} failed: {report.message}")
        self.report = report


# ====================== CLI ======================


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="统一门禁 runner")
    p.add_argument("--trigger", help="触发器：pre-tool-use|pre-commit|phase-transition|submit|ci|post-dev|adapter")
    p.add_argument("--req", dest="requirement_id", help="目标需求 ID，如 REQ-2026-002")
    p.add_argument("--from", dest="from_phase", help="phase-transition: 源 phase")
    p.add_argument("--to", dest="to_phase", help="phase-transition: 目标 phase")
    p.add_argument("--strict", action="store_true", help="warning 也视为失败")
    p.add_argument("--dry-run", action="store_true", help="不执行 gate.run，仅打印执行计划")
    p.add_argument("--validate-registry", action="store_true", help="仅校验 registry，不跑 gate")
    p.add_argument("--legacy", help="adapter 模式：包装某个旧 plugin（如 check-meta / check-index）")
    p.add_argument("paths", nargs="*", help="adapter 模式下传入的目标文件（如 meta.yaml 路径）")
    return p.parse_args(argv)


# ====================== context 构造（F-011 round-2 拆分） ======================


def _validate_requirement_id(req_id: str) -> bool:
    """校验 requirement_id 格式，防止路径穿越（F-001 review 安全建议）。

    只接受 REQ-YYYY-NNN 格式（4 位年份 + 3 位序号），拒绝含 .. / / 等路径穿越字符的输入。
    """
    return bool(re.match(_REQ_ID_PATTERN, req_id))


def _resolve_trigger(trigger: Optional[str]) -> str:
    """trigger 白名单校验 + adapter 模式归一化（F-011 round-2 抽出）。

    返回归一化后的 trigger（adapter → 'ci'）；非法 trigger 直接 SystemExit(2)。
    """
    if trigger == "adapter":
        return "ci"
    if trigger not in (*TRIGGERS, "adapter"):
        # F-11：trigger 白名单校验，防止写 audit 到 AUDIT_DIR 之外
        print(f"ERROR --trigger 非法：{trigger!r}，合法值 {sorted(TRIGGERS)}", file=sys.stderr)
        raise SystemExit(2)
    return trigger


def _load_meta_for_req(req_id: Optional[str]) -> dict[str, Any]:
    """按 requirement_id 加载 meta.yaml（含路径穿越防御 + 解析失败降级）。"""
    if not req_id:
        return {}
    if not _validate_requirement_id(req_id):
        print(
            f"ERROR requirement_id={req_id!r} 格式非法，必须匹配 REQ-YYYY-NNN",
            file=sys.stderr,
        )
        raise SystemExit(2)
    meta_path = _REPO_ROOT / "requirements" / req_id / "meta.yaml"
    if not meta_path.exists():
        return {}
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        print(f"WARNING 读取 meta.yaml 失败 req={req_id}：{exc}", file=sys.stderr)
        return {}


def _build_extra(args: argparse.Namespace, trigger: str) -> dict[str, Any]:
    """构造 ctx.extra（F-011 round-2 抽出）。

    包含 adapter 模式的 meta_paths + pre-tool-use 的 tool_name/file_path/command。
    """
    extra: dict[str, Any] = {}
    if args.legacy and args.paths:
        extra["meta_paths"] = args.paths
    # pre-tool-use trigger：从环境变量取 tool_name / file_path / command
    # （由 triggers/pre_tool_use.sh 解析 stdin 后注入；不让 plugin 自己读 os.environ）
    if trigger == "pre-tool-use":
        extra.setdefault("tool_name", os.environ.get("CLAUDE_HOOK_TOOL_NAME", ""))
        extra.setdefault("file_path", os.environ.get("CLAUDE_HOOK_FILE_PATH", ""))
        extra.setdefault("command", os.environ.get("CLAUDE_HOOK_COMMAND", ""))
    return extra


# F-15 / F-005 round-2：env 白名单常量（plugin 通过 ctx.env 读取，禁止直接 os.environ）
_ENV_WHITELIST = (
    "CLAUDE_HOOK_BRANCH",
    "CLAUDE_PROTECTED_BRANCHES",
    "CLAUDE_GATES_BYPASS",
    "CLAUDE_GATES_BYPASS_REASON",
    "SAVE_REVIEW_PID",  # F-005 round-2：save-review.sh 启动时 export 的 PID
)


def _build_env_whitelist() -> dict[str, str]:
    """从 os.environ 抽取白名单 key（F-011 round-2 抽出）。"""
    return {k: os.environ[k] for k in _ENV_WHITELIST if k in os.environ}


def _build_changed_files() -> list[str]:
    """pre-commit hook 通过 GATE_CHANGED_FILES 环境变量传入 staged 文件列表（换行分隔）。"""
    gate_changed = os.environ.get("GATE_CHANGED_FILES", "")
    if not gate_changed:
        return []
    return [f for f in gate_changed.splitlines() if f.strip()]


def build_context(args: argparse.Namespace) -> GateContext:
    """构造 GateContext（F-011 round-2 拆分：trigger / meta / extra / env / changed_files 子例程）。"""
    trigger = _resolve_trigger(args.trigger)
    meta = _load_meta_for_req(args.requirement_id)
    extra = _build_extra(args, trigger)
    changed_files = _build_changed_files()
    env = _build_env_whitelist()

    return GateContext(
        trigger=trigger,
        requirement_id=args.requirement_id,
        from_phase=args.from_phase,
        to_phase=args.to_phase,
        meta=meta,
        cli_flags={"strict": args.strict, "dry_run": args.dry_run, "legacy": args.legacy},
        extra=extra,
        changed_files=changed_files,
        env=env,
    )


# ====================== 过滤 + 拓扑 ======================


def filter_gates(registry_data: dict[str, Any], ctx: GateContext) -> list[dict[str, Any]]:
    """根据 ctx.trigger 过滤 gate（applies_when 内更精细的条件留给 F-002 实现）。

    adapter 模式：用 ctx.cli_flags['legacy'] 指定旧入口名（如 check-meta），
    通过 LEGACY_TO_PLUGIN 映射到 plugin 名后只保留对应 gate。
    """
    out: list[dict[str, Any]] = []
    legacy = ctx.cli_flags.get("legacy")
    legacy_plugin = LEGACY_TO_PLUGIN.get(legacy) if legacy else None
    for entry in registry_data.get("gates", []):
        if legacy:
            if entry["plugin"] == legacy_plugin:
                out.append(entry)
            continue
        # 普通模式：trigger 命中即纳入候选
        if ctx.trigger in (entry.get("triggers") or []):
            out.append(entry)
    return out


# 旧入口名 → plugin 名的映射（adapter 模式用；snapshot 行为契约用）
# F-002：补全全部 6 个旧入口（来源：requirements/REQ-2026-002/artifacts/detailed-design.md §5）
LEGACY_TO_PLUGIN: dict[str, str] = {
    "check-meta": "meta_schema",
    "check-index": "index_integrity",
    "check-sourcing": "sourcing",
    "check-reviews": "review_verdict",
    "check-plan": "plan_freshness",
    "workspace-clean": "workspace_clean",
}


def topological_sort(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 dependencies 拓扑排序，仅在候选集内的依赖参与（悬挂依赖已被 S5 拒绝）。"""
    if not entries:
        return []
    by_id = {e["id"]: e for e in entries}
    graph = {gid: set(d for d in (by_id[gid].get("dependencies") or []) if d in by_id)
             for gid in by_id}
    sorter = TopologicalSorter(graph)
    return [by_id[gid] for gid in sorter.static_order()]


def instantiate(entry: dict[str, Any]) -> Gate:
    """按 plugin 名实例化 Gate 子类。"""
    mod = importlib.import_module(f"plugins.{entry['plugin']}")
    return mod.GATE_CLASS()


# ====================== 主流程 ======================


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    # F-018：pre-tool-use 高频路径冷启动优化
    validate_only_ids: Optional[set[str]] = None
    if args.trigger == "pre-tool-use":
        validate_only_ids = {"GATE-PROTECT-BRANCH", "GATE-BASH-WRITE-PROTECT"}

    try:
        registry_data = load_registry(validate_only_ids=validate_only_ids)
    except RegistryError as exc:
        print(f"ERROR registry 加载失败：{exc}", file=sys.stderr)
        return 2

    if args.validate_registry:
        gate_count = len(registry_data.get("gates", []))
        print(f"OK registry 校验通过，共 {gate_count} 条 gate")
        return 0

    if not args.trigger:
        print("ERROR 必须指定 --trigger 或 --validate-registry", file=sys.stderr)
        return 2

    ctx = build_context(args)
    candidates = filter_gates(registry_data, ctx)
    plan = topological_sort(candidates)

    if args.dry_run:
        return _print_dry_run(ctx, plan)

    # 真实执行
    return _execute_plan(ctx, plan, strict=args.strict)


def _print_dry_run(ctx: GateContext, plan: list[dict[str, Any]]) -> int:
    print(f"[dry-run] trigger={ctx.trigger} req={ctx.requirement_id} 候选 gate 数={len(plan)}")
    for entry in plan:
        print(f"  - {entry['id']} (plugin={entry['plugin']}, severity={entry['severity']})")
    return 0


# ====================== 执行 plan（F-011 round-2 拆分） ======================


def _execute_plan(ctx: GateContext, plan: list[dict[str, Any]], strict: bool) -> int:
    """执行 plan：precheck → run → 暂存事务化 commit / fail 路径 rollback + restore。

    H1 事务化（F-002 round-2 修复）：
      commit_staged_writes 抛异常时统一走 GateFailed 路径——回滚已 commit 的 plugin、
      恢复 meta.yaml 磁盘快照、清空 staged_writes，避免 partial-commit 持久化。

    F-011 round-2：把"跑 gate / commit 写态 / GateFailed 处理"三段抽到子例程。
    """
    needs_stash = any(e.get("side_effects") == "write_state" for e in plan)
    snapshots = _stash_state(ctx) if needs_stash else {}
    executed: list[Gate] = []
    reports: list[Report] = []
    rollback_failed = False
    _current_plugin: list[str] = ["<unknown>"]

    try:
        _run_gates(ctx, plan, executed, reports, _current_plugin)
        _commit_write_state(ctx, executed, _current_plugin)
        _cleanup_snapshots(snapshots)
    except GateFailed:
        rollback_failed = _handle_gate_failed(ctx, executed, snapshots)
    except Exception as exc:  # noqa: BLE001
        return _handle_runner_exception(ctx, snapshots, reports, _current_plugin[0], exc)

    write_audit(_build_audit(ctx, reports, rollback_failed))
    return _calc_exit_code(reports, plan, strict)


def _run_gates(
    ctx: GateContext,
    plan: list[dict[str, Any]],
    executed: list[Gate],
    reports: list[Report],
    current_plugin: list[str],
) -> None:
    """跑每个 gate 的 precheck + run；任一 error 级 FAIL 抛 GateFailed（F-011 round-2 抽出）。"""
    for entry in plan:
        current_plugin[0] = entry.get("plugin", "<unknown>")
        gate = instantiate(entry)
        _log_gate_start(ctx, gate.id)
        skip = gate.precheck(ctx)
        if skip:
            reports.append(Report(gate.id, Decision.SKIP, message=skip.reason))
            continue
        executed.append(gate)
        r = gate.run(ctx)
        reports.append(r)
        sev = Severity(entry["severity"])
        if r.decision == Decision.FAIL and sev == Severity.ERROR:
            raise GateFailed(r)


def _commit_write_state(ctx: GateContext, executed: list[Gate], current_plugin: list[str]) -> None:
    """全 pass 后 commit 各 write_state plugin；任一异常转 GateFailed（F-011 round-2 抽出）。"""
    for g in executed:
        if getattr(g, "side_effects", "none") != "write_state":
            continue
        current_plugin[0] = g.id
        try:
            g.commit_staged_writes(ctx)
        except Exception as commit_exc:  # noqa: BLE001
            print(
                f"ERROR gate-commit-failed plugin={g.id} "
                f"trigger={ctx.trigger} req={ctx.requirement_id or '-'}: {commit_exc}",
                file=sys.stderr,
            )
            raise GateFailed(
                Report(
                    gate_id=g.id,
                    decision=Decision.FAIL,
                    code="GATE-COMMIT-FAILED",
                    message=f"commit_staged_writes 抛异常: {commit_exc}",
                    fix_hint="检查 meta.yaml 写权限、磁盘空间、并发锁竞争；可重试该 trigger",
                )
            ) from commit_exc


def _handle_gate_failed(ctx: GateContext, executed: list[Gate], snapshots: dict[str, Path]) -> bool:
    """GateFailed 路径：逆序 rollback + 恢复磁盘快照 + 清空 staged_writes（F-011 round-2 抽出）。

    返回：rollback_failed 标志（用于 audit log）。
    """
    rollback_failed = False
    for g in reversed(executed):
        try:
            g.rollback(ctx)
        except Exception as ex:  # noqa: BLE001
            rollback_failed = True
            print(f"ERROR gate-rollback-failed: {g.id}: {ex}", file=sys.stderr)
    _restore_state(ctx, snapshots)
    ctx.staged_writes.clear()
    return rollback_failed


def _handle_runner_exception(
    ctx: GateContext,
    snapshots: dict[str, Path],
    reports: list[Report],
    plugin_name: str,
    exc: Exception,
) -> int:
    """plugin 抛未捕获异常：恢复磁盘 + 写 audit 后返 2（F-011/F-033 round-2）。"""
    print(
        f"ERROR plugin 执行异常 plugin={plugin_name} "
        f"trigger={ctx.trigger} req={ctx.requirement_id or '-'}: {exc}",
        file=sys.stderr,
    )
    if not os.environ.get("CI"):
        traceback.print_exc(file=sys.stderr)
    _restore_state(ctx, snapshots)
    ctx.staged_writes.clear()
    # F-033：异常路径补 audit log，含 RUNNER-PLUGIN-EXCEPTION 占位条目，避免审计黑洞
    try:
        err_report = Report(
            gate_id=plugin_name,
            decision=Decision.FAIL,
            code="RUNNER-PLUGIN-EXCEPTION",
            message=f"plugin 抛未捕获异常: {exc}",
        )
        write_audit(_build_audit(ctx, reports + [err_report], rollback_failed=False))
    except Exception as audit_exc:  # noqa: BLE001
        print(f"ERROR audit log 异常路径写入失败: {audit_exc}", file=sys.stderr)
    return 2


def _log_gate_start(ctx: GateContext, gate_id: str) -> None:
    """关键业务节点日志：含 gate_id / trigger / requirement_id（无敏感信息）。"""
    print(
        f"INFO gate.start gate_id={gate_id} trigger={ctx.trigger} "
        f"requirement_id={ctx.requirement_id or '-'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
