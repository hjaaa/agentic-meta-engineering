"""GATE-SOURCING：包装 scripts/lib/check_sourcing.py 适配统一 Gate API。

逻辑零改动 —— 沿用 check_sourcing 的三态校验规则（E001/E002/E003/W001/W002/W003），
仅把旧版 `common.Report` 的多 finding 聚合结果映射为新 `plugins.base.Report`：

  - 任一 ERROR finding → Decision.FAIL，code=R-SOURCING
  - 仅 WARNING finding → Decision.PASS（severity=warning 由 registry 决定）
  - 无 finding         → Decision.PASS

precheck：当 trigger=pre-commit 且无 artifacts/*.md 改动时直接 Skip。
其他 trigger 由 registry.yaml 的 applies_when 过滤。
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
import check_sourcing  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip
from ._helpers import _changed_artifact_paths


class SourcingGate(Gate):
    """刨根问底（Source-or-Mark）三态校验 gate（包装 check_sourcing.py）。"""

    id = "GATE-SOURCING"
    severity = Severity.ERROR
    triggers = {"pre-commit", "phase-transition", "submit", "ci", "post-dev"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """pre-commit 时若无 artifacts/*.md 改动则跳过；其他 trigger 一律继续。

        参数：ctx.changed_files — staged 文件列表（pre-commit 由 runner 注入）。
        返回：Skip（无需检查）或 None（继续执行 run）。
        """
        if ctx.trigger == "pre-commit":
            if not _has_artifact_md_change(ctx.changed_files):
                return Skip("no artifacts/*.md changes in this commit")
        return None

    def run(self, ctx: GateContext) -> Report:
        """对所有目标 artifacts/*.md 执行三态校验，返回聚合结果。

        错误场景：文件缺三态标记（来源/待用户确认/待补充）时 FAIL。
        参数：ctx — 包含 requirement_id / trigger / changed_files / extra["sourcing_paths"]。
        """
        targets = _resolve_targets(ctx)
        if not targets:
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message="no artifacts/*.md in scope",
            )

        legacy_report = LegacyReport()
        for t in targets:
            if not t.exists() or t.suffix != ".md":
                continue
            try:
                check_sourcing.check_file(t, legacy_report)
            except OSError as exc:
                return Report(
                    gate_id=self.id,
                    decision=Decision.FAIL,
                    code="SOURCING-IO",
                    message=f"读取 {t} 失败: {exc}",
                    fix_hint="确认文件存在且可读",
                )

        # 行为契约：把 legacy 完整 render 输出到 stdout
        if legacy_report.findings():
            print(legacy_report.render())

        return _legacy_to_report(self.id, legacy_report)


def _has_artifact_md_change(changed_files: list[str]) -> bool:
    """changed_files 命中 requirements/*/artifacts/**/*.md → True。"""
    return bool(_changed_artifact_paths(changed_files))


def _resolve_targets(ctx: GateContext) -> list[Path]:
    """决定本次需要扫描的 artifacts/*.md 路径列表。

    优先级：
      1. ctx.extra["sourcing_paths"]（显式注入）
      2. trigger=pre-commit 时使用 changed_files 中命中 artifacts/*.md 的文件
      3. ctx.requirement_id 存在则扫 requirements/<id>/artifacts/**/*.md
      4. 兜底：扫全部 requirements/*/artifacts/**/*.md
    """
    explicit = ctx.extra.get("sourcing_paths")
    if explicit:
        return [Path(p) for p in explicit]

    if ctx.trigger == "pre-commit":
        hits = _changed_artifact_paths(ctx.changed_files)
        if hits:
            return hits

    if ctx.requirement_id:
        artifacts_dir = _REPO_ROOT / "requirements" / ctx.requirement_id / "artifacts"
        if artifacts_dir.exists():
            return sorted(artifacts_dir.rglob("*.md"))

    req_root = _REPO_ROOT / "requirements"
    if not req_root.exists():
        return []
    return sorted(req_root.glob("*/artifacts/**/*.md"))


def _legacy_to_report(gate_id: str, legacy: LegacyReport) -> Report:
    """把 common.Report 的 findings 列表降维成单条 Report。"""
    findings = legacy.findings()
    errors = [f for f in findings if f[1] == LegacySeverity.ERROR]
    warnings = [f for f in findings if f[1] == LegacySeverity.WARNING]

    if errors:
        first = errors[0]
        message = f"{first[0]}: {first[2]}: {first[3]}"
        return Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code="R-SOURCING",
            message=message,
            fix_hint="对照 ai-collaboration.md §规则一 补三态标记（来源：/待用户确认/待补充）",
            vars={
                "errors": [list(f) for f in errors],
                "warnings": [list(f) for f in warnings],
            },
        )

    return Report(
        gate_id=gate_id,
        decision=Decision.PASS,
        vars={"warnings": [list(f) for f in warnings]} if warnings else {},
    )


# 模块级导出
GATE_CLASS = SourcingGate
