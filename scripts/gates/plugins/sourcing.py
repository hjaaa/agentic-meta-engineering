"""GATE-SOURCING：包装 scripts/lib/check_sourcing.py 适配统一 Gate API。

逻辑零改动 —— 沿用 check_sourcing 的三态校验规则（E001/E002/E003/W001/W002/W003），
仅把旧版 `common.Report` 的多 finding 聚合结果映射为新 `plugins.base.Report`：

  - 任一 ERROR finding         → Decision.FAIL，code=R-SOURCING
  - 仅 WARNING finding + strict → Decision.FAIL，code=R-WARNING-ONLY
  - 仅 WARNING finding + 非strict → Decision.PASS（warnings 透传到 vars，message 提示）
  - 无 finding                 → Decision.PASS

strict 由 `ctx.cli_flags["strict"]` 传入（runner 的 `--strict` flag）。
非 strict 默认放行 warning-only 是修复原 docstring 与实现不一致（Bug-18，
原实现违反 line 8 PASS 语义恒返 FAIL，导致 submit/post-dev 等非 strict 入口
被 pre-existing W002/W003 卡死）。

F-003：changed_files 过滤双轨清理——pre-commit 时 runner 已通过
registry.yaml.applies_when.changed_files 过滤；本 plugin 不再 precheck 内重复
判定（避免双轨腐化）。run() 内 _resolve_targets 仍按 changed_files 选择性扫描，
是 IO 选路而非过滤，保留不动。
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
        """F-003 起本 plugin 不在 precheck 做 changed_files 过滤（runner 一处消费）。

        留空实现仅为满足 Gate 抽象方法契约；过滤完全交给 runner 的
        filter_gates(applies_when.changed_files) 一次性处理。
        """
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

        strict = bool(ctx.cli_flags.get("strict"))
        return _legacy_to_report(self.id, legacy_report, strict=strict)


def _resolve_targets(ctx: GateContext) -> list[Path]:
    """决定本次需要扫描的 artifacts/*.md 路径列表。

    优先级：
      1. ctx.extra["sourcing_paths"]（显式注入）
      2. trigger=pre-commit 时使用 changed_files 中命中 artifacts/*.md 的文件
      3. ctx.requirement_id 存在则扫 requirements/<id>/artifacts/**/*.md
      4. 兜底：扫全部 requirements/*/artifacts/**/*.md，但 phase=completed 的需求豁免
         （档案需求的引用在 shipped 时刻已冻结；后续删除被引用文件不应触发 CI 回归）
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
    results: list[Path] = []
    for p in sorted(req_root.glob("*/artifacts/**/*.md")):
        if _is_completed_req(p, req_root):
            continue
        results.append(p)
    return results


def _is_completed_req(artifact_path: Path, req_root: Path) -> bool:
    """判断 artifact 所属需求是否已 completed（meta.yaml.phase == "completed"）。

    解析失败 / meta.yaml 缺失 → 视为未完成（保守，避免误豁免）。
    """
    try:
        rel = artifact_path.relative_to(req_root)
    except ValueError:
        return False
    if not rel.parts:
        return False
    req_dir = req_root / rel.parts[0]
    meta_path = req_dir / "meta.yaml"
    if not meta_path.exists():
        return False
    try:
        import yaml
        with meta_path.open("r", encoding="utf-8") as f:
            meta = yaml.safe_load(f) or {}
        return meta.get("phase") == "completed"
    except Exception:
        return False


def _legacy_to_report(
    gate_id: str, legacy: LegacyReport, *, strict: bool = False
) -> Report:
    """把 common.Report 的 findings 列表降维成单条 Report。

    转换规则（Bug-18 修复后）：
      - 任一 ERROR finding         → Decision.FAIL，code=R-SOURCING
      - 仅 WARNING finding + strict → Decision.FAIL，code=R-WARNING-ONLY（触发 exit=1）
      - 仅 WARNING finding + 非strict → Decision.PASS，warnings 透传到 vars
      - 无 finding                  → Decision.PASS

    strict 由调用方（plugin.run）从 ctx.cli_flags["strict"] 取得。
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
            code="R-SOURCING",
            message=message,
            fix_hint="对照 ai-collaboration.md §规则一 补三态标记（来源：/待用户确认/待补充）",
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
GATE_CLASS = SourcingGate
