"""code-review-prepare 的卡点 A 路由 CLI。

功能：
  - 扫 diff（或从 stdin 读 --diff-stat-stdin），按关键字规则生成 checker_route 候选
  - tty 校验：非 tty 环境拒绝运行（退出码 2），防止 AI 自动绕过卡点 A
  - 交互确认：accept / all / abort / 自定义子集（逗号分隔下标）
  - 写 .review-scope.json（含 routing_confirmed_by 子段）

用法：
  python3 scripts/lib/code_review_routing.py [--all] [--trivial] [--diff-stat-stdin] [--scope-out PATH]

退出码：
  0 — 正常完成（含 abort 用户取消）
  1 — 输入非法（无效 token、email 格式错误）
  2 — 非 tty stdin，拒绝交互确认

测试钩子：
  CODE_REVIEW_ROUTING_FAKE_TTY=1 — 仅供 pytest 模拟 tty 场景（生产路径禁止使用）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# 8 个 checker 全集（固定顺序）
ALL_CHECKERS: list[str] = [
    "complexity-checker",
    "security-checker",
    "concurrency-checker",
    "performance-checker",
    "error-handling-checker",
    "design-consistency-checker",
    "history-context-checker",
    "auxiliary-spec-checker",
]

# 各 checker 的关键字匹配规则（正则，命中则进入候选路由）
_CHECKER_PATTERNS: dict[str, re.Pattern[str]] = {
    "security-checker": re.compile(
        r"password|secret|token|sql|[Dd]ao", re.IGNORECASE
    ),
    "concurrency-checker": re.compile(
        r"sync|mutex|lock|goroutine|async", re.IGNORECASE
    ),
    "performance-checker": re.compile(
        r"N\+1|for\s+\w+\s+query|range\s+loop", re.IGNORECASE
    ),
}

# 默认全跑的 checker（无关键字规则，宁滥勿缺）
_DEFAULT_RUN_CHECKERS: list[str] = [
    c for c in ALL_CHECKERS if c not in _CHECKER_PATTERNS
]

# 合法 email 格式（git config user.email 的简单校验）
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_tty() -> bool:
    """检测 stdin 是否为 tty。支持测试钩子 CODE_REVIEW_ROUTING_FAKE_TTY=1。"""
    if os.environ.get("CODE_REVIEW_ROUTING_FAKE_TTY") == "1":
        return True
    return sys.stdin.isatty()


def _get_git_email() -> str:
    """从 git config 读取 user.email；空值或非法格式 → 退出码 1。"""
    try:
        email = subprocess.check_output(
            ["git", "config", "user.email"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        email = ""

    # 空值或主机名（无 @ 符号）视为无效
    if not email or "@" not in email:
        print(f"routing: invalid email {email!r}", file=sys.stderr)
        sys.exit(1)

    if not _EMAIL_RE.match(email):
        print(f"routing: invalid email {email!r}", file=sys.stderr)
        sys.exit(1)

    return email


def _get_diff_text(diff_stat_stdin: bool) -> str:
    """获取 diff 文本：--diff-stat-stdin 从 stdin 读，否则运行 git diff。"""
    if diff_stat_stdin:
        return sys.stdin.read()
    try:
        return subprocess.check_output(
            ["git", "diff", "--stat", "main...HEAD"], text=True
        )
    except subprocess.CalledProcessError:
        # diff 失败时返回空字符串，不阻塞流程
        return ""


def _build_checker_route(diff_text: str) -> tuple[list[str], list[dict[str, str]]]:
    """根据 diff 文本生成候选 checker_route 和 skipped_checkers。

    规则：
    - 有关键字规则的 checker：命中则进候选，未命中进 skipped（注明原因）
    - 无关键字规则的 checker：默认全跑（宁滥勿缺，遵循 R2 漏跑风险规避）

    返回：(checker_route, skipped_checkers)
    """
    route: list[str] = list(_DEFAULT_RUN_CHECKERS)  # 默认全跑的先加进来
    skipped: list[dict[str, str]] = []

    for checker, pattern in _CHECKER_PATTERNS.items():
        # 提取 checker 类别名（去掉 -checker 后缀）用于日志
        category = checker.replace("-checker", "")
        if pattern.search(diff_text):
            route.append(checker)
        else:
            skipped.append({
                "name": checker,
                "reason": f"diff 未命中 {category} 关键字",
            })

    # 按 ALL_CHECKERS 顺序对 route 排序，保持稳定输出
    order_map = {c: i for i, c in enumerate(ALL_CHECKERS)}
    route.sort(key=lambda c: order_map.get(c, 999))

    return route, skipped


def _print_route_prompt(
    route: list[str], skipped: list[dict[str, str]]
) -> None:
    """在 tty 上输出候选 checker 列表 + skipped 原因，供用户确认。"""
    print("\n===== 卡点 A：路由建议 =====", flush=True)
    print("候选 checker（AI 建议执行）：", flush=True)
    for i, name in enumerate(route):
        print(f"  [{i}] {name}", flush=True)

    if skipped:
        print("\n跳过的 checker（diff 未命中关键字）：", flush=True)
        for item in skipped:
            print(f"  - {item['name']}: {item['reason']}", flush=True)

    print(
        "\n请选择操作：",
        flush=True,
    )
    print(
        "  accept          — 接受 AI 建议的候选列表",
        flush=True,
    )
    print(
        "  all             — 运行全部 8 个 checker",
        flush=True,
    )
    print(
        "  abort           — 取消本次审查",
        flush=True,
    )
    print(
        "  1,3,5           — 自定义子集（逗号分隔下标）",
        flush=True,
    )
    print("请输入：", end="", flush=True)


def _parse_user_input(
    raw: str, route: list[str]
) -> tuple[list[str], str]:
    """解析用户输入，返回 (final_route, decision)。

    非法 token → 直接 sys.exit(1) 并输出 stderr。
    abort → 返回 ([], 'abort')，由调用方处理。
    """
    token = raw.strip().lower()

    if token == "accept":
        return route, "accept"

    if token == "all":
        return list(ALL_CHECKERS), "all"

    if token == "abort":
        return [], "abort"

    # 尝试解析逗号分隔下标
    parts = token.split(",")
    indices: list[int] = []
    for p in parts:
        p = p.strip()
        if not p.isdigit():
            print(f"routing: invalid token {raw!r}", file=sys.stderr)
            sys.exit(1)
        idx = int(p)
        if idx < 0 or idx >= len(route):
            print(f"routing: invalid token {raw!r}", file=sys.stderr)
            sys.exit(1)
        indices.append(idx)

    if not indices:
        print(f"routing: invalid token {raw!r}", file=sys.stderr)
        sys.exit(1)

    custom_route = [route[i] for i in indices]
    return custom_route, "custom"


def _build_scope_patch(
    final_route: list[str],
    skipped: list[dict[str, str]],
    mode_hint: str,
    decision: str,
    email: str,
) -> dict:
    """构造 scope.json 中新增的 4 个字段。"""
    return {
        "checker_route": final_route,
        "skipped_checkers": skipped,
        "mode_hint": mode_hint,
        "routing_confirmed_by": {
            "decision": decision,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "confirmed_by": email,
            "tty_verified": True,
        },
    }


def _load_existing_scope(scope_out: str) -> dict:
    """读取已有 scope.json（若存在），否则返回空 dict。"""
    path = Path(scope_out)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_scope(scope_out: str, data: dict) -> None:
    """将 scope dict 序列化写入文件。"""
    path = Path(scope_out)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"routing: .review-scope.json 已写入 {scope_out}", flush=True)


def _run_all_mode(scope_out: str, trivial: bool) -> None:
    """--all 模式：跳过路由建议，但仍要求 tty（防 AI 绕过卡点 A）。"""
    # tty 校验（--all 也不豁免）
    if not _is_tty():
        print(
            "routing: stdin not a tty, refuse interactive confirmation",
            file=sys.stderr,
        )
        sys.exit(2)

    email = _get_git_email()
    mode_hint = "trivial" if trivial else "all"
    scope = _load_existing_scope(scope_out)
    patch = _build_scope_patch(
        final_route=list(ALL_CHECKERS),
        skipped=[],
        mode_hint=mode_hint,
        decision="all",
        email=email,
    )
    scope.update(patch)
    _write_scope(scope_out, scope)


def _run_default_mode(
    scope_out: str, trivial: bool, diff_stat_stdin: bool
) -> None:
    """默认模式（含 --trivial）：扫 diff → tty 确认 → 写盘。"""
    # tty 校验
    if not _is_tty():
        print(
            "routing: stdin not a tty, refuse interactive confirmation",
            file=sys.stderr,
        )
        sys.exit(2)

    email = _get_git_email()

    # 扫 diff 生成候选
    diff_text = _get_diff_text(diff_stat_stdin)
    route, skipped = _build_checker_route(diff_text)

    # 输出候选给用户确认
    _print_route_prompt(route, skipped)

    # 读取用户输入
    raw = sys.stdin.readline()
    final_route, decision = _parse_user_input(raw, route)

    if decision == "abort":
        print("routing: aborted by user", file=sys.stderr)
        # 不写盘，直接正常退出
        return

    # mode_hint：--trivial 时写 trivial，否则按 decision
    if trivial:
        mode_hint = "trivial"
    elif decision == "all":
        mode_hint = "all"
    else:
        mode_hint = "default"

    scope = _load_existing_scope(scope_out)
    patch = _build_scope_patch(
        final_route=final_route,
        skipped=skipped,
        mode_hint=mode_hint,
        decision=decision,
        email=email,
    )
    scope.update(patch)
    _write_scope(scope_out, scope)


def main(argv: list[str] | None = None) -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="code-review-prepare 卡点 A：路由建议 + tty 确认 + scope.json 写盘"
    )
    parser.add_argument(
        "--all",
        dest="run_all",
        action="store_true",
        help="跳过路由建议，直接用 8 全集（仍要求 tty）",
    )
    parser.add_argument(
        "--trivial",
        action="store_true",
        help="透传 mode_hint=trivial，不豁免卡点 A",
    )
    parser.add_argument(
        "--diff-stat-stdin",
        action="store_true",
        help="从 stdin 读 diff 文本（而非运行 git diff）",
    )
    parser.add_argument(
        "--scope-out",
        default=".review-scope.json",
        help="scope.json 输出路径（默认：.review-scope.json）",
    )

    args = parser.parse_args(argv)

    if args.run_all:
        _run_all_mode(args.scope_out, args.trivial)
    else:
        _run_default_mode(args.scope_out, args.trivial, args.diff_stat_stdin)


if __name__ == "__main__":
    main()
