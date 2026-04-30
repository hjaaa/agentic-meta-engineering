"""卡点 B：code-review-signoff 的 CLI 入口脚本。

功能：
  - tty 二次校验（深防御：即便 Command 层已校验，Skill 层再校验防绕过）
  - 预检：verdict 文件存在性 + 已签字检测 + --decision 合法性
  - --trivial 路径白名单判定（git diff --name-only 全部 ∈ *.md / docs/** / *.txt 才放行）
  - 取 git config user.email → signed_by；ISO8601 含时区 → signed_at
  - 调 save_review.py signoff 子命令完成 schema 校验 + 写盘 + process.txt append

用法：
  python3 scripts/lib/code_review_signoff.py --rev-id <REV-ID> [--decision <v>] [--trivial]

退出码：
  0  — 签字成功
  1  — 参数非法（--decision 非法）
  2  — 非 tty stdin，拒绝 AI 代签
  3  — --trivial 通道：diff 含非文档文件
  4  — verdict 文件不存在
  5  — 已签字

不允许任何 FAKE_TTY / DRY_RUN_TTY 等 env var 旁路（D-003 红线）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 把 scripts/lib 加入路径（支持直接运行也支持 import）
_SCRIPTS_LIB = Path(__file__).resolve().parent
if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

from common import REPO_ROOT  # noqa: E402
from save_review import _resolve_verdict_path  # noqa: E402

# 合法 --decision 枚举
VALID_DECISIONS: list[str] = ["approved", "approved-trivial", "rejected"]

# 文档文件路径白名单正则（--trivial 模式使用）
_DOC_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^.*\.md$"),
    re.compile(r"^docs/.*$"),
    re.compile(r"^.*\.txt$"),
]

# 合法 email 格式（与 code_review_routing.py 保持一致）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_tty() -> bool:
    """检测 stdin 是否为 tty。

    二次 tty 校验（深防御）：防止 Skill 被绕过 Command 直接调用。
    不允许任何 env var 后门旁路（D-003 红线）。
    """
    return sys.stdin.isatty()


def _get_git_email() -> str | None:
    """从 git config 取 user.email；失败或格式非法返回 None。"""
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
    """返回当前时间的 ISO8601 含时区字符串。"""
    return datetime.now(timezone.utc).astimezone().isoformat()


def _check_trivial_paths(diff_paths: list[str]) -> tuple[bool, list[str]]:
    """判断 diff_paths 是否全部属于文档白名单。

    返回：(all_doc, non_doc_paths)
      - all_doc=True 表示全部是文档文件（放行 --trivial）
      - non_doc_paths 是命中白名单之外的路径列表
    """
    non_doc: list[str] = []
    for path in diff_paths:
        if not any(pat.match(path) for pat in _DOC_PATTERNS):
            non_doc.append(path)
    return len(non_doc) == 0, non_doc


def _get_trivial_diff_paths(base: str = "main") -> list[str]:
    """获取 --trivial 模式下的 diff 文件列表（ACMR 变更）。"""
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


def _read_verdict_signoff(verdict_path: Path) -> dict | None:
    """读取 verdict 文件中的 human_signoff 字段；解析失败返回 None。"""
    try:
        with verdict_path.open("r", encoding="utf-8") as f:
            verdict = json.load(f)
        return verdict.get("human_signoff") or {}
    except (json.JSONDecodeError, OSError):
        return None


def _call_save_review_signoff(
    rev_id: str,
    decision: str,
    signed_by: str,
    signed_at: str,
    source: str = "cli-tty",
) -> int:
    """调 save_review.py signoff 子命令，返回退出码。

    这是 Skill 层的最后一步——写盘 + CR 校验 + process.txt append 全部在此完成。
    """
    cmd = [
        sys.executable,
        str(_SCRIPTS_LIB / "save_review.py"),
        "signoff",
        "--rev-id", rev_id,
        "--decision", decision,
        "--signed-by", signed_by,
        "--signed-at", signed_at,
        "--source", source,
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    return result.returncode


def _run_signoff_skill(
    rev_id: str,
    decision: str | None,
    trivial: bool,
) -> int:
    """Skill 核心逻辑（可被单测 mock）。

    步骤：
      1. 二次 tty 校验（深防御）
      2. --trivial 路径白名单判定（仅 --trivial 模式）
      3. 取 git email + ISO8601 时间
      4. 定位 verdict 文件 + 预检（存在性 + 已签字检测）
      5. 调 save_review.py signoff
    """
    # 步骤 1：二次 tty 校验（深防御，防 Skill 被绕过 Command 直接调用）
    if not _check_tty():
        print("signoff: stdin not a tty, refuse to sign for AI", file=sys.stderr)
        return 2

    # 步骤 2：--trivial 路径白名单判定
    if trivial:
        diff_paths = _get_trivial_diff_paths()
        all_doc, non_doc = _check_trivial_paths(diff_paths)
        if not all_doc:
            paths_str = " ".join(non_doc)
            print(f"trivial: non-doc files detected: {paths_str}", file=sys.stderr)
            return 3
        # --trivial 通过 → 强制 decision = approved-trivial
        decision = "approved-trivial"
    else:
        # --decision 合法性校验
        if decision not in VALID_DECISIONS:
            print(
                f"signoff: invalid decision {decision!r},"
                f" expected one of {VALID_DECISIONS}",
                file=sys.stderr,
            )
            return 1

    # 步骤 3：取 git email + 时间戳
    signed_by = _get_git_email()
    if signed_by is None:
        print("signoff: 无法获取 git config user.email，请先配置", file=sys.stderr)
        return 1
    signed_at = _get_iso8601_now()

    # 步骤 4：定位 verdict 文件 + 预检
    verdict_path = _resolve_verdict_path(rev_id)
    if verdict_path is None or not verdict_path.exists():
        print(f"signoff: verdict {rev_id} not found", file=sys.stderr)
        return 4

    existing_sig = _read_verdict_signoff(verdict_path)
    if existing_sig is None:
        print("signoff: verdict 文件解析失败", file=sys.stderr)
        return 2
    if existing_sig.get("decision"):
        by = existing_sig.get("signed_by", "unknown")
        at = existing_sig.get("signed_at", "unknown")
        print(f"signoff: already signed by {by} at {at}", file=sys.stderr)
        return 5

    # 步骤 5：调 save_review.py signoff 子命令
    return _call_save_review_signoff(rev_id, decision, signed_by, signed_at)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="卡点 B：human_signoff 写入（tty 校验 + trivial 路径白名单 + schema 校验）"
    )
    parser.add_argument("--rev-id", required=True, help="REV-ID，如 REV-REQ-2026-003-definition-001")
    parser.add_argument(
        "--decision",
        default=None,
        choices=VALID_DECISIONS,
        help="sign-off 决策（--trivial 模式自动设为 approved-trivial）",
    )
    parser.add_argument(
        "--trivial",
        action="store_true",
        help="纯文档变更快速通道：git diff 全部 ∈ *.md/docs/**/-.txt 才放行",
    )

    args = parser.parse_args(argv)

    # --trivial 与 --decision 互斥检查
    if args.trivial and args.decision is not None:
        print(
            "signoff: --trivial 与 --decision 不能同时使用（--trivial 自动设 approved-trivial）",
            file=sys.stderr,
        )
        return 1

    # 非 --trivial 模式必须有 --decision
    if not args.trivial and args.decision is None:
        print(
            f"signoff: 必须指定 --decision，可选值 {VALID_DECISIONS}",
            file=sys.stderr,
        )
        return 1

    return _run_signoff_skill(args.rev_id, args.decision, args.trivial)


if __name__ == "__main__":
    sys.exit(main())
