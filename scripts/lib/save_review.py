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
from pathlib import Path
from typing import Any

# ruamel.yaml 用于 meta.yaml round-trip（保留注释）；PyYAML 仅用于 schema 读取
from ruamel.yaml import YAML
import yaml

from common import REPO_ROOT, Report, Severity, paint, rel

# F-004b 实装后 is_signed_off 会从 check_reviews 导入；本期用占位兜底
# 占位实现：一律视为未签字（F-004b 未合并时的安全默认值）
try:
    from check_reviews import is_signed_off  # type: ignore[import]  # F-004b 实装后启用
except ImportError:
    def is_signed_off(verdict: dict) -> bool:  # noqa: D401
        """占位：F-004b 未合并时一律视为未签字。"""
        return False

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


def _resolve_verdict_path(rev_id: str) -> Path | None:
    """从 REV-ID 反推 verdict 文件路径。

    REV-ID 格式：REV-<REQ-ID>-<prefix>-NNN
    示例：REV-REQ-2026-003-definition-001
          REV-REQ-2026-003-code-F-001-001

    返回路径（不保证存在），或 None（解析失败）。
    """
    # 格式：REV-REQ-YYYY-NNN-<phase_and_seq>
    # 去掉开头的 "REV-" 前缀
    if not rev_id.startswith("REV-"):
        return None
    rest = rev_id[4:]  # 去掉 "REV-"

    # REQ-ID 固定为 REQ-YYYY-NNN（3 段 + 连字符）
    # 从 rest 中提取：REQ-2026-003 然后是文件名剩余部分
    parts = rest.split("-")
    # 期望格式：["REQ", "2026", "003", ...phase+seq...]
    if len(parts) < 4 or parts[0] != "REQ":
        return None

    req_id = f"{parts[0]}-{parts[1]}-{parts[2]}"
    # 文件名：rest 去掉 "<req_id>-" 前缀 = 余下的 phase-seq 部分
    filename_stem = rest[len(req_id) + 1:]  # e.g. "definition-001" or "code-F-001-001"
    if not filename_stem:
        return None

    verdict_path = REQUIREMENTS_DIR / req_id / "reviews" / f"{filename_stem}.json"
    return verdict_path


def _run_save(args: argparse.Namespace) -> int:
    """既有 save 逻辑（原 main() 全部迁入此函数）。"""
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

    # 黑名单：阻止 reviewer agent 把 meta.yaml / reviews/ 自身塞进 reviewed_artifacts
    # 历史教训：reviewer 写入 meta.yaml.reviews 块即破坏自身 hash，导致 R005 自引用循环
    blacklist_err = _check_artifact_blacklist(verdict.get("reviewed_artifacts", []))
    if blacklist_err is not None:
        print(paint(blacklist_err, "red"), file=sys.stderr)
        return 1

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


def _run_signoff(args: argparse.Namespace) -> int:
    """signoff 子命令：把 human_signoff 字段写入已有 verdict 文件。

    流程：
      1. 从 REV-ID 定位 verdict 文件
      2. 读 verdict JSON
      3. 写 human_signoff 字段
      4. 全量重跑 CR-1~CR-8 校验
      5. 通过 → 写盘 + append process.txt
      6. 失败 → 退出码 1 + stderr CR 详情
    """
    rev_id = args.rev_id
    verdict_path = _resolve_verdict_path(rev_id)
    if verdict_path is None:
        print(f"signoff: verdict {rev_id} not found", file=sys.stderr)
        return 4

    if not verdict_path.exists():
        print(f"signoff: verdict {rev_id} not found", file=sys.stderr)
        return 4

    # 读取 verdict 文件
    try:
        with verdict_path.open("r", encoding="utf-8") as f:
            verdict = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(paint(f"❌ verdict 文件解析失败: {exc}", "red"), file=sys.stderr)
        return 2

    # 检查是否已签字（防重复签名）
    existing_sig = verdict.get("human_signoff") or {}
    if existing_sig.get("decision"):
        signed_by = existing_sig.get("signed_by", "unknown")
        signed_at = existing_sig.get("signed_at", "unknown")
        print(f"signoff: already signed by {signed_by} at {signed_at}", file=sys.stderr)
        return 5

    # 写入 human_signoff 字段
    verdict["human_signoff"] = {
        "decision": args.decision,
        "signed_at": args.signed_at,
        "signed_by": args.signed_by,
        "source": args.source,
    }

    # 全量重跑 CR-1~CR-8 + 格式校验
    schema = _load_schema()
    report = Report()
    label = f"{verdict_path.name}:{verdict.get('requirement_id', '?')}"
    _check_required_fields(verdict, schema, report, label)
    _check_enums(verdict, schema, report, label)
    _check_format(verdict, schema, report, label)
    _check_cr_rules(verdict, report, label)
    _check_scope_rules(verdict, schema, report, label)

    if report.errors > 0:
        print(report.render(), file=sys.stderr)
        return 1

    # 写盘（原子替换）
    tmp_path = verdict_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(verdict_path)
    print(paint(f"✓ human_signoff 已写入 {rel(verdict_path)}", "green"))

    # append process.txt 评审事件
    req_id = verdict.get("requirement_id", "")
    if req_id:
        _append_signoff_process_log(req_id, rev_id, args.decision, args.signed_by)

    return 0


def _append_signoff_process_log(
    req_id: str, rev_id: str, decision: str, signed_by: str
) -> None:
    """追加 signoff 事件到 requirements/<req>/process.txt。

    格式（模仿 requirement-progress-logger 单行格式）：
      <ts> [signoff] <REV-ID> <decision> by <email>
    """
    process_path = REQUIREMENTS_DIR / req_id / "process.txt"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [signoff] {rev_id} {decision} by {signed_by}\n"
    try:
        with process_path.open("a", encoding="utf-8") as f:
            f.write(line)
        print(paint(f"✓ 已追加事件到 {rel(process_path)}", "green"))
    except OSError as exc:
        # 日志写入失败不阻断主流程，仅警告
        print(paint(f"⚠️  process.txt 写入失败（{exc}），签字已生效", "yellow"), file=sys.stderr)


def main() -> int:
    """CLI 入口：支持 save（默认）与 signoff 两个子命令。

    兼容性保证：
      既有调用 'python3 save_review.py --req X --phase Y --reviewer Z'
      在升级后等价于 'python3 save_review.py save --req X --phase Y --reviewer Z'，
      通过 args.cmd is None 路径走 _run_save，无需改 save-review.sh。
    """
    parser = argparse.ArgumentParser(description="写入 review JSON / 签字")
    sub = parser.add_subparsers(dest="cmd", required=False)

    # 默认子命令（无 cmd 时进入）：save —— 与既有调用方完全兼容
    save_p = sub.add_parser("save", help="写入 review JSON + 更新 meta.yaml.reviews")
    save_p.add_argument("--req", required=True, help="REQ-YYYY-NNN")
    save_p.add_argument("--phase", required=True,
                        help="definition / outline-design / detail-design / code")
    save_p.add_argument("--reviewer", required=True)
    save_p.add_argument("--scope", default=None,
                        help="形如 feature_id=F-001（仅 phase=code 必填）")

    # 新增子命令：signoff（卡点 B 调用）
    signoff_p = sub.add_parser("signoff", help="写 human_signoff 字段（卡点 B 调用）")
    signoff_p.add_argument("--rev-id", required=True, help="REV-ID，如 REV-REQ-2026-003-definition-001")
    signoff_p.add_argument("--decision", required=True,
                           choices=["approved", "approved-trivial", "rejected"],
                           help="sign-off 决策")
    signoff_p.add_argument("--signed-by", required=True, help="签字人 email（取自 git config user.email）")
    signoff_p.add_argument("--signed-at", required=True, help="签字时间（ISO8601 含时区）")
    # --source 当前枚举仅 cli-tty，保留参数形式为 D-004（PR Review 等价）预留扩展
    signoff_p.add_argument("--source", default="cli-tty", choices=["cli-tty"],
                           help="sign-off 来源（默认 cli-tty）")

    args = parser.parse_args()

    # cmd 缺省时（历史调用无 subcommand），检查是否有 --req 参数
    # 若有则走 save 路径（兼容旧调用）；若无则打印帮助
    if args.cmd is None:
        # 兼容旧调用：无子命令时尝试重解析为 save 子命令
        save_args = sub.choices["save"].parse_args(sys.argv[1:])
        return _run_save(save_args)

    if args.cmd == "save":
        return _run_save(args)
    if args.cmd == "signoff":
        return _run_signoff(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
