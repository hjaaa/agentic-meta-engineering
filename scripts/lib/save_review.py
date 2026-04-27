"""save-review.sh 的 Python 实现：写入 review JSON + 更新 meta.yaml.reviews

唯一事实源：context/team/engineering-spec/review-schema.yaml

用法：
  python3 scripts/lib/save_review.py \\
    --req REQ-2026-001 \\
    --phase definition \\
    --reviewer requirement-quality-reviewer \\
    [--scope feature_id=F-001] \\
    < verdict.json

退出码见 common.py。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

# ruamel.yaml 用于 meta.yaml round-trip（保留注释）；PyYAML 仅用于 schema 读取
from ruamel.yaml import YAML
import yaml

from common import REPO_ROOT, Report, Severity, paint, rel

SCHEMA_PATH = REPO_ROOT / "context" / "team" / "engineering-spec" / "review-schema.yaml"
REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# meta.yaml 专用实例：round-trip 模式，保留注释和 key 顺序
_meta_yaml = YAML(typ="rt")
_meta_yaml.preserve_quotes = True
_meta_yaml.indent(mapping=2, sequence=4, offset=2)


def _load_schema() -> dict[str, Any]:
    # schema 文件无需保留注释，使用 PyYAML safe_load 读取即可
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _check_required_fields(verdict: dict, schema: dict, report: Report, label: str) -> None:
    for field in schema.get("required_fields", []):
        if field not in verdict:
            report.add(label, Severity.ERROR, "missing", f"缺少必填字段 {field}")


def _check_enums(verdict: dict, schema: dict, report: Report, label: str) -> None:
    enums = schema.get("enums", {})
    for field, allowed in enums.items():
        if field == "severity":
            continue  # severity 在 issues 内部，单独检查
        value = verdict.get(field)
        if value is None:
            continue
        if value not in allowed:
            report.add(label, Severity.ERROR, "enum", f"字段 {field} 值 {value!r} 不在枚举 {allowed} 内")


def _check_format(verdict: dict, schema: dict, report: Report, label: str) -> None:
    fmt = schema.get("format", {})
    for field, rule in fmt.items():
        value = verdict.get(field)
        if value is None:
            continue
        if rule == "datetime":
            try:
                datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                report.add(label, Severity.ERROR, "format", f"字段 {field} 值 {value!r} 不符合 datetime 格式")
        elif isinstance(rule, str) and rule.startswith("^"):
            if not isinstance(value, str) or not re.match(rule, value):
                report.add(label, Severity.ERROR, "format", f"字段 {field} 值 {value!r} 不匹配正则 {rule}")


def _check_cr_rules(verdict: dict, report: Report, label: str) -> None:
    conclusion = verdict.get("conclusion")
    required_fixes = verdict.get("required_fixes") or []
    score = verdict.get("score")
    dimensions = verdict.get("dimensions") or {}

    # CR-1: approved ⇒ required_fixes == []
    if conclusion == "approved" and len(required_fixes) > 0:
        report.add(label, Severity.ERROR, "CR-1", "conclusion=approved 但 required_fixes 非空")

    # CR-2: required_fixes 非空 ⇒ conclusion ∈ {needs_revision, rejected}
    if len(required_fixes) > 0 and conclusion not in ("needs_revision", "rejected"):
        report.add(label, Severity.ERROR, "CR-2", f"required_fixes 非空但 conclusion={conclusion!r}")

    # CR-3: 任一 dim.score < 60 ⇒ conclusion ≠ approved
    for dim_name, dim in dimensions.items():
        dim_score = dim.get("score") if isinstance(dim, dict) else None
        if isinstance(dim_score, int) and dim_score < 60 and conclusion == "approved":
            report.add(label, Severity.ERROR, "CR-3", f"维度 {dim_name} score={dim_score} < 60 但 conclusion=approved")

    # CR-4: score < 70 ⇒ conclusion ≠ approved
    if isinstance(score, int) and score < 70 and conclusion == "approved":
        report.add(label, Severity.ERROR, "CR-4", f"score={score} < 70 但 conclusion=approved")

    # CR-5: 每个 issue 必须 severity 合法 + description 非空
    for dim_name, dim in dimensions.items():
        issues = dim.get("issues") if isinstance(dim, dict) else []
        for i, issue in enumerate(issues or []):
            if not isinstance(issue, dict):
                report.add(label, Severity.ERROR, "CR-5", f"维度 {dim_name} issues[{i}] 不是 object")
                continue
            sev = issue.get("severity")
            desc = issue.get("description")
            if sev not in ("blocker", "major", "minor"):
                report.add(label, Severity.ERROR, "CR-5", f"维度 {dim_name} issues[{i}] severity={sev!r} 不合法")
            if not desc or not desc.strip():
                report.add(label, Severity.ERROR, "CR-5", f"维度 {dim_name} issues[{i}] description 为空")

    # CR-6: 任一 issue.severity=blocker ⇒ conclusion ≠ approved
    if conclusion == "approved":
        for dim_name, dim in dimensions.items():
            for issue in (dim.get("issues") if isinstance(dim, dict) else []) or []:
                if isinstance(issue, dict) and issue.get("severity") == "blocker":
                    report.add(label, Severity.ERROR, "CR-6", f"维度 {dim_name} 含 blocker issue 但 conclusion=approved")


def _git_head_short() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short=7", "HEAD"], cwd=REPO_ROOT, text=True)
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _check_commit_matches_head(verdict: dict, report: Report, label: str) -> None:
    head = _git_head_short()
    if head is None:
        report.add(label, Severity.WARNING, "commit", "无法获取 git HEAD（非 git 仓库或 git 不可用）")
        return
    reviewed = verdict.get("reviewed_commit", "") or ""
    # 拒绝空或过短的 reviewed_commit（防止 head.startswith("") 隐式通过）
    if len(reviewed) < 7:
        report.add(label, Severity.ERROR, "commit", f"reviewed_commit={reviewed!r} 长度不足 7，无法与 HEAD 比对")
        return
    if not reviewed.startswith(head) and not head.startswith(reviewed[:7]):
        report.add(label, Severity.ERROR, "commit", f"reviewed_commit={reviewed!r} 与当前 HEAD={head!r} 不匹配")


def _check_scope_rules(verdict: dict, schema: dict, report: Report, label: str) -> None:
    """强制执行 review-schema.yaml 中的 scope_rules 约束。"""
    phase = verdict.get("phase")
    scope = verdict.get("scope")
    rules = schema.get("scope_rules", []) or []
    for rule in rules:
        when = rule.get("when") or {}
        match = True
        if "phase" in when and when["phase"] != phase:
            match = False
        if "phase_not" in when and phase in when["phase_not"]:
            match = False
        if not match:
            continue
        must = rule.get("must") or {}
        if "scope" in must:
            expected = must["scope"]
            if expected is None and scope is not None:
                report.add(label, Severity.ERROR, "scope", f"phase={phase!r} 时 scope 必须为 null，实际 {scope!r}")
            elif expected == "object" and not isinstance(scope, dict):
                report.add(label, Severity.ERROR, "scope", f"phase={phase!r} 时 scope 必须为 object，实际 {scope!r}")
        if "scope.feature_id" in must and isinstance(scope, dict):
            pat = must["scope.feature_id"]
            fid = scope.get("feature_id")
            if not isinstance(fid, str) or not re.match(pat, fid):
                report.add(label, Severity.ERROR, "scope", f"scope.feature_id={fid!r} 不匹配 {pat}")


def main() -> int:
    parser = argparse.ArgumentParser(description="写入 review JSON + 更新 meta.yaml.reviews")
    parser.add_argument("--req", required=True, help="REQ-YYYY-NNN")
    parser.add_argument("--phase", required=True, help="definition / outline-design / detail-design / code")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--scope", default=None, help="形如 feature_id=F-001（仅 phase=code 必填）")
    args = parser.parse_args()

    try:
        verdict = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(paint(f"❌ stdin JSON 解析失败: {exc}", "red"), file=sys.stderr)
        return 2

    # Fix 5+6: 交叉校验 CLI 参数与 verdict 字段，防止文件与命令行不一致
    if verdict.get("requirement_id") != args.req:
        print(paint(f"❌ verdict.requirement_id={verdict.get('requirement_id')!r} 与 --req={args.req!r} 不一致", "red"), file=sys.stderr)
        return 1
    if verdict.get("phase") != args.phase:
        print(paint(f"❌ verdict.phase={verdict.get('phase')!r} 与 --phase={args.phase!r} 不一致", "red"), file=sys.stderr)
        return 1
    if verdict.get("reviewer") != args.reviewer:
        print(paint(f"❌ verdict.reviewer={verdict.get('reviewer')!r} 与 --reviewer={args.reviewer!r} 不一致", "red"), file=sys.stderr)
        return 1

    schema = _load_schema()
    report = Report()
    label = f"<stdin>:{args.req}/{args.phase}"

    _check_required_fields(verdict, schema, report, label)
    _check_enums(verdict, schema, report, label)
    _check_format(verdict, schema, report, label)
    _check_cr_rules(verdict, report, label)
    _check_commit_matches_head(verdict, report, label)
    _check_scope_rules(verdict, schema, report, label)

    print(report.render())

    if report.errors > 0:
        return report.exit_code(strict=False)

    # 重算 reviewed_artifacts[].sha256
    req_dir = REQUIREMENTS_DIR / args.req
    if not req_dir.exists():
        print(paint(f"❌ 需求目录不存在: {rel(req_dir)}", "red"), file=sys.stderr)
        return 2

    for art in verdict.get("reviewed_artifacts", []):
        art_path = req_dir / art["path"]
        if not art_path.exists():
            print(paint(f"❌ artifact 文件不存在: {rel(art_path)}", "red"), file=sys.stderr)
            return 1
        with art_path.open("rb") as f:
            art["sha256"] = hashlib.sha256(f.read()).hexdigest()

    # 算下一个 NNN
    reviews_dir = req_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    phase = args.phase
    if phase == "code":
        if not args.scope or not args.scope.startswith("feature_id="):
            print(paint("❌ phase=code 必须有 --scope feature_id=F-XXX", "red"), file=sys.stderr)
            return 1
        # Fix 7: feature_id 只提取一次，后续复用
        feature_id = args.scope.split("=", 1)[1]
        prefix = f"code-{feature_id}-"
    else:
        prefix = f"{phase}-"
    existing = sorted(reviews_dir.glob(f"{prefix}*.json"))
    next_seq = len(existing) + 1
    out_name = f"{prefix}{next_seq:03d}.json"
    out_path = reviews_dir / out_name

    # 校验 review_id 与 NNN 一致
    expected_id = f"REV-{args.req}-{prefix}{next_seq:03d}"
    if verdict.get("review_id") != expected_id:
        print(paint(f"❌ review_id 应为 {expected_id!r}，实际 {verdict.get('review_id')!r}", "red"), file=sys.stderr)
        return 1

    # 写入 review JSON
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(paint(f"✓ 已写入 {rel(out_path)}", "green"))

    # 更新 meta.yaml.reviews
    # Fix 1+2: 使用 ruamel.yaml round-trip 模式读写，保留注释；写入改为 atomic（temp + rename）
    meta_path = req_dir / "meta.yaml"
    with meta_path.open("r", encoding="utf-8") as f:
        meta = _meta_yaml.load(f) or {}
    reviews = meta.setdefault("reviews", {})
    artifact_hashes = {art["path"]: art["sha256"] for art in verdict["reviewed_artifacts"]}
    entry = {
        "latest": verdict["review_id"],
        "conclusion": verdict["conclusion"],
        "reviewed_commit": verdict["reviewed_commit"],
        "artifact_hashes": artifact_hashes,
        "history": [],
        "stale": False,
    }
    if phase == "code":
        # feature_id 已在上方提取，直接复用（Fix 7）
        code_seg = reviews.setdefault("code", {}).setdefault("by_feature", {}).setdefault(feature_id, {"history": []})
        code_seg["history"] = (code_seg.get("history") or []) + [verdict["review_id"]]
        code_seg.update({k: v for k, v in entry.items() if k != "history"})
    else:
        old = reviews.get(phase, {"history": []})
        history = (old.get("history") or []) + [verdict["review_id"]]
        entry["history"] = history
        reviews[phase] = entry

    # atomic 写入：先写临时文件，再原子替换，防止中途崩溃导致 meta.yaml 损坏
    tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        _meta_yaml.dump(meta, f)
    tmp_path.replace(meta_path)  # POSIX 原子操作
    print(paint(f"✓ 已更新 {rel(meta_path)} 的 reviews.{phase}", "green"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
