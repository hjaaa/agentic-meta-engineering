"""sign-off 子模块（F-012 rev2 从 save_review.py 拆出）

⚠️ 本模块**不能作为独立 CLI 入口**——必须通过 save_review.py 的 main() 委托。
原因：save_review.py 顶层 import signoff（L235），signoff.run_signoff 内 lazy import save_review（L359 之后）；
若直接 python3 signoff.py 启动，lazy import 时会触发 save_review 模块级双向加载（~62ms 冷启动 + 反模式风险）。
未来若需独立入口，建议先抽公共 helper 到 save_review_validation.py 解开双向依赖。

来源：requirements/REQ-2026-009/artifacts/detailed-design.md §10.3 + F-012 rev2 ADR（D-016）+ F-012 rev3 ADR（D-017）

⚠️ __all__ 仅暴露 build_signoff_parser 与 run_signoff 供 save_review.py main() 委托用——
  禁止直接 `python3 -m signoff` 启动，禁止其他模块通过 from signoff import * 引入这两个符号。
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import REPO_ROOT, Report, paint, rel

_log = logging.getLogger(__name__)

__all__ = ["run_signoff", "build_signoff_parser"]

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
    except (subprocess.SubprocessError, OSError) as exc:
        _log.warning("_get_git_email: git config failed: %s", exc)
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
    """获取 --trivial 模式下的 diff 文件列表（ACMR 变更）。

    F-012 从 code_review_signoff.py 迁入；F-012 rev2 迁入 signoff.py。
    F-012 rev3 修 M-2：base 由调用方传入或自动推导（_detect_default_base）。
    """
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


def _resolve_verdict_path(rev_id: str) -> tuple[Path | None, str]:
    """从 REV-ID 反推 verdict 文件路径。

    REV-ID 格式：REV-<REQ-ID>-<prefix>-NNN
    示例：REV-REQ-2026-003-definition-001
          REV-REQ-2026-003-code-F-001-001

    返回 (verdict_path, reason)：
      - verdict_path: Path 时表示解析成功（不保证文件存在），reason="" 占位
      - verdict_path: None 时表示解析失败，reason 含具体原因，可选值：
          - "invalid REV-ID format"：REV-ID 格式不符（前缀 / 段数 / 字符集错）
          - "resolve error"：path traversal 检测命中或 Path.resolve() 抛 OSError/ValueError

    注：调用方 run_signoff 在文件不存在时会自行打印 "verdict file missing: {path}"
    （rc=4），那是 verdict_path.exists() 检查的结果，不是本函数返回的 reason。

    F-012 rev2 迁入 signoff.py；加 path traversal 防护。
    F-012 rev3 M-5：改返回 tuple[Path | None, str]，提供差异化诊断信息。
    F-012 rev3 N-4：docstring 补全 reason 取值清单 + 与调用方文案的边界。
    """
    # 格式：REV-REQ-YYYY-NNN-<phase_and_seq>
    if not rev_id.startswith("REV-"):
        return None, "invalid REV-ID format"
    rest = rev_id[4:]  # 去掉 "REV-"

    # REQ-ID 固定为 REQ-YYYY-NNN（3 段 + 连字符）
    parts = rest.split("-")
    # 期望格式：["REQ", "2026", "003", ...phase+seq...]
    if len(parts) < 4 or parts[0] != "REQ":
        return None, "invalid REV-ID format"

    req_id = f"{parts[0]}-{parts[1]}-{parts[2]}"
    # 文件名：rest 去掉 "<req_id>-" 前缀 = 余下的 phase-seq 部分
    filename_stem = rest[len(req_id) + 1:]  # e.g. "definition-001" or "code-F-001-001"
    if not filename_stem:
        return None, "invalid REV-ID format"

    # F-012 rev2 F-21：path traversal 防护
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


def _check_args_mutex(args: argparse.Namespace) -> int | None:
    """步骤 1 互斥校验：--trivial 与 --decision 不能同时使用。

    返回 None 放行继续 / int 退出码（调用方直接 return）。

    F-012 rev3 M-3 从 run_signoff 拆出。
    """
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


def _resolve_signoff_decision(args: argparse.Namespace) -> tuple[str | None, list[str], int | None]:
    """步骤 2 trivial 分支处理：路径白名单判定 + decision 确定。

    返回 (decision, diff_paths, rc)：
      - decision: str 时放行（调用方用此值）
      - rc: int 时调用方直接 return rc

    F-012 rev3 M-3 从 run_signoff 拆出。
    """
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


def _validate_signed_by(args: argparse.Namespace) -> tuple[str | None, int | None]:
    """步骤 3 _EMAIL_RE 校验 + _get_git_email fallback。

    返回 (signed_by, rc)：
      - signed_by: str 时放行
      - rc: int 时调用方直接 return rc

    F-012 rev3 M-3 从 run_signoff 拆出。
    """
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


def run_signoff(args: argparse.Namespace) -> int:
    """signoff 子命令公开入口：把 human_signoff 字段写入已有 verdict 文件。

    F-012 rev2 从 save_review._run_signoff 迁入并公开（改名 run_signoff）。
    F-012 rev3 M-3：拆 3 helper（_check_args_mutex / _resolve_signoff_decision / _validate_signed_by）。

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
        print(f"signoff: verdict file missing: {verdict_path}", file=sys.stderr)
        return 4

    # 读取 verdict 文件
    try:
        with verdict_path.open("r", encoding="utf-8") as f:
            verdict = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(paint(f"❌ verdict file corrupted: {verdict_path}: {exc}", "red"), file=sys.stderr)
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
