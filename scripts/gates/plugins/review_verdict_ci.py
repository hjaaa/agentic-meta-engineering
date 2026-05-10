"""GATE-REVIEW-VERDICT 的 ci 全量扫描分支（F-015 round-3 从 review_verdict.py 拆出）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §3.1（行 246-273）。

职责：
  - run_all_requirements：扫 requirements/ 下的全部需求，对每个跑 R001~R007 收集 errors/warnings
  - load_req_meta / should_skip_req：单需求子例程
  - collect_findings：把单个需求的 R 规则结果分类追加到 errors / warnings
  - build_ci_report：汇总 errors/warnings → 一条 Report（FAIL / PASS）

注意：本模块不是 Gate plugin（不导出 GATE_CLASS），仅作为 review_verdict.py 主类的
ci 路径委托函数。phase-transition / submit 单需求路径仍由 review_verdict.py 主文件承载。
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
import yaml  # noqa: E402
from common import Report as LegacyReport  # noqa: E402
from common import Severity as LegacySeverity  # noqa: E402
import check_reviews  # noqa: E402

from .base import Decision, Report

# phase-transition 的目标 phase → 必须存在的 review phase 映射（plugin 本地副本，
# F-012 取代跨模块共享 dict 的旧设计；详见 scripts/lib/check_reviews.py:_PHASE_REVIEW_DEPS
# 顶部的设计动机注释）。
# 来源：context/team/engineering-spec/meta-schema.yaml `enums.phase`
# （phase-rules.md F-012 后已删；meta-schema.yaml 为唯一事实源）
_PHASE_REVIEW_DEPS: dict[str, list[str]] = {
    "tech-research":  ["definition"],
    "outline-design": ["definition"],
    "detail-design":  ["outline-design"],
    "task-planning":  ["detail-design"],
    "development":    ["detail-design"],
    "testing":        ["detail-design", "code"],
    "completed":      ["definition", "outline-design", "detail-design"],
}


def run_all_requirements(gate_id: str) -> Report:
    """ci trigger：扫全部 requirements/ 下的需求，汇总 findings。

    调用链：load_req_meta → should_skip_req → collect_findings → build_ci_report。

    参数：gate_id — 主类传入的 GATE-REVIEW-VERDICT，作为 Report.gate_id 字段。
    """
    req_root = _REPO_ROOT / "requirements"
    if not req_root.exists():
        return Report(gate_id=gate_id, decision=Decision.PASS, message="no requirements dir")

    all_errors: list[tuple] = []
    all_warnings: list[tuple] = []

    for req_dir in sorted(req_root.iterdir()):
        if not req_dir.is_dir() or req_dir.name.startswith("."):
            continue
        meta = load_req_meta(req_dir, all_warnings)
        if meta is None:
            continue
        if should_skip_req(meta):
            continue
        collect_findings(meta, req_dir.name, all_errors, all_warnings)

    return build_ci_report(gate_id, all_errors, all_warnings)


def load_req_meta(req_dir: Path, all_warnings: list[tuple]) -> Optional[dict]:
    """读取 req_dir/meta.yaml；解析失败追加 warning 并返回 None。"""
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


def should_skip_req(meta: dict) -> bool:
    """判断是否应跳过当前需求（legacy=true 或 phase 无对应 review 要求）。"""
    if meta.get("legacy") is True:
        return True
    target_phase = meta.get("phase", "")
    return not target_phase or target_phase not in _PHASE_REVIEW_DEPS


def collect_findings(
    meta: dict,
    req_id: str,
    all_errors: list[tuple],
    all_warnings: list[tuple],
) -> None:
    """对单个需求跑 R001~R007，结果分类追加到 all_errors / all_warnings。

    ci trigger 路径是只读全量扫描：staged_writes=[] 显式传入空列表，
    R005 命中 drift 时只向此列表 append（不写盘 meta.yaml.stale=true），
    列表在本函数退出后即丢弃——保证 ci 路径无副作用。
    （F-012 rev2 修复 F-9：旧行为 None 会让 R005 走旧 CLI 直写路径。）
    """
    target_phase = meta.get("phase", "")
    required_phases = _PHASE_REVIEW_DEPS.get(target_phase, [])
    legacy_report = LegacyReport()
    staged_writes: list = []  # ci 只读路径：R005 drift 结果暂存此列表，不写盘
    run_r_rules(legacy_report, meta, target_phase, required_phases, req_id, req_id, staged_writes)
    for finding in legacy_report.findings():
        if finding[1] == LegacySeverity.ERROR:
            all_errors.append(finding)
        else:
            all_warnings.append(finding)


def build_ci_report(gate_id: str, all_errors: list[tuple], all_warnings: list[tuple]) -> Report:
    """根据 ci trigger 汇总结果构造 Report：有 error → FAIL（first error 主信息）；否则 PASS。"""
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


def legacy_to_report(gate_id: str, legacy: LegacyReport) -> Report:
    """把 common.Report 的 findings 列表降维成单条 Report（单需求路径用）。

    与 build_ci_report 同为 findings → Report 转换器，集中在本模块统一维护。
    F-015 round-3 从 review_verdict.py 迁出。
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


def run_r_rules(
    report: LegacyReport,
    meta: dict,
    target_phase: str,
    required_phases: list[str],
    label: str,
    req_id: str,
    staged_writes: list | None,
) -> None:
    """运行 R001~R007 全部规则，结果写入 report（公开 helper，被单需求路径与 ci 路径共用）。

    H1 事务化（来源：detailed-design.md §3.1）：
      staged_writes 非 None 时，R005 命中 drift 只 append 到暂存通道；
      为 None 时（如 ci trigger）走 CLI 旧行为（直接写盘 stale=true）。
    F-012：R001~R005 改 required_phases 显式入参（取代旧跨模块共享 dict）；
    R006/R007 不需要 required_phases（R006 全 reviews/ 扫描；R007 仅 testing 阶段触发）。
    """
    check_reviews._r001_review_exists(meta, target_phase, required_phases, report, label)
    check_reviews._r002_schema_recheck(meta, required_phases, report, label, req_id)
    check_reviews._r003_blocked_or_unsigned(meta, required_phases, report, label, req_id)
    check_reviews._r004_needs_revision(meta, required_phases, report, label)
    check_reviews._r005_hash_drift(meta, required_phases, report, label, req_id, staged_writes)
    check_reviews._r006_supersedes_chain(meta, target_phase, report, label, req_id)
    check_reviews._r007_code_by_feature_coverage(meta, target_phase, report, label, req_id)
