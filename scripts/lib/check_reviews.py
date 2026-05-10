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

# save_review 同目录，scripts/lib 已在 sys.path 中（脚本入口由 sh 启动）
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ─── REQ-2026-003 双卡点 sign-off 判定 ──────────────────────────────────────
# 所有调用方（feature-lifecycle-manager / GATE-REVIEW-VERDICT / save_review.CR 检查）
# 共用此常量+helper，严禁在各自逻辑里重复比对字符串（避免双轨 D-008）。
#
# 注意：SIGNOFF_PASS / is_signed_off 必须定义在 `import save_review` 之前——
# save_review 顶层会 `from check_reviews import is_signed_off`，若放在 import
# save_review 之后，循环导入会让 save_review 拿到 ImportError 并永久绑定 stub
# `return False`，导致 CR-1 / CR-4 静默失效（Codex P1-B verified bug）。
SIGNOFF_PASS: set[str] = {"approved", "approved-trivial"}


def is_signed_off(verdict: dict) -> bool:
    """REQ-2026-003 双卡点 sign-off 判定。
    所有调用方必须共用此 helper（feature-lifecycle-manager / GATE-REVIEW-VERDICT）。
    True 当且仅当 verdict.human_signoff.decision ∈ {approved, approved-trivial}。
    缺字段 / decision 为 rejected / 空字符串 → False。
    """
    sig = verdict.get("human_signoff") or {}
    return sig.get("decision") in SIGNOFF_PASS


import save_review
import canonical_phases  # canonical phase 枚举单一事实源（F-012 改自 phase_enum）

REQUIREMENTS_DIR = REPO_ROOT / "requirements"


# ─── target-phase → 必须存在的 review phase 列表（CLI 入口本地副本）──────────
# 设计动机（REQ-2026-009 F-012）：
#   旧实现暴露一个共享字典并被 plugins 跨模块 import；这种"定义一处、消费多处"的
#   拓扑会让 R 函数调用方与字典定义模块产生隐式耦合，且 R 函数内部
#   `dict.get(target_phase, [])` 的兜底空 list 是 vacuous pass 的根源。
#   新方案——每个调用方各持本地副本（dict literal）+ R 函数改 required_phases 显式入参：
#     1. dict literal 极小（7 行）+ 跨模块复制不会显著维护成本
#     2. R 函数只消费 list，不依赖具体 dict；新增 trigger 时不改 R 函数
#     3. 与 meta-schema.yaml `enums.phase` 单一事实源对齐
#   消费方当前 3 处：本文件 main() / scripts/gates/plugins/review_verdict.py
#   / scripts/gates/plugins/review_verdict_ci.py。
# 来源：context/team/engineering-spec/meta-schema.yaml `enums.phase`
_PHASE_REVIEW_DEPS: dict[str, list[str]] = {
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


def _r001_review_exists(
    meta: dict,
    target_phase: str,
    required_phases: list[str],
    report: Report,
    label: str,
) -> None:
    """R001: target-phase 要求的 review 必须存在（latest != null）

    fail-closed 防御：target_phase 必须在 canonical 枚举内，否则视为 typo / 非法值
    直接报 R001 错误。避免历史 bug：non-canonical phase 名（如 'technical-research'）
    会让前置 dict 取空 list → 静默 vacuous pass。
    F-012：required_phases 改为显式入参；调用方负责传入正确的 phase 列表。
    F-012 rev2 F-24：required_phases None 守卫（防调用方传 None 导致 for-loop TypeError）。
    """
    if required_phases is None:
        required_phases = []
    valid_phases = canonical_phases.load_canonical_phases()
    if target_phase and target_phase not in valid_phases:
        report.add(
            label, Severity.ERROR, "R001",
            f"target-phase '{target_phase}' 不在 canonical phase 枚举内 "
            f"({sorted(valid_phases)})；可能 phase 名拼写有误，"
            f"参考 context/team/engineering-spec/meta-schema.yaml:38",
        )
        return
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
        if phase == "code":
            continue  # 由 R007 处理
        entry = reviews.get(phase)
        if not entry or not entry.get("latest"):
            report.add(label, Severity.ERROR, "R001",
                       f"切到 {target_phase} 需要 {phase} 阶段的 review，但 reviews.{phase}.latest 为空")


def _r003_blocked_or_unsigned(
    meta: dict,
    required_phases: list[str],
    report: Report,
    label: str,
    req: str,
) -> None:
    """R003: latest.conclusion != blocked（D-008 旧 rejected 等价）且必须有 human_signoff。

    F-012 rev2 F-24：required_phases None 守卫。

    升级口径（REQ-2026-003 D-008）：
    - 旧 schema 里 conclusion=rejected → 新 schema 里 conclusion=blocked；两者都阻断
    - 新要求：所有非 code phase 的 latest verdict 必须经过人类 sign-off 才允许切阶段
    F-012：required_phases 改为显式入参（旧 target_phase 参数已删——R003 不在错误消息里
    引用 target_phase）。
    """
    if required_phases is None:
        required_phases = []
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        # 兼容旧 schema：conclusion=rejected 等价于新 blocked
        if entry.get("conclusion") in ("blocked", "rejected"):
            report.add(label, Severity.ERROR, "R003",
                       f"reviews.{phase}.conclusion={entry.get('conclusion')}，禁止切阶段")
        # 读 verdict 文件做 sign-off 判定（参考 _r002_schema_recheck 文件读取模式）
        latest_id = entry.get("latest")
        if not latest_id:
            continue
        prefix = f"REV-{req}-"
        if not latest_id.startswith(prefix):
            # 格式异常交由 R002 报告，R003 跳过
            continue
        suffix = latest_id[len(prefix):]
        review_path = REQUIREMENTS_DIR / req / "reviews" / f"{suffix}.json"
        if not review_path.exists():
            # 文件缺失交由 R002 报告，R003 跳过
            continue
        try:
            verdict = json.load(review_path.open(encoding="utf-8"))
        except json.JSONDecodeError:
            # 解析失败交由 R002 报告，R003 跳过
            continue
        # 升级判定：必须有 human_signoff.decision ∈ SIGNOFF_PASS 才放行
        if not is_signed_off(verdict):
            report.add(
                label, Severity.ERROR, "R003",
                f"reviews.{phase}.latest 缺 human_signoff 或 decision=rejected，未签字禁止切阶段",
            )


def _r002_schema_recheck(
    meta: dict,
    required_phases: list[str],
    report: Report,
    label: str,
    req: str,
) -> None:
    """R002: review JSON schema 合法（复用 save_review 的校验函数）

    F-012：required_phases 改为显式入参。
    F-012 rev2 F-24：required_phases None 守卫。
    """
    if required_phases is None:
        required_phases = []
    schema = save_review._load_schema()
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
        if phase == "code":
            # PR1: code 类 review 文件的 schema 复检暂未实现；R007 只检查 existence/conclusion。
            # 完整 schema 复检留待 PR3，届时 protect-branch 也会禁止主对话直接编辑 reviews/*.json。
            continue
        entry = reviews.get(phase) or {}
        latest_id = entry.get("latest")
        if not latest_id:
            continue
        # 找到对应 JSON 文件：去掉 REV-<req>- 前缀，剩余即文件名（不含 .json）
        prefix = f"REV-{req}-"
        if not latest_id.startswith(prefix):
            report.add(label, Severity.ERROR, "R002",
                       f"reviews.{phase}.latest={latest_id} 不以 {prefix} 开头，格式异常")
            continue
        suffix = latest_id[len(prefix):]   # e.g. "outline-design-002"
        review_path = REQUIREMENTS_DIR / req / "reviews" / f"{suffix}.json"
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
        for f, sev, code, msg in sub_report.findings():
            report.add(f, sev, f"R002/{code}", msg)


def _r004_needs_revision(
    meta: dict,
    required_phases: list[str],
    report: Report,
    label: str,
) -> None:
    """R004: latest.conclusion = needs_attention → 默认 WARNING，--strict 升 ERROR

    F-001/F-003 schema 升级后，旧 conclusion 值 needs_revision 已替换为
    needs_attention（AI 三档机器评估）。R004 同步级联到新枚举值。
    F-012：required_phases 改为显式入参。
    F-012 rev2 F-24：required_phases None 守卫。
    """
    if required_phases is None:
        required_phases = []
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
        if phase == "code":
            continue
        entry = reviews.get(phase) or {}
        if entry.get("conclusion") == "needs_attention":
            report.add(label, Severity.WARNING, "R004",
                       f"reviews.{phase}.conclusion=needs_attention，建议先修后切阶段")


def _r005_hash_drift(
    meta: dict,
    required_phases: list[str],
    report: Report,
    label: str,
    req: str,
    staged_writes: list | None = None,
) -> None:
    """R005: reviewed_artifacts 中所有文件当前 sha256 必须匹配。

    H1 改造（来源：detailed-design.md §3.1）：
      - 旧行为（CLI 直跑）：drift 命中后立即写盘 meta.yaml.reviews.<phase>.stale=true
      - 新行为（runner 事务化）：传入 staged_writes 时只 append 暂存项，不写盘
        （格式：("meta.yaml", f"reviews.{phase}.stale", True)），
        由 review_verdict plugin 的 commit_staged_writes 在所有 gate pass 后落盘。
      - staged_writes 为 None ⇒ 维持旧行为，CLI 入口（scripts/lib/check_reviews.py main）走此路径。
    F-012：required_phases 改为显式入参。
    F-012 rev2 F-24：required_phases None 守卫。
    """
    if required_phases is None:
        required_phases = []
    req_dir = REQUIREMENTS_DIR / req
    reviews = meta.get("reviews") or {}
    for phase in required_phases:
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
            # 同进程 meta dict 也回填 stale=true，方便后续规则读到一致视图
            entry["stale"] = True
            if staged_writes is not None:
                # H1 事务化路径：只暂存待写，不立即落盘
                staged_writes.append(("meta.yaml", f"reviews.{phase}.stale", True))
                continue
            # 旧行为：直接写回 stale=true（CLI 入口保留兼容）
            meta_path = req_dir / "meta.yaml"
            # 用 ruamel.yaml 保留注释（与 save_review 一致）
            with meta_path.open("r", encoding="utf-8") as f:
                meta_rt = save_review._meta_yaml.load(f)
            meta_rt.setdefault("reviews", {}).setdefault(phase, {})["stale"] = True
            tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                save_review._meta_yaml.dump(meta_rt, f)
            tmp_path.replace(meta_path)


def _r006_supersedes_chain(meta: dict, target_phase: str, report: Report, label: str, req: str) -> None:
    """R006: supersedes 链无环、无悬挂引用"""
    # target_phase 未使用：supersedes 链是全局检查，与切阶段方向无关，签名保留是为了与其他 R 函数一致
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
        # falsy 等价于"无前序"：None / "" / 0 都视为 round-001（无前序），不进入悬挂检查
        # 历史数据 bug：F-008-001.json 写入 supersedes=""（save_review 默认值偏差），
        # 工具层接受 falsy 兜底，避免历史单点数据触发 R006 误报（D-016）
        if not sup:
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
    done_features: list[str] = []
    for i, f in enumerate(features.get("features", [])):
        if not isinstance(f, dict):
            report.add(label, Severity.ERROR, "R007", f"features.json features[{i}] 不是 object")
            continue
        if f.get("status") != "done":
            continue
        fid = f.get("id")
        if not isinstance(fid, str) or not fid:
            report.add(label, Severity.ERROR, "R007", f"features.json features[{i}] status=done 但 id 缺失或非法")
            continue
        done_features.append(fid)
    code_seg = (meta.get("reviews") or {}).get("code") or {}
    by_feature = code_seg.get("by_feature") or {}
    for fid in done_features:
        entry = by_feature.get(fid) or {}
        latest_id = entry.get("latest")
        if not latest_id:
            report.add(label, Severity.ERROR, "R007",
                       f"feature {fid} status=done 但 reviews.code.by_feature.{fid}.latest 为空")
            continue
        # 兼容旧 schema：conclusion=rejected 等价于新 blocked
        if entry.get("conclusion") in ("rejected", "blocked"):
            report.add(label, Severity.ERROR, "R007",
                       f"feature {fid} 的 code review conclusion={entry.get('conclusion')}")
        # 升级判定：code review 也必须经过 human sign-off（REQ-2026-003 D-008）
        prefix = f"REV-{req}-"
        if not latest_id.startswith(prefix):
            continue
        suffix = latest_id[len(prefix):]
        review_path = REQUIREMENTS_DIR / req / "reviews" / f"code-{suffix}.json"
        # 兼容两种路径模式：code-<suffix>.json 与 <suffix>.json
        if not review_path.exists():
            review_path = REQUIREMENTS_DIR / req / "reviews" / f"{suffix}.json"
        if not review_path.exists():
            continue
        try:
            verdict = json.load(review_path.open(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not is_signed_off(verdict):
            report.add(
                label, Severity.ERROR, "R007",
                f"feature {fid} 的 code review 缺 human_signoff 或 decision=rejected，未签字禁止切阶段",
            )


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

    # PR4: legacy=true 的需求豁免所有 review 校验（历史治理用）
    # legacy 是 REQ 级硬豁免，--strict 也不互动
    if meta.get("legacy") is True:
        print(paint(f"ℹ️  {args.req} legacy=true，跳过 reviewer-verdict 校验（R001~R007）", "cyan"))
        return 0

    required_phases = _PHASE_REVIEW_DEPS.get(args.target_phase, [])
    _r001_review_exists(meta, args.target_phase, required_phases, report, label)
    _r002_schema_recheck(meta, required_phases, report, label, args.req)
    _r003_blocked_or_unsigned(meta, required_phases, report, label, args.req)
    _r004_needs_revision(meta, required_phases, report, label)
    _r005_hash_drift(meta, required_phases, report, label, args.req)
    _r006_supersedes_chain(meta, args.target_phase, report, label, args.req)
    _r007_code_by_feature_coverage(meta, args.target_phase, report, label, args.req)

    print(report.render())
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
