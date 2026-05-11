"""sign-off 子模块（F-012 rev2 从 save_review.py 拆出）

⚠️ 不能作为独立 CLI 入口——必须通过 save_review.py 的 main() 委托。
原因：save_review.py 顶层 import signoff，run_signoff 调用的 _run_cr_checks 函数体内
延迟加载 save_review（避免循环 import）。F-012 rev6 Major 1：纯工具函数（_get_iso8601_now /
_sanitize_log_field）迁入 save_review_validation.py，signoff → validation 为单向依赖。

来源：detailed-design.md §10.3 + D-016 + D-017

⚠️ __all__ 公开 API 仅限 build_signoff_parser 与 run_signoff。
  禁止直接 `python3 -m signoff` 启动。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common import REPO_ROOT, Report, paint, rel

# F-012 rev6 Major 1：纯工具 helper 从 save_review_validation.py 导入（单向依赖）
# _check_args_mutex / _validate_signed_by / _get_git_email / _resolve_verdict_path 保留在本模块，
# 因测试通过 monkeypatch.setattr(sig, "...") 直接 patch，需在 signoff 命名空间中可替换。
from save_review_validation import (
    _get_iso8601_now,
    _sanitize_log_field,
)

_log = logging.getLogger(__name__)

__all__ = ["run_signoff", "build_signoff_parser"]

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# email 格式校验（与 code_review_routing.py 一致）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# trivial 模式文档白名单（与原 code_review_signoff.py 保持一致，D-003 红线）
_DOC_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^.*\.md$"),
    re.compile(r"^docs/.*$"),
    re.compile(r"^.*\.txt$"),
]


def _check_trivial_paths(diff_paths: list[str]) -> tuple[bool, list[str]]:
    """判断 diff_paths 是否全部属于文档白名单；返回 (all_doc, non_doc_paths)。（rev2 迁入）"""
    non_doc: list[str] = []
    for path in diff_paths:
        if not any(pat.match(path) for pat in _DOC_PATH_PATTERNS):
            non_doc.append(path)
    return len(non_doc) == 0, non_doc


def _resolve_verdict_path(rev_id: str) -> tuple[Path | None, str]:
    """从 REV-ID 反推 verdict 文件路径。

    REV-ID 格式：REV-<REQ-ID>-<prefix>-NNN（如 REV-REQ-2026-003-definition-001）
    返回 (verdict_path, reason)：Path=解析成功，None=失败（reason="invalid REV-ID format"|"resolve error"）
    注：文件是否存在由调用方检查（verdict_path.exists()），本函数不保证。

    rev2 迁入 + path traversal 防护（F-21）；rev3 M-5 改返回 tuple 提供差异化诊断。
    """
    if not rev_id.startswith("REV-"):
        return None, "invalid REV-ID format"
    rest = rev_id[4:]  # 去掉 "REV-"

    parts = rest.split("-")
    if len(parts) < 4 or parts[0] != "REQ":
        return None, "invalid REV-ID format"

    req_id = f"{parts[0]}-{parts[1]}-{parts[2]}"
    filename_stem = rest[len(req_id) + 1:]
    if not filename_stem:
        return None, "invalid REV-ID format"

    # path traversal 防护（rev2 F-21）
    if ".." in filename_stem or "/" in filename_stem:
        return None, "invalid REV-ID format"
    verdict_path = REQUIREMENTS_DIR / req_id / "reviews" / f"{filename_stem}.json"
    try:
        resolved = verdict_path.resolve()
        reviews_root = (REQUIREMENTS_DIR / req_id / "reviews").resolve()
        if not str(resolved).startswith(str(reviews_root) + "/"):
            return None, "resolve error"
    except (OSError, ValueError):
        return None, "resolve error"
    return verdict_path, ""


_DEFAULT_BASE_CACHE: str | None = None  # 模块级单进程缓存（N-3）


def _detect_default_base() -> str:
    """推导仓库默认 base 分支（带模块级缓存 + 0.5s timeout）。
    优先 git symbolic-ref refs/remotes/origin/HEAD；fallback main → develop → master。

    F-012 rev3 新增：解决旧版硬编码 base="main" 的 M-2 问题。
    本仓库默认分支为 develop，硬编码 main 会导致 --trivial 通道跑错 diff 范围。
    F-012 rev4 修 M-4'/N-3：加模块级缓存避免重复 fork；timeout 缩到 0.5s
    （CI shallow clone fallback 最坏 4 fork × 0.5s = 2s，而非旧版 8s）。
    """
    global _DEFAULT_BASE_CACHE
    if _DEFAULT_BASE_CACHE is not None:
        return _DEFAULT_BASE_CACHE

    result: str
    try:
        cp = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            timeout=0.5,
            cwd=REPO_ROOT,
        )
        if cp.returncode == 0:
            ref = cp.stdout.strip()  # e.g. "origin/develop"
            if "/" in ref:
                result = ref.split("/", 1)[1]  # "develop"
                _DEFAULT_BASE_CACHE = result
                return result
    except (subprocess.SubprocessError, OSError) as exc:
        _log.warning("_detect_default_base: symbolic-ref failed: %s", exc)
    # fallback：检查 main / develop / master 是否存在 ref
    for candidate in ("main", "develop", "master"):
        try:
            cp = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{candidate}"],
                capture_output=True,
                text=True,
                timeout=0.5,
                cwd=REPO_ROOT,
            )
            if cp.returncode == 0:
                _DEFAULT_BASE_CACHE = candidate
                return candidate
        except (subprocess.SubprocessError, OSError) as exc:
            _log.warning("_detect_default_base: rev-parse %s failed: %s", candidate, exc)
            continue
    _DEFAULT_BASE_CACHE = "main"
    return "main"  # 最后兜底


def _reset_default_base_cache() -> None:
    """测试用：重置模块级缓存，防 fixture 间污染。"""
    global _DEFAULT_BASE_CACHE
    _DEFAULT_BASE_CACHE = None


def _get_trivial_diff_paths(base: str | None = None) -> list[str]:
    """获取 --trivial diff 文件列表（ACMR）；base=None 时自动推导。（rev3 M-2 修）"""
    if base is None:
        base = _detect_default_base()
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}..HEAD"],
            text=True,
            cwd=REPO_ROOT,
        )
        return [p for p in out.strip().splitlines() if p]
    except (subprocess.SubprocessError, OSError) as exc:
        _log.warning("_get_trivial_diff_paths: git diff failed: %s", exc)
        # git diff 失败视为有非文档文件（保守策略）
        return ["<git-diff-failed>"]


def _get_git_email() -> str | None:
    """从 git config 取 user.email；失败或格式非法返回 None。（F-012 rev2 迁入）"""
    try:
        email = subprocess.check_output(
            ["git", "config", "user.email"],
            text=True,
            cwd=REPO_ROOT,
        ).strip()
    except (subprocess.SubprocessError, OSError) as exc:
        _log.warning("_get_git_email: git config failed: %s", exc)
        email = ""
    if not email or not _EMAIL_RE.match(email):
        return None
    return email


def _check_args_mutex(args: argparse.Namespace) -> int | None:
    """--trivial 与 --decision 互斥校验；None=放行，int=退出码。（rev3 M-3 拆出）"""
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
    return None


def _validate_signed_by(args: argparse.Namespace) -> tuple[str | None, int | None]:
    """email 格式校验 + _get_git_email fallback；(signed_by, rc)。（rev3 M-3 拆出）"""
    if args.signed_by is not None:
        if not _EMAIL_RE.match(args.signed_by):
            print(paint("❌ --signed-by 格式非法，应为 email", "red"), file=sys.stderr)
            return None, 1
        return args.signed_by, None
    else:
        signed_by = _get_git_email()
        if signed_by is None:
            print("signoff: 无法获取 git config user.email，请先配置", file=sys.stderr)
            return None, 1
        return signed_by, None


def _append_signoff_process_log(
    req_id: str, rev_id: str, decision: str, signed_by: str
) -> None:
    """追加 signoff 事件到 process.txt；req_id 空时静默跳过。（rev2 迁入 / rev4 CC 优化）"""
    if not req_id:
        return
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


def _resolve_signoff_decision(args: argparse.Namespace) -> tuple[str | None, list[str], int | None]:
    """--trivial 路径白名单判定 + decision 确定；返回 (decision, diff_paths, rc)。（rev3 M-3）"""
    if args.trivial:
        diff_paths = _get_trivial_diff_paths()
        all_doc, non_doc = _check_trivial_paths(diff_paths)
        if not all_doc:
            paths_str = " ".join(non_doc)
            print(f"trivial: non-doc files detected: {paths_str}", file=sys.stderr)
            return None, diff_paths, 3
        # --trivial 通过 → 强制 decision = approved-trivial
        return "approved-trivial", diff_paths, None
    else:
        return args.decision, [], None


def _load_and_validate_verdict(
    verdict_path: Path,
) -> tuple[dict | None, int | None]:
    """读取并预检 verdict；JSON 异常→rc=6，已签字→rc=5；(verdict, rc)。（rev4 M-3' 拆出）"""
    try:
        with verdict_path.open("r", encoding="utf-8") as f:
            verdict = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(paint(f"❌ verdict file corrupted: {rel(verdict_path)}: {exc}", "red"), file=sys.stderr)
        return None, 6

    # 检查是否已签字（防重复签名）
    existing_sig = verdict.get("human_signoff") or {}
    if existing_sig.get("decision"):
        existing_by = existing_sig.get("signed_by", "unknown")
        existing_at = existing_sig.get("signed_at", "unknown")
        print(f"signoff: already signed by {existing_by} at {existing_at}", file=sys.stderr)
        return None, 5

    return verdict, None


def _run_cr_checks(verdict: dict, verdict_path: Path) -> int | None:
    """加载 schema + 全量重跑 CR-1~CR-8；schema 缺失或 CR 失败→rc=1；通过→None。（rev4 M-3'）"""
    import save_review as _sr  # noqa: PLC0415

    try:
        schema = _sr._load_schema()
    except FileNotFoundError as exc:
        print(paint(f"❌ schema 文件缺失: {exc}", "red"), file=sys.stderr)
        return 1
    except _sr.yaml.YAMLError as exc:
        print(paint(f"❌ schema 文件格式错误: {exc}", "red"), file=sys.stderr)
        return 1

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

    return None


def _commit_signoff(
    verdict: dict, verdict_path: Path, rev_id: str, decision: str, signed_by: str
) -> int:
    """原子写盘（tmp+rename）+ 追加 process.txt；成功→0，OSError→1。（rev5 F-15 拆出）"""
    # F-012 rev6 F-10：进程隔离命名防多进程并发互删 tmp 文件
    import os
    tmp_path = verdict_path.with_suffix(f".{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(verdict, f, ensure_ascii=False, indent=2)
            f.write("\n")
        tmp_path.replace(verdict_path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        # F-012 rev6 F-8：用 rel(tmp_path) 显式给路径，不依赖 {exc} 默认 str 泄露绝对路径
        print(paint(f"❌ verdict 写盘失败（路径 {rel(tmp_path)}: {exc.strerror or exc}）", "red"), file=sys.stderr)
        return 1
    print(paint(f"✓ human_signoff 已写入 {rel(verdict_path)}", "green"))
    req_id_str = verdict.get("requirement_id", "")
    _append_signoff_process_log(req_id_str, rev_id, decision, signed_by)
    return 0


def run_signoff(args: argparse.Namespace) -> int:
    """signoff 子命令公开入口：把 human_signoff 字段写入已有 verdict 文件。

    F-012 rev2 从 save_review._run_signoff 迁入并公开（改名 run_signoff）。
    F-012 rev3 M-3：拆 3 helper（_check_args_mutex / _resolve_signoff_decision / _validate_signed_by）。
    F-012 rev4 M-3'：再拆 2 helper（_load_and_validate_verdict / _run_cr_checks），CC 14→≤10。

    流程（F-012 重构后单一入口）：
      0. D-003 深防御：校验 stdin 必须为 tty（防 AI 代签；不允许 env var 旁路）
      1. 模式互斥校验：--trivial 与 --decision 不能同时使用
      2. --trivial 模式：跑路径白名单 → 通过则强制 decision=approved-trivial
      3. 自动填充 signed_by（git config user.email）/ signed_at（ISO8601 now）
         若未通过 CLI 显式提供；--signed-by 显式传入时校验 email 格式
      4. 从 REV-ID 定位 verdict 文件 → _load_and_validate_verdict（JSON/已签字检查）
      5. 写 human_signoff 字段 → _run_cr_checks（全量重跑 CR-1~CR-8）
      6. 通过 → 写盘 + append process.txt；失败 → 退出码 1 + stderr CR 详情

    退出码：
      0 — 签字成功
      1 — 参数非法（互斥冲突 / --signed-by 格式非法 / 缺 git email / schema 文件缺失 / CR 校验失败）
      2 — 非 tty stdin
      3 — --trivial 通道：diff 含非文档文件
      4 — verdict 文件不存在
      5 — 已签字
      6 — verdict 文件解析失败（JSON 损坏 / IO 错误）

    ⚠️ CC=10 顶格；下次新增分支前必须先拆 helper（避免 rev6+1 再次溢出）。
    """
    # 步骤 0：tty 校验（D-003 深防御；FAKE_TTY 等 env var 红线封禁）
    if not sys.stdin.isatty():
        print("signoff: stdin not a tty, refuse to sign for AI", file=sys.stderr)
        return 2

    # 步骤 1：模式互斥校验
    rc = _check_args_mutex(args)
    if rc is not None:
        return rc

    # 步骤 2：--trivial 路径白名单判定 + decision 确定
    decision, _diff_paths, rc = _resolve_signoff_decision(args)
    if rc is not None:
        return rc

    # 步骤 3：自动填充 signed_by / signed_at（CLI 未提供时从 git / now 取）
    signed_by, rc = _validate_signed_by(args)
    if rc is not None:
        return rc
    signed_at = args.signed_at or _get_iso8601_now()

    # 步骤 4：定位 verdict 文件 + 已签字预检
    rev_id = args.rev_id
    verdict_path, reason = _resolve_verdict_path(rev_id)
    if verdict_path is None:
        print(f"signoff: {reason}: {rev_id}", file=sys.stderr)
        return 4
    if not verdict_path.exists():
        print(f"signoff: verdict file missing: {rel(verdict_path)}", file=sys.stderr)
        return 4

    verdict, rc = _load_and_validate_verdict(verdict_path)
    if rc is not None:
        return rc

    # 步骤 5：写入 human_signoff 字段
    verdict["human_signoff"] = {  # type: ignore[index]
        "decision": decision,
        "signed_at": signed_at,
        "signed_by": signed_by,
        "source": args.source,
    }

    rc = _run_cr_checks(verdict, verdict_path)  # type: ignore[arg-type]
    if rc is not None:
        return rc

    # 步骤 6：写盘（原子替换）+ append process.txt
    return _commit_signoff(verdict, verdict_path, rev_id, decision, signed_by)  # type: ignore[arg-type]


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
