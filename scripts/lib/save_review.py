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
import re
import subprocess
import sys
from datetime import datetime
from typing import Any

# ruamel.yaml 用于 meta.yaml round-trip（保留注释）；PyYAML 仅用于 schema 读取
import yaml
from ruamel.yaml import YAML

from common import REPO_ROOT, Report, Severity, paint, rel

# is_signed_off 来自 check_reviews——必须在 check_reviews 完成 SIGNOFF_PASS / is_signed_off
# 定义之后才能 import 本文件，否则循环导入会绑死 stub。check_reviews.py 已把这两个符号
# 放在 `import save_review` 之前；如改动 check_reviews import 顺序，必须同步验证此处导入。
from check_reviews import is_signed_off  # noqa: E402

# 新三档 conclusion 枚举（v2.0 schema）
CONCLUSION_NEW: set[str] = {"looks_clean", "needs_attention", "blocked"}
# human_signoff.decision 通过值集合
SIGNOFF_DECISION_PASS: set[str] = {"approved", "approved-trivial"}

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
    """校验 CR-1 ~ CR-8 内部一致性规则。

    签名不变：(verdict, report, label) -> None。
    通过 report.add 累积错误，禁止抛异常。
    """
    conclusion = verdict.get("conclusion")
    required_fixes = verdict.get("required_fixes") or []
    score = verdict.get("score")
    dimensions = verdict.get("dimensions") or {}

    # CR-1: 已签字 ⇒ required_fixes == []
    # is_signed_off 来自 F-004b；未合并时占位实现一律返回 False（跳过本条）
    if is_signed_off(verdict) and len(required_fixes) > 0:
        report.add(label, Severity.ERROR, "CR-1", "已签字（is_signed_off=True）但 required_fixes 非空")

    # CR-2: required_fixes 非空 ⇒ conclusion ∈ {needs_attention, blocked}
    if len(required_fixes) > 0 and conclusion not in ("needs_attention", "blocked"):
        report.add(label, Severity.ERROR, "CR-2", f"required_fixes 非空但 conclusion={conclusion!r}，应为 needs_attention 或 blocked")

    # CR-3: 任一 dim.score < 60 ⇒ conclusion ≠ looks_clean
    for dim_name, dim in dimensions.items():
        dim_score = dim.get("score") if isinstance(dim, dict) else None
        if isinstance(dim_score, int) and dim_score < 60 and conclusion == "looks_clean":
            report.add(label, Severity.ERROR, "CR-3", f"维度 {dim_name} score={dim_score} < 60 但 conclusion=looks_clean")

    # CR-4: score < 70 ⇒ conclusion ≠ looks_clean 且不能已签字
    if isinstance(score, int) and score < 70:
        if conclusion == "looks_clean":
            report.add(label, Severity.ERROR, "CR-4", f"score={score} < 70 但 conclusion=looks_clean")
        if is_signed_off(verdict):
            report.add(label, Severity.ERROR, "CR-4", f"score={score} < 70 但已签字（is_signed_off=True），禁止签字通过低分 verdict")

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

    # CR-6: 任一 issue.severity=blocker ⇒ conclusion 必须 == blocked（正向约束）
    for dim_name, dim in dimensions.items():
        for issue in (dim.get("issues") if isinstance(dim, dict) else []) or []:
            if isinstance(issue, dict) and issue.get("severity") == "blocker":
                if conclusion != "blocked":
                    report.add(label, Severity.ERROR, "CR-6",
                               f"维度 {dim_name} 含 blocker issue，conclusion 必须为 blocked，实际 {conclusion!r}")

    # CR-7（新增）: conclusion 必须命中新枚举——阻断 AI 残留写旧值（如 approved）
    if verdict.get("conclusion") not in CONCLUSION_NEW:
        report.add(label, Severity.ERROR, "CR-7",
                   f"conclusion {verdict.get('conclusion')!r} not in enum {sorted(CONCLUSION_NEW)}")

    # CR-8（新增）: human_signoff.source 若存在必须 ∈ signoff_source 枚举（当前仅 cli-tty）
    sig = verdict.get("human_signoff") or {}
    src = sig.get("source")
    if sig and src != "cli-tty":
        report.add(label, Severity.ERROR, "CR-8",
                   f"human_signoff.source {src!r} not in [cli-tty]")


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


def _check_artifact_blacklist(artifacts: list) -> str | None:
    """禁止 reviewed_artifacts 包含 meta.yaml 或 reviews/ 下的文件。

    返回 None 表示通过；返回字符串 = 失败原因（调用方负责 paint + stderr + exit）。
    黑名单原因：reviewer 写入 meta.yaml.reviews.<phase> 即修改 meta.yaml 内容，
    若 meta.yaml 被列入 reviewed_artifacts 则 R005 hash drift 立刻自引用失败。
    """
    for art in artifacts:
        path_str = art.get("path", "")
        if path_str == "meta.yaml":
            return (
                "❌ reviewed_artifacts 严禁包含 meta.yaml：reviewer 写入会修改 meta.yaml，"
                "导致 R005 hash drift 自引用循环；只列业务产出物"
                "（requirement.md / outline-design.md / detailed-design.md / features.json / tasks/*）"
            )
        if path_str.startswith("reviews/"):
            return (
                f"❌ reviewed_artifacts 严禁包含 reviews/ 下的文件（path={path_str}）："
                "reviewer 输出自身不应被 hash 跟踪"
            )
    return None


# ─── F-012 rev2：signoff 子模块 re-export ─────────────────────────────────────
# signoff 相关 helper 已迁入 scripts/lib/signoff.py；
# 下面的 import 保留原模块级名字，确保测试 monkeypatch 继续工作。
import signoff as _signoff_mod  # noqa: E402

_resolve_verdict_path = _signoff_mod._resolve_verdict_path
_run_signoff = _signoff_mod.run_signoff
_check_trivial_paths = _signoff_mod._check_trivial_paths


def _load_stdin_verdict() -> tuple[dict | None, int | None]:
    """从 stdin 读取并解析 JSON verdict；返回 (verdict, None) 或 (None, rc)。"""
    try:
        verdict = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(paint(f"❌ stdin JSON 解析失败: {exc}", "red"), file=sys.stderr)
        return None, 2
    return verdict, None


def _run_schema_checks(
    verdict: dict, args: argparse.Namespace
) -> tuple[dict | None, int | None]:
    """加载 schema + 全量 CR 校验；返回 (schema, None) 通过，(None, rc) 失败。"""
    try:
        schema = _load_schema()
    except yaml.YAMLError as exc:
        print(paint(f"❌ schema 文件格式错误: {exc}", "red"), file=sys.stderr)
        return None, 1
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
        return None, report.exit_code(strict=False)
    return schema, None


def _validate_inputs(
    args: argparse.Namespace, verdict: dict
) -> int | None:
    """stdin JSON 解析后的 CLI/verdict 字段一致性 + req_id/phase/reviewer 校验 + 黑名单。

    返回 None 通过，int=退出码（调用方直接 return）。
    """
    if verdict.get("requirement_id") != args.req:
        print(paint(f"❌ verdict.requirement_id={verdict.get('requirement_id')!r} 与 --req={args.req!r} 不一致", "red"), file=sys.stderr)
        return 1
    if verdict.get("phase") != args.phase:
        print(paint(f"❌ verdict.phase={verdict.get('phase')!r} 与 --phase={args.phase!r} 不一致", "red"), file=sys.stderr)
        return 1
    if verdict.get("reviewer") != args.reviewer:
        print(paint(f"❌ verdict.reviewer={verdict.get('reviewer')!r} 与 --reviewer={args.reviewer!r} 不一致", "red"), file=sys.stderr)
        return 1
    blacklist_err = _check_artifact_blacklist(verdict.get("reviewed_artifacts", []))
    if blacklist_err is not None:
        print(paint(blacklist_err, "red"), file=sys.stderr)
        return 1
    return None


def _compute_artifact_hashes(verdict: dict, req_dir: Any) -> int | None:
    """重算 reviewed_artifacts[].sha256 + 文件存在性校验。返回 None 通过，int=退出码。"""
    for art in verdict.get("reviewed_artifacts", []):
        art_path = req_dir / art["path"]
        if not art_path.exists():
            print(paint(f"❌ artifact 文件不存在: {rel(art_path)}", "red"), file=sys.stderr)
            return 1
        with art_path.open("rb") as f:
            art["sha256"] = hashlib.sha256(f.read()).hexdigest()
    return None


def _compute_next_review_id(
    args: argparse.Namespace, verdict: dict, reviews_dir: Any
) -> tuple[str, str] | int:
    """算下一个 NNN 序号 + review_id 一致性校验。

    返回 (feature_id, out_name) 或 int 退出码。feature_id 为空字符串时表示非 code phase。
    """
    phase = args.phase
    if phase == "code":
        if not args.scope or not args.scope.startswith("feature_id="):
            print(paint("❌ phase=code 必须有 --scope feature_id=F-XXX", "red"), file=sys.stderr)
            return 1
        feature_id = args.scope.split("=", 1)[1]
        prefix = f"code-{feature_id}-"
    else:
        feature_id = ""
        prefix = f"{phase}-"
    existing = sorted(reviews_dir.glob(f"{prefix}*.json"))
    next_seq = len(existing) + 1
    out_name = f"{prefix}{next_seq:03d}.json"
    expected_id = f"REV-{args.req}-{prefix}{next_seq:03d}"
    if verdict.get("review_id") != expected_id:
        print(paint(f"❌ review_id 应为 {expected_id!r}，实际 {verdict.get('review_id')!r}", "red"), file=sys.stderr)
        return 1
    return feature_id, out_name


def _commit_review_json(out_path: Any, verdict: dict) -> int | None:
    """原子写盘 review JSON（tmp+rename）；成功→None，OSError→1（D-014 同模式 _commit_signoff）。"""
    import os
    tmp_path = out_path.with_suffix(f".{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(verdict, f, ensure_ascii=False, indent=2)
            f.write("\n")
        tmp_path.replace(out_path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        print(paint(f"❌ review JSON 写盘失败（路径 {rel(tmp_path)}: {exc.strerror or exc}）", "red"), file=sys.stderr)
        return 1
    print(paint(f"✓ 已写入 {rel(out_path)}", "green"))
    return None


def _write_meta_yaml(
    meta_path: Any, meta: dict, phase: str, reviews: dict, verdict: dict, feature_id: str
) -> int | None:
    """更新 meta.yaml.reviews + atomic 写盘；成功→None，OSError→1。"""
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
        code_seg = reviews.setdefault("code", {}).setdefault("by_feature", {}).setdefault(feature_id, {"history": []})
        code_seg["history"] = (code_seg.get("history") or []) + [verdict["review_id"]]
        code_seg.update({k: v for k, v in entry.items() if k != "history"})
    else:
        old = reviews.get(phase, {"history": []})
        history = (old.get("history") or []) + [verdict["review_id"]]
        entry["history"] = history
        reviews[phase] = entry

    import os
    tmp_path = meta_path.with_suffix(f"{meta_path.suffix}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            _meta_yaml.dump(meta, f)
        tmp_path.replace(meta_path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        print(paint(f"❌ meta.yaml 写盘失败（路径 {rel(tmp_path)}: {exc.strerror or exc}）", "red"), file=sys.stderr)
        return 1
    print(paint(f"✓ 已更新 {rel(meta_path)} 的 reviews.{phase}", "green"))
    return None


def _run_save(args: argparse.Namespace) -> int:
    """既有 save 逻辑（拆 helper 后主流程 ≤25 行 / CC ≤10）。"""
    verdict, rc = _load_stdin_verdict()
    if rc is not None:
        return rc

    rc = _validate_inputs(args, verdict)  # type: ignore[arg-type]
    if rc is not None:
        return rc

    _schema, rc = _run_schema_checks(verdict, args)
    if rc is not None:
        return rc

    req_dir = REQUIREMENTS_DIR / args.req
    if not req_dir.exists():
        print(paint(f"❌ 需求目录不存在: {rel(req_dir)}", "red"), file=sys.stderr)
        return 2

    rc = _compute_artifact_hashes(verdict, req_dir)
    if rc is not None:
        return rc

    reviews_dir = req_dir / "reviews"
    reviews_dir.mkdir(exist_ok=True)
    result = _compute_next_review_id(args, verdict, reviews_dir)  # type: ignore[arg-type]
    if isinstance(result, int):
        return result
    feature_id, out_name = result

    rc = _commit_review_json(reviews_dir / out_name, verdict)
    if rc is not None:
        return rc

    meta_path = req_dir / "meta.yaml"
    with meta_path.open("r", encoding="utf-8") as f:
        meta = _meta_yaml.load(f) or {}
    reviews = meta.setdefault("reviews", {})
    rc = _write_meta_yaml(meta_path, meta, args.phase, reviews, verdict, feature_id)
    return rc if rc is not None else 0


_KNOWN_CMDS: frozenset[str] = frozenset({"save", "signoff"})


def _build_parsers() -> tuple[argparse.ArgumentParser, argparse._SubParsersAction]:
    """构造主 parser + subparser，供 main() 和单测复用。"""
    parser = argparse.ArgumentParser(description="写入 review JSON / 签字")
    sub = parser.add_subparsers(dest="cmd", required=False)

    # save 子命令（与既有调用方完全兼容）
    save_p = sub.add_parser("save", help="写入 review JSON + 更新 meta.yaml.reviews")
    save_p.add_argument("--req", required=True, help="REQ-YYYY-NNN")
    save_p.add_argument("--phase", required=True,
                        help="definition / outline-design / detail-design / code")
    save_p.add_argument("--reviewer", required=True)
    save_p.add_argument("--scope", default=None,
                        help="形如 feature_id=F-001（仅 phase=code 必填）")

    # signoff 子命令——parser 定义集中在 signoff.py 统一维护（F-012 rev2）
    _signoff_mod.build_signoff_parser(sub)

    return parser, sub


def main() -> int:
    """CLI 入口：支持 save（默认）与 signoff 两个子命令。

    兼容性保证：
      既有调用 'python3 save_review.py --req X --phase Y --reviewer Z'（无 subcommand）
      在升级后等价于 'python3 save_review.py save --req X --phase Y --reviewer Z'。

    实现方案：
      检查 sys.argv 第一个非 '-' 开头的参数是否是已知子命令。
      不是已知子命令 → 注入 'save' 前缀，走 save 路径（历史兼容）。
      是已知子命令 → 正常解析。
    """
    # 检测是否需要注入 'save' 前缀（历史兼容）
    # 寻找 sys.argv[1:] 中第一个非 '-' 开头的 token（候选 subcommand 位置）
    raw_argv = sys.argv[1:]
    first_positional = next(
        (tok for tok in raw_argv if not tok.startswith("-")), None
    )
    if first_positional not in _KNOWN_CMDS:
        # 旧调用格式（无 subcommand）：注入 'save' 前缀，委托 save 子 parser 解析
        _, sub = _build_parsers()
        save_args = sub.choices["save"].parse_args(raw_argv)
        return _run_save(save_args)

    # 新调用格式（有 subcommand）
    parser, _ = _build_parsers()
    args = parser.parse_args()

    if args.cmd == "save":
        return _run_save(args)
    if args.cmd == "signoff":
        return _run_signoff(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
