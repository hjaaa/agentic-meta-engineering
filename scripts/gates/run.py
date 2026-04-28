"""统一门禁 runner 主入口。

设计文档：requirements/REQ-2026-002/artifacts/detailed-design.md §2.2

主要职责：
  1. 解析 CLI 参数 → 构造 GateContext（含 meta.yaml 解析）
  2. 加载 registry.yaml + S1~S10 schema 校验 + 拓扑无环
  3. 按 trigger + applies_when 过滤 gate
  4. 拓扑排序后顺序执行；side_effects=write_state 的 plugin 通过
     ctx.staged_writes 暂存，全 pass 后由 runner 调 commit_staged_writes 落盘
  5. 写 audit log 到 audit/<YYYY-MM>/<trigger>-<timestamp>.json
  6. 计算 exit code 返回（0 通过 / 1 存在 error / 2 自身异常）

使用：
  python scripts/gates/run.py --trigger=ci --dry-run
  python scripts/gates/run.py --trigger=phase-transition --req=REQ-2026-002 --from=X --to=Y
  python scripts/gates/run.py --validate-registry        # 仅校验 registry，不跑 gate
  python scripts/gates/run.py --trigger=adapter --legacy=check-meta requirements/REQ.../meta.yaml
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import sys
import traceback
from datetime import datetime
from graphlib import CycleError, TopologicalSorter
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


REGISTRY_PATH = _PKG_ROOT / "registry.yaml"
AUDIT_DIR = _PKG_ROOT / "audit"
SCHEMA_VERSION = "1.0"

ID_PATTERN = r"^GATE-[A-Z][A-Z0-9-]+$"
SEVERITY_VALUES = {"error", "warning", "info"}
SIDE_EFFECTS_VALUES = {"none", "write_state"}

# 安全校验：requirement_id 白名单正则，防止路径穿越（F-001 review 建议，来源：code-F-001-001.json）
_REQ_ID_PATTERN = r"^REQ-\d{4}-\d{3}$"


class GateFailed(Exception):
    """某个 severity=error gate 的 Decision.FAIL 触发的中断信号。"""

    def __init__(self, report: Report) -> None:
        super().__init__(f"{report.gate_id} failed: {report.message}")
        self.report = report


class RegistryError(Exception):
    """registry.yaml 加载或 schema 校验失败。退出码 2。"""


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


# ====================== registry 加载 + schema 校验 ======================


def load_registry(path: Optional[Path] = None) -> dict[str, Any]:
    """加载 registry.yaml，跑 S1~S10 校验，返回 dict（含 gates / escape_hatches）。

    path=None 时回退到模块级 REGISTRY_PATH，保证测试期 monkeypatch 生效。
    """
    if path is None:
        path = REGISTRY_PATH
    if not path.exists():
        raise RegistryError(f"registry.yaml 不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise RegistryError(f"registry.yaml YAML 解析失败: {exc}") from exc

    if not isinstance(data, dict):
        raise RegistryError("registry.yaml 顶层必须是 mapping")
    gates = data.get("gates") or []
    if not isinstance(gates, list):
        raise RegistryError("registry.yaml gates 字段必须是 list")

    _validate_registry_schema(gates)
    return data


def _validate_registry_schema(gates: list[dict[str, Any]]) -> None:
    """跑 S1~S10 schema 校验，违反即抛 RegistryError。"""
    seen_ids: set[str] = set()
    id_to_entry: dict[str, dict[str, Any]] = {}

    for entry in gates:
        if not isinstance(entry, dict):
            raise RegistryError(f"gate entry 必须是 mapping，实际: {type(entry).__name__}")
        gid = entry.get("id")
        # S1：id 正则 + 全局唯一
        if not isinstance(gid, str) or not re.match(ID_PATTERN, gid):
            raise RegistryError(f"S1 违反：id={gid!r} 不符合 {ID_PATTERN}")
        if gid in seen_ids:
            raise RegistryError(f"S1 违反：id={gid!r} 重复")
        seen_ids.add(gid)
        id_to_entry[gid] = entry

        _validate_one_entry(entry)

    # S5：dependencies 引用必须存在
    for gid, entry in id_to_entry.items():
        for dep in entry.get("dependencies") or []:
            if dep not in seen_ids:
                raise RegistryError(f"S5 违反：{gid} 的依赖 {dep!r} 不存在于 gates")

    # S6：dependencies 拓扑无环
    graph = {gid: set(entry.get("dependencies") or []) for gid, entry in id_to_entry.items()}
    sorter = TopologicalSorter(graph)
    try:
        sorter.prepare()
    except CycleError as exc:
        raise RegistryError(f"S6 违反：dependencies 拓扑出现环 {exc.args[1]}") from exc

    # S7：side_effects=write_state 必须实现 rollback —— 用 hasattr+不为基类原方法判断
    for gid, entry in id_to_entry.items():
        if entry.get("side_effects") == "write_state":
            _validate_write_state_plugin(gid, entry["plugin"])


def _validate_one_entry(entry: dict[str, Any]) -> None:
    """单 gate 条目的 S2/S3/S4/S8/S9/S10 校验。"""
    gid = entry["id"]
    plugin_name = entry.get("plugin")

    # S2：plugin 模块存在且可导入（导出 Gate 子类）
    if not isinstance(plugin_name, str) or not plugin_name:
        raise RegistryError(f"S2 违反：{gid} 的 plugin 字段必填且为字符串")
    plugin_path = _PKG_ROOT / "plugins" / f"{plugin_name}.py"
    if not plugin_path.exists():
        raise RegistryError(f"S2 违反：{gid} 的 plugins/{plugin_name}.py 不存在")
    try:
        mod = importlib.import_module(f"plugins.{plugin_name}")
    except Exception as exc:  # noqa: BLE001
        raise RegistryError(f"S2 违反：plugins.{plugin_name} import 失败: {exc}") from exc
    cls = getattr(mod, "GATE_CLASS", None)
    if cls is None or not isinstance(cls, type) or not issubclass(cls, Gate):
        raise RegistryError(f"S2 违反：plugins/{plugin_name}.py 未导出 GATE_CLASS（Gate 子类）")

    # S3：triggers 白名单
    triggers = entry.get("triggers") or []
    if not isinstance(triggers, list) or not triggers:
        raise RegistryError(f"S3 违反：{gid} triggers 必须是非空 list")
    for t in triggers:
        if t not in TRIGGERS:
            raise RegistryError(f"S3 违反：{gid} 含未知 trigger={t!r}（白名单 {sorted(TRIGGERS)}）")

    # S4：severity 枚举
    if entry.get("severity") not in SEVERITY_VALUES:
        raise RegistryError(f"S4 违反：{gid} severity 必须 ∈ {sorted(SEVERITY_VALUES)}")

    # side_effects 枚举
    if entry.get("side_effects", "none") not in SIDE_EFFECTS_VALUES:
        raise RegistryError(f"{gid} side_effects 必须 ∈ {sorted(SIDE_EFFECTS_VALUES)}")

    # S8：tests.fixtures 至少 [pass, fail, skip]
    fixtures = ((entry.get("tests") or {}).get("fixtures")) or []
    if not {"pass", "fail", "skip"}.issubset(set(fixtures)):
        raise RegistryError(f"S8 违反：{gid} tests.fixtures 必须至少包含 [pass, fail, skip]")

    # S9：applies_when.requires 必须以 meta. 前缀
    requires = ((entry.get("applies_when") or {}).get("requires")) or []
    for item in requires:
        if not isinstance(item, str) or not item.startswith("meta."):
            raise RegistryError(f"S9 违反：{gid} applies_when.requires 项 {item!r} 必须以 'meta.' 开头")

    # S10：escape_hatch.cli_flag 限定 trigger
    eh = entry.get("escape_hatch") or {}
    cli_flag = eh.get("cli_flag")
    if cli_flag is not None:
        allowed = {"submit", "phase-transition"}
        if not (set(triggers) & allowed):
            raise RegistryError(
                f"S10 违反：{gid} escape_hatch.cli_flag={cli_flag!r} 仅 submit/phase-transition trigger 接受"
            )


def _validate_write_state_plugin(gid: str, plugin_name: str) -> None:
    """S7：side_effects=write_state 的 plugin 必须重写 rollback。"""
    mod = importlib.import_module(f"plugins.{plugin_name}")
    cls = mod.GATE_CLASS
    if cls.rollback is Gate.rollback:
        raise RegistryError(
            f"S7 违反：{gid} side_effects=write_state 但 plugins/{plugin_name}.py 未实现 rollback()"
        )


# ====================== context 构造 ======================


def _validate_requirement_id(req_id: str) -> bool:
    """校验 requirement_id 格式，防止路径穿越（F-001 review 安全建议）。

    只接受 REQ-YYYY-NNN 格式（4 位年份 + 3 位序号），拒绝含 .. / / 等路径穿越字符的输入。
    """
    return bool(re.match(_REQ_ID_PATTERN, req_id))


def build_context(args: argparse.Namespace) -> GateContext:
    trigger = args.trigger
    # adapter 模式：CLI 标志，不进 ctx.trigger 枚举（fallback 到 ci 以便复用 plugin 主流程）
    if trigger == "adapter":
        trigger = "ci"
    elif trigger not in (*TRIGGERS, "adapter"):
        # F-11：trigger 白名单校验，防止写 audit 到 AUDIT_DIR 之外（来源：F-002 review F-11）
        print(f"ERROR --trigger 非法：{trigger!r}，合法值 {sorted(TRIGGERS)}", file=sys.stderr)
        raise SystemExit(2)

    meta: dict[str, Any] = {}
    if args.requirement_id:
        # 路径穿越防御：校验 requirement_id 格式（F-001 review 安全建议，run.py:236）
        if not _validate_requirement_id(args.requirement_id):
            print(
                f"ERROR requirement_id={args.requirement_id!r} 格式非法，必须匹配 REQ-YYYY-NNN",
                file=sys.stderr,
            )
            raise SystemExit(2)
        meta_path = _REPO_ROOT / "requirements" / args.requirement_id / "meta.yaml"
        if meta_path.exists():
            try:
                with meta_path.open("r", encoding="utf-8") as f:
                    meta = yaml.safe_load(f) or {}
            except (yaml.YAMLError, OSError) as exc:
                print(
                    f"WARNING 读取 meta.yaml 失败 req={args.requirement_id}：{exc}",
                    file=sys.stderr,
                )
                meta = {}

    extra: dict[str, Any] = {}
    if args.legacy and args.paths:
        # adapter 模式下把 paths 透传给 plugin（meta_schema 取 meta_paths）
        extra["meta_paths"] = args.paths

    # pre-commit hook 通过 GATE_CHANGED_FILES 环境变量传入 staged 文件列表（换行分隔）
    changed_files: list[str] = []
    gate_changed = os.environ.get("GATE_CHANGED_FILES", "")
    if gate_changed:
        changed_files = [f for f in gate_changed.splitlines() if f.strip()]

    # F-15：注入 env 白名单（protect_branch 等 plugin 通过 ctx.env 读取，避免隐式依赖 os.environ）
    env = {k: os.environ[k] for k in ("CLAUDE_HOOK_BRANCH", "CLAUDE_PROTECTED_BRANCHES") if k in os.environ}

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


def filter_gates(registry: dict[str, Any], ctx: GateContext) -> list[dict[str, Any]]:
    """根据 ctx.trigger 过滤 gate（applies_when 内更精细的条件留给 F-002 实现）。

    adapter 模式：用 ctx.cli_flags['legacy'] 指定旧入口名（如 check-meta），
    通过 LEGACY_TO_PLUGIN 映射到 plugin 名后只保留对应 gate。
    """
    out: list[dict[str, Any]] = []
    legacy = ctx.cli_flags.get("legacy")
    legacy_plugin = LEGACY_TO_PLUGIN.get(legacy) if legacy else None
    for entry in registry.get("gates", []):
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

    try:
        registry = load_registry()
    except RegistryError as exc:
        print(f"ERROR registry 加载失败：{exc}", file=sys.stderr)
        return 2

    if args.validate_registry:
        gate_count = len(registry.get("gates", []))
        print(f"OK registry 校验通过，共 {gate_count} 条 gate")
        return 0

    if not args.trigger:
        print("ERROR 必须指定 --trigger 或 --validate-registry", file=sys.stderr)
        return 2

    ctx = build_context(args)
    candidates = filter_gates(registry, ctx)
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


def _execute_plan(ctx: GateContext, plan: list[dict[str, Any]], strict: bool) -> int:
    """执行 plan：precheck → run → 暂存事务化 commit / fail 路径 rollback + restore。"""
    # 仅当存在 write_state plugin 时才创建快照，避免污染工作区
    needs_stash = any(e.get("side_effects") == "write_state" for e in plan)
    snapshots = _stash_state(ctx) if needs_stash else {}
    executed: list[Gate] = []
    reports: list[Report] = []
    rollback_failed = False
    # 记录当前正在执行的 plugin 名，用于 generic Exception 日志上下文（F-001 review 建议）
    _current_plugin: list[str] = ["<unknown>"]

    try:
        for entry in plan:
            _current_plugin[0] = entry.get("plugin", "<unknown>")
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
        # 全部 pass：commit 暂存写
        for g in executed:
            if getattr(g, "side_effects", "none") == "write_state":
                _current_plugin[0] = g.id
                g.commit_staged_writes(ctx)
    except GateFailed:
        for g in reversed(executed):
            try:
                g.rollback(ctx)
            except Exception as ex:  # noqa: BLE001
                rollback_failed = True
                print(f"ERROR gate-rollback-failed: {g.id}: {ex}", file=sys.stderr)
        _restore_state(ctx, snapshots)
        ctx.staged_writes.clear()
    except Exception as exc:  # noqa: BLE001
        # plugin 内部未捕获异常：当作 runner 自身异常退出 2
        # 补充 plugin 名到日志上下文，便于排查（F-001 review 建议，run.py:380-385）
        print(
            f"ERROR plugin 执行异常 plugin={_current_plugin[0]} "
            f"trigger={ctx.trigger} req={ctx.requirement_id or '-'}: {exc}",
            file=sys.stderr,
        )
        if not os.environ.get("CI"):
            # 本地调试：完整堆栈有助于排查
            traceback.print_exc(file=sys.stderr)
        # CI 路径：堆栈已通过 audit log 结构化保存（TODO：待 F-003 audit log 增强后写入）
        _restore_state(ctx, snapshots)
        return 2

    write_audit(_build_audit(ctx, reports, rollback_failed))
    return _calc_exit_code(reports, plan, strict)


def _log_gate_start(ctx: GateContext, gate_id: str) -> None:
    """关键业务节点日志：含 gate_id / trigger / requirement_id（无敏感信息）。"""
    print(
        f"INFO gate.start gate_id={gate_id} trigger={ctx.trigger} "
        f"requirement_id={ctx.requirement_id or '-'}",
        file=sys.stderr,
    )


# ====================== 状态快照（事务化基础） ======================


def _stash_state(ctx: GateContext) -> dict[str, Path]:
    """对受保护文件做快照备份（本 PR 仅备份 meta.yaml；F-002 起按 plugin 写态扩展）。

    requirement_id 在 build_context 阶段已校验，此处直接使用。
    """
    snapshots: dict[str, Path] = {}
    if ctx.requirement_id:
        meta_path = _REPO_ROOT / "requirements" / ctx.requirement_id / "meta.yaml"
        if meta_path.exists():
            backup = meta_path.with_suffix(".yaml.bak")
            shutil.copy2(meta_path, backup)
            snapshots[str(meta_path)] = backup
    return snapshots


def _restore_state(ctx: GateContext, snapshots: dict[str, Path]) -> None:
    """fail 路径恢复快照；restore 后清理 .bak。"""
    for original, backup in snapshots.items():
        try:
            shutil.copy2(backup, original)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR restore_state failed: {original}: {exc}", file=sys.stderr)
        try:
            backup.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARNING restore_state .bak 清理失败 backup={backup}: {exc}",
                file=sys.stderr,
            )


# ====================== audit log ======================


def _build_audit(ctx: GateContext, reports: list[Report], rollback_failed: bool) -> dict[str, Any]:
    passed = [r.gate_id for r in reports if r.decision == Decision.PASS]
    failed = [
        {"gate_id": r.gate_id, "code": r.code, "message": r.message, "fix_hint": r.fix_hint}
        for r in reports if r.decision == Decision.FAIL
    ]
    skipped = [{"gate_id": r.gate_id, "reason": r.message} for r in reports if r.decision == Decision.SKIP]
    return {
        "schema_version": SCHEMA_VERSION,
        "trigger": ctx.trigger,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "actor": ctx.actor,
        "requirement_id": ctx.requirement_id,
        "from_phase": ctx.from_phase,
        "to_phase": ctx.to_phase,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "escape_used": None,
        "rollback_failed": rollback_failed,
        "exit_code": 1 if failed else 0,
    }


def write_audit(audit: dict[str, Any]) -> Path:
    """写 audit JSON 到 audit/<YYYY-MM>/<trigger>-<timestamp>.json。"""
    ts = datetime.now()
    sub = AUDIT_DIR / ts.strftime("%Y-%m")
    sub.mkdir(parents=True, exist_ok=True)
    fname = f"{audit['trigger']}-{ts.strftime('%Y%m%d-%H%M%S-%f')}.json"
    path = sub / fname
    with path.open("w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    return path


# ====================== exit code 计算 ======================


def _calc_exit_code(reports: list[Report], plan: list[dict[str, Any]], strict: bool) -> int:
    """0 通过 / 1 存在 error 级 fail（或 strict 下含 warning fail）。"""
    sev_by_id = {e["id"]: e["severity"] for e in plan}
    has_error_fail = False
    has_warning_fail = False
    for r in reports:
        if r.decision != Decision.FAIL:
            continue
        sev = sev_by_id.get(r.gate_id, "error")
        if sev == "error":
            has_error_fail = True
        elif sev == "warning":
            has_warning_fail = True
    if has_error_fail:
        return 1
    if strict and has_warning_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
