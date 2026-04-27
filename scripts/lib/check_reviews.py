"""check-reviews.sh 的 Python 实现：阶段切换 / submit / CI 的门禁校验

唯一事实源：context/team/engineering-spec/review-schema.yaml

用法：
  python3 scripts/lib/check_reviews.py \\
    --req REQ-2026-001 \\
    --target-phase tech-research \\
    [--strict]

退出码见 common.py。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from common import REPO_ROOT, Report, Severity, paint, rel

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# target-phase → 必须存在的 review phase 列表
PHASE_REQUIREMENTS: dict[str, list[str]] = {
    "tech-research":  ["definition"],
    "outline-design": ["definition"],
    "detail-design":  ["outline-design"],
    "task-planning":  ["detail-design"],
    "development":    ["detail-design"],
    "testing":        ["detail-design", "code"],   # code 走 by_feature 检查
    "completed":      ["definition", "outline-design", "detail-design"],   # 全量
}


def _load_meta(req: str) -> dict[str, Any]:
    meta_path = REQUIREMENTS_DIR / req / "meta.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"{rel(meta_path)} 不存在")
    with meta_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _r001_review_exists(meta: dict, target_phase: str, report: Report, label: str) -> None:
    """R001: target-phase 要求的 review 必须存在（latest != null）"""
    required_phases = PHASE_REQUIREMENTS.get(target_phase, [])
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
        if phase == "code":
            continue  # 由 R007 处理
        entry = reviews.get(phase)
        if not entry or not entry.get("latest"):
            report.add(label, Severity.ERROR, "R001",
                       f"切到 {target_phase} 需要 {phase} 阶段的 review，但 reviews.{phase}.latest 为空")


def _r003_not_rejected(meta: dict, target_phase: str, report: Report, label: str) -> None:
    """R003: latest.conclusion != rejected"""
    required_phases = PHASE_REQUIREMENTS.get(target_phase, [])
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        if entry.get("conclusion") == "rejected":
            report.add(label, Severity.ERROR, "R003",
                       f"reviews.{phase}.conclusion=rejected，禁止切阶段")


def _r002_schema_recheck(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R002: review JSON schema 合法（复用 save_review 的校验函数）"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import save_review

    schema = save_review._load_schema()
    reviews = meta.get("reviews") or {}
    for phase in PHASE_REQUIREMENTS.get(target_phase, []):
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        latest_id = entry.get("latest")
        if not latest_id:
            continue
        # 找到对应 JSON 文件
        review_path = REQUIREMENTS_DIR / req / "reviews" / f"{phase}-{latest_id.rsplit('-', 1)[-1]}.json"
        if not review_path.exists():
            report.add(label, Severity.ERROR, "R002",
                       f"reviews.{phase}.latest={latest_id} 对应的文件 {rel(review_path)} 不存在")
            continue
        try:
            verdict = json.load(review_path.open(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.add(label, Severity.ERROR, "R002", f"{rel(review_path)} JSON 解析失败: {exc}")
            continue
        sub_report = Report()
        save_review._check_required_fields(verdict, schema, sub_report, str(review_path))
        save_review._check_enums(verdict, schema, sub_report, str(review_path))
        save_review._check_format(verdict, schema, sub_report, str(review_path))
        save_review._check_cr_rules(verdict, sub_report, str(review_path))
        for f, sev, code, msg in sub_report._findings:
            report.add(f, sev, f"R002/{code}", msg)


def _r004_needs_revision(meta: dict, target_phase: str, report: Report, label: str) -> None:
    """R004: latest.conclusion = needs_revision → 默认 WARNING，--strict 升 ERROR"""
    reviews = meta.get("reviews") or {}
    for phase in PHASE_REQUIREMENTS.get(target_phase, []):
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        if entry.get("conclusion") == "needs_revision":
            report.add(label, Severity.WARNING, "R004",
                       f"reviews.{phase}.conclusion=needs_revision，建议先修后切阶段")


def _r005_hash_drift(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R005: reviewed_artifacts 中所有文件当前 sha256 必须匹配"""
    req_dir = REQUIREMENTS_DIR / req
    reviews = meta.get("reviews") or {}
    for phase in PHASE_REQUIREMENTS.get(target_phase, []):
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        artifact_hashes = entry.get("artifact_hashes") or {}
        drifted: list[tuple[str, str, str]] = []
        for path_str, recorded in artifact_hashes.items():
            file_path = req_dir / path_str
            if not file_path.exists():
                drifted.append((path_str, recorded, "<missing>"))
                continue
            with file_path.open("rb") as f:
                current = hashlib.sha256(f.read()).hexdigest()
            if current != recorded:
                drifted.append((path_str, recorded, current))
        if drifted:
            for path_str, was, now in drifted:
                report.add(label, Severity.ERROR, "R005",
                           f"reviews.{phase}: {path_str} 已变更（was {was[:8]}..., now {now[:8] if now != '<missing>' else now}），review 已 stale，请重审")
            # 写回 stale=true
            entry["stale"] = True
            meta_path = req_dir / "meta.yaml"
            # 用 ruamel.yaml 保留注释（与 save_review 一致）
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import save_review
            with meta_path.open("r", encoding="utf-8") as f:
                meta_rt = save_review._meta_yaml.load(f)
            meta_rt.setdefault("reviews", {}).setdefault(phase, {})["stale"] = True
            tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                save_review._meta_yaml.dump(meta_rt, f)
            tmp_path.replace(meta_path)


def _r006_supersedes_chain(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R006: supersedes 链无环、无悬挂引用"""
    req_dir = REQUIREMENTS_DIR / req
    reviews_dir = req_dir / "reviews"
    if not reviews_dir.exists():
        return
    all_ids: dict[str, dict] = {}
    for jf in reviews_dir.glob("*.json"):
        try:
            v = json.load(jf.open(encoding="utf-8"))
            all_ids[v["review_id"]] = v
        except (json.JSONDecodeError, KeyError):
            continue
    for rid, v in all_ids.items():
        sup = v.get("supersedes")
        if sup is None:
            continue
        if sup not in all_ids:
            report.add(label, Severity.ERROR, "R006", f"{rid} supersedes={sup} 但目标不存在")
            continue
        # 环检测：从 sup 向前走，看能不能回到 rid
        seen = {rid}
        cur = sup
        while cur is not None and cur in all_ids:
            if cur in seen:
                report.add(label, Severity.ERROR, "R006", f"supersedes 链含环：{rid} → ... → {cur}")
                break
            seen.add(cur)
            cur = all_ids[cur].get("supersedes")


def _r007_code_by_feature_coverage(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R007: 切到 testing 时，code.by_feature 必须覆盖 features.json 中所有 status=done 的 feature"""
    if target_phase != "testing":
        return
    features_path = REQUIREMENTS_DIR / req / "artifacts" / "features.json"
    if not features_path.exists():
        report.add(label, Severity.ERROR, "R007", f"切到 testing 需要 {rel(features_path)}，但文件不存在")
        return
    try:
        features = json.load(features_path.open(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.add(label, Severity.ERROR, "R007", f"features.json 解析失败: {exc}")
        return
    done_features = [f["id"] for f in features.get("features", []) if f.get("status") == "done"]
    code_seg = (meta.get("reviews") or {}).get("code") or {}
    by_feature = code_seg.get("by_feature") or {}
    for fid in done_features:
        entry = by_feature.get(fid) or {}
        if not entry.get("latest"):
            report.add(label, Severity.ERROR, "R007",
                       f"feature {fid} status=done 但 reviews.code.by_feature.{fid}.latest 为空")
        elif entry.get("conclusion") == "rejected":
            report.add(label, Severity.ERROR, "R007",
                       f"feature {fid} 的 code review conclusion=rejected")


def main() -> int:
    parser = argparse.ArgumentParser(description="reviewer verdict 门禁校验")
    parser.add_argument("--req", required=True)
    parser.add_argument("--target-phase", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    label = args.req
    report = Report()

    try:
        meta = _load_meta(args.req)
    except FileNotFoundError as exc:
        print(paint(f"❌ {exc}", "red"), file=sys.stderr)
        return 2

    _r001_review_exists(meta, args.target_phase, report, label)
    _r002_schema_recheck(meta, args.target_phase, report, label, args.req)
    _r003_not_rejected(meta, args.target_phase, report, label)
    _r004_needs_revision(meta, args.target_phase, report, label)
    _r005_hash_drift(meta, args.target_phase, report, label, args.req)
    _r006_supersedes_chain(meta, args.target_phase, report, label, args.req)
    _r007_code_by_feature_coverage(meta, args.target_phase, report, label, args.req)

    print(report.render())
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
