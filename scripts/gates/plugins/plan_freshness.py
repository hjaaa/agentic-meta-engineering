"""GATE-PLAN-FRESHNESS：包装 scripts/lib/check_plan.py 适配统一 Gate API。

逻辑零改动 —— 沿用 check_plan 的新鲜度 + 占位符校验规则（E001/W001/W002/W003），
仅把旧版 `common.Report` 的多 finding 聚合结果映射为新 `plugins.base.Report`：

  - E001（plan.md 不存在）→ Decision.FAIL，code=R-PLAN，severity=error
  - W001/W002/W003 → Decision.PASS，severity=warning；--strict 模式由 runner 处理
  - 无 finding       → Decision.PASS

设计说明（来源：detailed-design.md §3.4）：
  plan_freshness 的警告属于"软检查"，W 类不阻断主流程；
  只有 E001（plan.md 不存在）才作 fail，severity 由 registry 声明为 warning，
  让 runner 在 strict 模式才真阻断。

F-003：changed_files 过滤双轨清理——pre-commit 时 runner 已通过
registry.yaml.applies_when.changed_files 过滤；本 plugin 不再 precheck 内重复
判定。run() 内 _resolve_req_dirs 仍用 changed_files 选择性扫描需求目录，是 IO
选路而非过滤，保留不动。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# noqa: E402 —— sys.path 注入后才能 import
from common import Report as LegacyReport  # noqa: E402
from common import Severity as LegacySeverity  # noqa: E402
import check_plan  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip
from ._helpers import _changed_req_dirs


class PlanFreshnessGate(Gate):
    """plan.md 新鲜度 + 非占位符软校验 gate（包装 check_plan.py）。"""

    id = "GATE-PLAN-FRESHNESS"
    severity = Severity.WARNING
    triggers = {"pre-commit", "phase-transition", "submit", "ci", "post-dev"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """F-003 起本 plugin 不在 precheck 做 changed_files 过滤（runner 一处消费）。"""
        return None

    def run(self, ctx: GateContext) -> Report:
        """检查目标需求的 plan.md 新鲜度与占位符完整性，返回聚合结果。

        错误场景：plan.md 不存在（E001）时 FAIL；W 类软警告在 strict 模式才阻断。
        参数：ctx — 包含 requirement_id / trigger / changed_files。
        """
        targets = _resolve_req_dirs(ctx)
        if not targets:
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message="no requirements in scope",
            )

        legacy_report = LegacyReport()
        for req_dir in targets:
            if not req_dir.is_dir():
                continue
            try:
                check_plan.check_requirement(req_dir, legacy_report)
            except OSError as exc:
                return Report(
                    gate_id=self.id,
                    decision=Decision.FAIL,
                    code="PLAN-IO",
                    message=f"读取 {req_dir} 失败: {exc}",
                    fix_hint="确认需求目录存在且可读",
                )

        # 行为契约：把 legacy 完整 render 输出到 stdout
        if legacy_report.findings():
            print(legacy_report.render())

        strict = bool(ctx.cli_flags.get("strict"))
        return _legacy_to_report(self.id, legacy_report, strict=strict)


def _resolve_req_dirs(ctx: GateContext) -> list[Path]:
    """决定本次需要检查的需求目录列表。

    优先级：
      1. ctx.extra["plan_req_dirs"]（显式注入）
      2. trigger=pre-commit 时从 changed_files 取 requirements/<id>/plan.md 的父目录
      3. ctx.requirement_id 存在则取对应需求目录
      4. 兜底：扫全部 requirements/*/
    """
    explicit = ctx.extra.get("plan_req_dirs")
    if explicit:
        return [Path(p) for p in explicit]

    if ctx.trigger == "pre-commit":
        dirs = _changed_req_dirs(ctx.changed_files, _REPO_ROOT)
        if dirs:
            return sorted(dirs)

    if ctx.requirement_id:
        target = _REPO_ROOT / "requirements" / ctx.requirement_id
        if target.exists():
            return [target]

    req_root = _REPO_ROOT / "requirements"
    if not req_root.exists():
        return []
    return sorted(
        d for d in req_root.iterdir()
        if d.is_dir() and not d.name.startswith(".") and (d / "meta.yaml").exists()
    )


def _legacy_to_report(
    gate_id: str, legacy: LegacyReport, *, strict: bool = False
) -> Report:
    """把 common.Report 的 findings 列表降维成单条 Report。

    转换规则（Bug-18 同模式修复）：
      - E001（plan.md 不存在）       → Decision.FAIL，code=R-PLAN
      - 仅 WARNING + strict          → Decision.FAIL，code=R-WARNING-ONLY
      - 仅 WARNING + 非strict        → Decision.PASS，warnings 透传到 vars
      - 无 finding                   → Decision.PASS
    """
    findings = legacy.findings()
    errors = [f for f in findings if f[1] == LegacySeverity.ERROR]
    warnings = [f for f in findings if f[1] == LegacySeverity.WARNING]

    if errors:
        first = errors[0]
        message = f"{first[0]}: {first[2]}: {first[3]}"
        return Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code="R-PLAN",
            message=message,
            fix_hint="确认 plan.md 存在且内容已填充（非纯模板占位）",
            vars={
                "errors": [list(f) for f in errors],
                "warnings": [list(f) for f in warnings],
            },
        )

    if warnings:
        first = warnings[0]
        if strict:
            return Report(
                gate_id=gate_id,
                decision=Decision.FAIL,
                code="R-WARNING-ONLY",
                message=f"{first[0]}: {first[2]}: {first[3]}",
                fix_hint="strict 模式下 warning 视为失败；去掉 --strict 或修复 W001/W002/W003 后重试",
                vars={"warnings": [list(f) for f in warnings]},
            )
        return Report(
            gate_id=gate_id,
            decision=Decision.PASS,
            message=(
                f"{len(warnings)} warning(s) ignored (non-strict); "
                f"first: {first[0]}: {first[2]}: {first[3]}"
            ),
            vars={"warnings": [list(f) for f in warnings]},
        )

    return Report(
        gate_id=gate_id,
        decision=Decision.PASS,
        vars={},
    )


# 模块级导出
GATE_CLASS = PlanFreshnessGate
