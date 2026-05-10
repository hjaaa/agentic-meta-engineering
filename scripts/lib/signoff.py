"""signoff 子命令实现：把 human_signoff 字段写入已有 verdict 文件。

F-012 rev2 拆分：原 save_review.py 中的 _run_signoff 及相关 helper 全部迁入本模块。
save_review.py main() 的 signoff 子命令派发到本模块的 run_signoff(args)。

来源：requirements/REQ-2026-009/artifacts/detailed-design.md + F-012 rev2 ADR（D-016）
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import REPO_ROOT, paint, rel

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# trivial 模式文档白名单（与原 code_review_signoff.py 保持一致，D-003 红线）
_DOC_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^.*\.md$"),
    re.compile(r"^docs/.*$"),
    re.compile(r"^.*\.txt$"),
]

# email 格式校验（与 code_review_routing.py 一致）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get_git_email() -> str | None:
    """从 git config 取 user.email；失败或格式非法返回 None。

    F-012 从 code_review_signoff.py 迁入；F-012 rev2 迁入 signoff.py。
    """
    try:
        email = subprocess.check_output(
            ["git", "config", "user.email"],
            text=True,
            cwd=REPO_ROOT,
        ).strip()
    except subprocess.CalledProcessError:
        email = ""
    if not email or not _EMAIL_RE.match(email):
        return None
    return email


def _get_iso8601_now() -> str:
    """返回当前时间的 ISO8601 含时区字符串。

    F-012 从 code_review_signoff.py 迁入；F-012 rev2 迁入 signoff.py。
    """
    return datetime.now(timezone.utc).astimezone().isoformat()


def _check_trivial_paths(diff_paths: list[str]) -> tuple[bool, list[str]]:
    """判断 diff_paths 是否全部属于文档白名单。

    返回：(all_doc, non_doc_paths)
      - all_doc=True 表示全部是文档文件（放行 --trivial）
      - non_doc_paths 是命中白名单之外的路径列表

    F-012 从 code_review_signoff.py 迁入；F-012 rev2 迁入 signoff.py。
    """
    non_doc: list[str] = []
    for path in diff_paths:
        if not any(pat.match(path) for pat in _DOC_PATH_PATTERNS):
            non_doc.append(path)
    return len(non_doc) == 0, non_doc


def _get_trivial_diff_paths(base: str = "main") -> list[str]:
    """获取 --trivial 模式下的 diff 文件列表（ACMR 变更）。

    F-012 从 code_review_signoff.py 迁入；F-012 rev2 迁入 signoff.py。
    """
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}..HEAD"],
            text=True,
            cwd=REPO_ROOT,
        )
        return [p for p in out.strip().splitlines() if p]
    except subprocess.CalledProcessError:
        # git diff 失败视为有非文档文件（保守策略）
        return ["<git-diff-failed>"]


def _sanitize_log_field(v: str) -> str:
    """strip \\r\\n 防 process.txt 日志注入。

    F-012 rev2 新增。
    """
    return v.replace("\n", " ").replace("\r", " ")


def _append_signoff_process_log(
    req_id: str, rev_id: str, decision: str, signed_by: str
) -> None:
    """追加 signoff 事件到 requirements/<req>/process.txt。

    格式（模仿 requirement-progress-logger 单行格式）：
      <ts> [signoff] <REV-ID> <decision> by <email>

    F-012 rev2 迁入 signoff.py。
    """
    process_path = REQUIREMENTS_DIR / req_id / "process.txt"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [signoff] {_sanitize_log_field(rev_id)} {decision} by {_sanitize_log_field(signed_by)}\n"
    try:
        with process_path.open("a", encoding="utf-8") as f:
            f.write(line)
        print(paint(f"✓ 已追加事件到 {rel(process_path)}", "green"))
    except OSError as exc:
        # 日志写入失败不阻断主流程，仅警告
        print(paint(f"⚠️  process.txt 写入失败（{exc}），签字已生效", "yellow"), file=sys.stderr)


def _resolve_verdict_path(rev_id: str) -> Path | None:
    """从 REV-ID 反推 verdict 文件路径。

    REV-ID 格式：REV-<REQ-ID>-<prefix>-NNN
    示例：REV-REQ-2026-003-definition-001
          REV-REQ-2026-003-code-F-001-001

    返回路径（不保证存在），或 None（解析失败）。

    F-012 rev2 迁入 signoff.py；加 path traversal 防护。
    """
    # 格式：REV-REQ-YYYY-NNN-<phase_and_seq>
    if not rev_id.startswith("REV-"):
        return None
    rest = rev_id[4:]  # 去掉 "REV-"

    # REQ-ID 固定为 REQ-YYYY-NNN（3 段 + 连字符）
    parts = rest.split("-")
    # 期望格式：["REQ", "2026", "003", ...phase+seq...]
    if len(parts) < 4 or parts[0] != "REQ":
        return None

    req_id = f"{parts[0]}-{parts[1]}-{parts[2]}"
    # 文件名：rest 去掉 "<req_id>-" 前缀 = 余下的 phase-seq 部分
    filename_stem = rest[len(req_id) + 1:]  # e.g. "definition-001" or "code-F-001-001"
    if not filename_stem:
        return None

    # F-012 rev2 F-21：path traversal 防护
    if ".." in filename_stem or "/" in filename_stem:
        return None
    verdict_path = REQUIREMENTS_DIR / req_id / "reviews" / f"{filename_stem}.json"
    try:
        resolved = verdict_path.resolve()
        reviews_root = (REQUIREMENTS_DIR / req_id / "reviews").resolve()
        if not str(resolved).startswith(str(reviews_root) + "/"):
            return None
    except (OSError, ValueError):
        return None
    return verdict_path


def run_signoff(args: argparse.Namespace) -> int:
    """signoff 子命令公开入口：把 human_signoff 字段写入已有 verdict 文件。

    F-012 rev2 从 save_review._run_signoff 迁入并公开（改名 run_signoff）。

    流程（F-012 重构后单一入口）：
      0. D-003 深防御：校验 stdin 必须为 tty（防 AI 代签；不允许 env var 旁路）
      1. 模式互斥校验：--trivial 与 --decision 不能同时使用
      2. --trivial 模式：跑路径白名单 → 通过则强制 decision=approved-trivial
      3. 自动填充 signed_by（git config user.email）/ signed_at（ISO8601 now）
         若未通过 CLI 显式提供；--signed-by 显式传入时校验 email 格式
      4. 从 REV-ID 定位 verdict 文件 + 已签字预检
      5. 写 human_signoff 字段 + 全量重跑 CR-1~CR-8
      6. 通过 → 写盘 + append process.txt；失败 → 退出码 1 + stderr CR 详情

    退出码：
      0 — 签字成功
      1 — 参数非法（互斥冲突 / --signed-by 格式非法 / 缺 git email / schema 文件缺失 / CR 校验失败）
      2 — 非 tty stdin
      3 — --trivial 通道：diff 含非文档文件
      4 — verdict 文件不存在
      5 — 已签字
      6 — verdict 文件解析失败（JSON 损坏 / IO 错误）
    """
    # 步骤 0：tty 校验（D-003 深防御；FAKE_TTY 等 env var 红线封禁）
    if not sys.stdin.isatty():
        print("signoff: stdin not a tty, refuse to sign for AI", file=sys.stderr)
        return 2

    # 步骤 1：模式互斥校验
    if args.trivial and args.decision is not None:
        print(
            "signoff: --trivial 与 --decision 不能同时使用（--trivial 自动设 approved-trivial）",
            file=sys.stderr,
        )
        return 1
    if not args.trivial and args.decision is None:
        print(
            "signoff: 必须指定 --decision，可选值 [approved, approved-trivial, rejected]",
            file=sys.stderr,
        )
        return 1

    # 步骤 2：--trivial 路径白名单判定
    if args.trivial:
        diff_paths = _get_trivial_diff_paths()
        all_doc, non_doc = _check_trivial_paths(diff_paths)
        if not all_doc:
            paths_str = " ".join(non_doc)
            print(f"trivial: non-doc files detected: {paths_str}", file=sys.stderr)
            return 3
        # --trivial 通过 → 强制 decision = approved-trivial
        decision = "approved-trivial"
    else:
        decision = args.decision

    # 步骤 3：自动填充 signed_by / signed_at（CLI 未提供时从 git / now 取）
    if args.signed_by is not None:
        if not _EMAIL_RE.match(args.signed_by):
            print(paint("❌ --signed-by 格式非法，应为 email", "red"), file=sys.stderr)
            return 1
        signed_by = args.signed_by
    else:
        signed_by = _get_git_email()
        if signed_by is None:
            print("signoff: 无法获取 git config user.email，请先配置", file=sys.stderr)
            return 1
    signed_at = args.signed_at or _get_iso8601_now()

    # 步骤 4：定位 verdict 文件 + 已签字预检
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
        return 6

    # 检查是否已签字（防重复签名）
    existing_sig = verdict.get("human_signoff") or {}
    if existing_sig.get("decision"):
        existing_by = existing_sig.get("signed_by", "unknown")
        existing_at = existing_sig.get("signed_at", "unknown")
        print(f"signoff: already signed by {existing_by} at {existing_at}", file=sys.stderr)
        return 5

    # 步骤 5：写入 human_signoff 字段
    verdict["human_signoff"] = {
        "decision": decision,
        "signed_at": signed_at,
        "signed_by": signed_by,
        "source": args.source,
    }

    # 全量重跑 CR-1~CR-8 + 格式校验（延迟导入避免循环）
    import save_review as _sr  # noqa: PLC0415

    try:
        schema = _sr._load_schema()
    except FileNotFoundError as exc:
        print(paint(f"❌ schema 文件缺失: {exc}", "red"), file=sys.stderr)
        return 1
    from common import Report  # noqa: PLC0415

    report = Report()
    label = f"{verdict_path.name}:{verdict.get('requirement_id', '?')}"
    _sr._check_required_fields(verdict, schema, report, label)
    _sr._check_enums(verdict, schema, report, label)
    _sr._check_format(verdict, schema, report, label)
    _sr._check_cr_rules(verdict, report, label)
    _sr._check_scope_rules(verdict, schema, report, label)

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
    req_id_str = verdict.get("requirement_id", "")
    if req_id_str:
        _append_signoff_process_log(req_id_str, rev_id, decision, signed_by)

    return 0


def build_signoff_parser(sub: argparse._SubParsersAction) -> None:
    """向 subparser action 注册 signoff 子命令。

    供 save_review._build_parsers() 调用，将 signoff parser 定义集中在本模块。
    """
    signoff_p = sub.add_parser(
        "signoff",
        help="写 human_signoff 字段（卡点 B 调用；包含 tty 校验 + trivial 路径白名单 + CR 校验）",
    )
    signoff_p.add_argument("--rev-id", required=True,
                           help="REV-ID，如 REV-REQ-2026-003-definition-001")
    # F-012：--decision 与 --trivial 互斥；二者必择一（运行时校验）
    signoff_p.add_argument("--decision", default=None,
                           choices=["approved", "approved-trivial", "rejected"],
                           help="sign-off 决策（与 --trivial 互斥）")
    signoff_p.add_argument("--trivial", action="store_true",
                           help="纯文档变更快速通道：git diff 全部 ∈ *.md/docs/**/*.txt 才放行；"
                                "通过则强制 decision=approved-trivial（与 --decision 互斥）")
    # F-012：--signed-by / --signed-at 改为可选——未提供时自动取 git config user.email / 当前时间
    signoff_p.add_argument("--signed-by", default=None,
                           help="签字人 email（默认从 git config user.email 取）")
    signoff_p.add_argument("--signed-at", default=None,
                           help="签字时间 ISO8601 含时区（默认当前时间）")
    # --source 当前枚举仅 cli-tty，保留参数形式为 D-004（PR Review 等价）预留扩展
    signoff_p.add_argument("--source", default="cli-tty", choices=["cli-tty"],
                           help="sign-off 来源（默认 cli-tty）")


# 向后兼容别名：测试文件通过 sig._run_signoff(args) 调用（F-012 rev2 拆模块后保留）
_run_signoff = run_signoff
