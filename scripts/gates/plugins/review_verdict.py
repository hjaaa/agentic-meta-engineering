"""GATE-REVIEW-VERDICT：reviewer verdict 门禁（R001~R007 全规则）。

设计说明（来源：detailed-design.md §3.1 + detailed-design.md §3.4）：
  承载 R001~R007 全部规则，复用 scripts/lib/check_reviews.py 中的各 _rXXX 函数。

  注意 R005 约束（来源：detailed-design.md §3.1）：
    - F-002 阶段：R005 仍按原行为（check_reviews._r005_hash_drift 直接写 meta.yaml stale=true）
    - F-003 阶段：改造为事务化 staged_writes 模式（side_effects=write_state）
    - 因此本 plugin 的 side_effects=none；commit_staged_writes/rollback 均为基类空实现

precheck：
  - 需要 ctx.requirement_id + ctx.to_phase 才能跑（缺失任一直接 Skip）
  - ctx.meta.get("legacy") == True 时短路（历史治理豁免）
  - trigger 非 phase-transition / submit / ci 时跳过（review 校验仅在这些时机有意义）
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
import yaml  # noqa: E402（F-022：提至模块顶层）
from common import Report as LegacyReport  # noqa: E402
from common import Severity as LegacySeverity  # noqa: E402
import check_reviews  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# phase-transition 的目标 phase → 必须存在的 review phase 映射
# 与 check_reviews.PHASE_REQUIREMENTS 保持一致（来源：scripts/lib/check_reviews.py:33-41）
_PHASE_REQUIREMENTS = check_reviews.PHASE_REQUIREMENTS


class ReviewVerdictGate(Gate):
    """reviewer verdict 门禁 gate（R001~R007 全规则包装）。"""

    id = "GATE-REVIEW-VERDICT"
    severity = Severity.ERROR
    # phase-transition 和 submit 时必须检查；ci 时扫全部需求
    triggers = {"phase-transition", "submit", "ci"}
    # F-002 阶段：R005 仍保留直接写 meta.yaml 的旧行为，side_effects=none
    # F-003 阶段：改造为 write_state（staged_writes 事务化）
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        # ci trigger：扫全部需求，不需要 requirement_id 和 to_phase
        if ctx.trigger == "ci":
            return None

        if not ctx.requirement_id:
            return Skip("no requirement_id in context; review-verdict check skipped")

        if ctx.trigger == "phase-transition" and not ctx.to_phase:
            return Skip("phase-transition requires to_phase; review-verdict check skipped")

        # legacy=true 豁免（历史治理用）
        if ctx.meta.get("legacy") is True:
            return Skip(f"{ctx.requirement_id} legacy=true; review-verdict check skipped")

        return None

    def run(self, ctx: GateContext) -> Report:
        if ctx.trigger == "ci":
            return self._run_all_requirements(ctx)
        return self._run_single_requirement(ctx, ctx.requirement_id, ctx.to_phase)

    def _run_all_requirements(self, ctx: GateContext) -> Report:
        """ci trigger：扫全部 requirements/ 下的需求，汇总 findings。

        调用链：_load_req_meta → _should_skip_req → 主循环聚合。
        CC 保持 ≤ 6（来源：F-005 重构）。
        """
        req_root = _REPO_ROOT / "requirements"
        if not req_root.exists():
            return Report(gate_id=self.id, decision=Decision.PASS, message="no requirements dir")

        all_errors: list[tuple] = []
        all_warnings: list[tuple] = []

        for req_dir in sorted(req_root.iterdir()):
            if not req_dir.is_dir() or req_dir.name.startswith("."):
                continue
            req_id = req_dir.name
            meta = _load_req_meta(req_dir, all_warnings)
            if meta is None:
                continue
            if _should_skip_req(meta):
                continue
            _collect_findings(meta, req_id, all_errors, all_warnings)

        return _build_ci_report(self.id, all_errors, all_warnings)

    def _run_single_requirement(
        self, ctx: GateContext, req_id: Optional[str], target_phase: Optional[str]
    ) -> Report:
        """phase-transition / submit trigger：检查指定需求。"""
        assert req_id is not None

        try:
            meta = check_reviews._load_meta(req_id)
        except FileNotFoundError as exc:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="REVIEW-META-MISSING",
                message=str(exc),
                fix_hint="确认 requirements/<REQ-ID>/meta.yaml 存在",
            )

        if meta.get("legacy") is True:
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message=f"{req_id} legacy=true；跳过 R001~R007",
            )

        # submit trigger 时，target_phase 取 meta 中当前 phase
        effective_phase = target_phase or meta.get("phase", "")
        if not effective_phase or effective_phase not in _PHASE_REQUIREMENTS:
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message=f"target_phase={effective_phase!r} 无对应 review 要求；跳过",
            )

        legacy_report = LegacyReport()
        label = req_id
        _run_r_rules(legacy_report, meta, effective_phase, label, req_id)

        # 行为契约：把 legacy 完整 render 输出到 stdout
        if legacy_report.findings():
            print(legacy_report.render())

        return _legacy_to_report(self.id, legacy_report)


def _load_req_meta(req_dir: "Path", all_warnings: list[tuple]) -> "Optional[dict]":
    """读取 req_dir/meta.yaml；解析失败追加 warning 并返回 None。

    参数：
      req_dir      — 需求目录 Path（必须存在）
      all_warnings — 收集 warning 的列表（原地追加）
    """
    meta_path = req_dir / "meta.yaml"
    if not meta_path.exists():
        return None
    req_id = req_dir.name
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING GATE-REVIEW-VERDICT req={req_id} meta.yaml 解析失败: {exc}",
            file=sys.stderr,
        )
        all_warnings.append((req_id, "WARNING", "REVIEW-META-PARSE", f"meta.yaml 解析失败: {exc}"))
        return None


def _should_skip_req(meta: dict) -> bool:
    """判断是否应跳过当前需求（legacy 或 phase 无对应 review 要求）。

    参数：meta — meta.yaml 解析结果 dict。
    返回：True = 跳过；False = 继续校验。
    """
    if meta.get("legacy") is True:
        return True
    target_phase = meta.get("phase", "")
    return not target_phase or target_phase not in _PHASE_REQUIREMENTS


def _collect_findings(
    meta: dict,
    req_id: str,
    all_errors: list[tuple],
    all_warnings: list[tuple],
) -> None:
    """对单个需求跑 R001~R007，结果分类追加到 all_errors / all_warnings。

    参数：
      meta         — meta.yaml 解析结果
      req_id       — 需求 ID（用于日志 label）
      all_errors   — 收集 error 的列表（原地追加）
      all_warnings — 收集 warning 的列表（原地追加）
    """
    target_phase = meta.get("phase", "")
    legacy_report = LegacyReport()
    _run_r_rules(legacy_report, meta, target_phase, req_id, req_id)
    for finding in legacy_report.findings():
        if finding[1] == LegacySeverity.ERROR:
            all_errors.append(finding)
        else:
            all_warnings.append(finding)


def _build_ci_report(gate_id: str, all_errors: list[tuple], all_warnings: list[tuple]) -> Report:
    """根据 ci trigger 汇总结果构造 Report。

    有 error → FAIL（first error 为主信息）；否则 PASS（warnings 附带）。
    """
    if all_errors:
        first = all_errors[0]
        return Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code=first[2],
            message=f"{first[0]}: {first[3]}",
            fix_hint="对照 check-reviews.sh 规则修正对应 review 状态",
            vars={
                "errors": [list(f) for f in all_errors],
                "warnings": [list(f) for f in all_warnings],
            },
        )
    return Report(
        gate_id=gate_id,
        decision=Decision.PASS,
        vars={"warnings": [list(f) for f in all_warnings]} if all_warnings else {},
    )


def _run_r_rules(
    report: LegacyReport, meta: dict, target_phase: str, label: str, req_id: str
) -> None:
    """运行 R001~R007 全部规则，结果写入 report。

    R005 在 F-002 阶段保留旧行为（直接写 meta.yaml stale=true），F-003 再改造为事务化。
    """
    check_reviews._r001_review_exists(meta, target_phase, report, label)
    check_reviews._r002_schema_recheck(meta, target_phase, report, label, req_id)
    check_reviews._r003_not_rejected(meta, target_phase, report, label)
    check_reviews._r004_needs_revision(meta, target_phase, report, label)
    # R005：F-002 阶段保留原行为（直接写 stale=true），事务化在 F-003 改造
    check_reviews._r005_hash_drift(meta, target_phase, report, label, req_id)
    check_reviews._r006_supersedes_chain(meta, target_phase, report, label, req_id)
    check_reviews._r007_code_by_feature_coverage(meta, target_phase, report, label, req_id)


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
            code=first[2],
            message=message,
            fix_hint="对照 check-reviews.sh 规则修正对应 review 状态（R001~R007）",
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
GATE_CLASS = ReviewVerdictGate
