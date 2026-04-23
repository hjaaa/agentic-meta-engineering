"""plan.md 新鲜度 + 非占位符软校验。

plan.md 是"阶段级活文档"（见 skeleton-design §6.2），设计上每次阶段切换
应刷新。由于内容主观（目标/范围/风险均为自然语言），不做硬门禁，仅
输出 warning 提醒主 Agent 回头对齐。配合 gate-checklist 做软检查入口。

检查项：
  E001  plan.md 不存在（bootstrap 门禁硬要求）
  W001  plan.md 仍保留模板占位符（目标/风险未填）
  W002  plan.md mtime 早于进入当前 phase 的时间（未随阶段刷新）
  W003  范围段 '不包含' 无子条目（scope 防守缺口）

事实源：
  context/team/engineering-spec/specs/2026-04-20-agentic-engineering-skeleton-design.md §6.2
  .claude/skills/managing-requirement-lifecycle/templates/plan.md.tmpl

用法：
  python3 scripts/lib/check_plan.py requirements/<REQ-ID>
  python3 scripts/lib/check_plan.py --requirement <REQ-ID>
  python3 scripts/lib/check_plan.py --all [--strict]

退出码见 common.py。
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import REPO_ROOT, Report, Severity, paint, rel

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# 占位符：取自 plan.md.tmpl 中最具辨识度的片段
# 改模板时需同步此列表
TEMPLATE_MARKERS: tuple[str, ...] = (
    "一句话描述本需求要交付什么业务价值",
    "风险 1：描述 / 应对",
    "__TITLE__",
    "__REQ_ID__",
)

RE_PHASE = re.compile(r"^phase:\s*(\S+)", re.MULTILINE)
RE_PHASE_TRANSITION = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+\[phase-transition\]\s+\S+\s+→\s+(?P<to>\S+)",
    re.MULTILINE,
)
RE_SCOPE_EXCLUDE = re.compile(r"^-\s*不包含\s*[：:]?\s*$", re.MULTILINE)
RE_TOP_BULLET = re.compile(r"^[-*]\s+\S")
RE_NESTED_BULLET = re.compile(r"^\s+[-*]\s+\S")
RE_HEADING = re.compile(r"^#{1,6}\s+\S")


def _current_phase(meta_file: Path) -> str | None:
    if not meta_file.exists():
        return None
    m = RE_PHASE.search(meta_file.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def _phase_enter_time(process_file: Path, phase: str) -> datetime | None:
    """取 process.txt 中最后一条 `→ <phase>` 的时间戳（UTC naive）。"""
    if not process_file.exists():
        return None
    last_ts: datetime | None = None
    for m in RE_PHASE_TRANSITION.finditer(process_file.read_text(encoding="utf-8")):
        if m.group("to") != phase:
            continue
        try:
            last_ts = datetime.strptime(m.group("ts"), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
    return last_ts


def _scope_exclude_items(plan_text: str) -> int:
    """统计"- 不包含：" 行下的同级子条目数。

    模板中"- 不包含："是顶级列表项，子条目期望缩进（2 空格 或 tab）。
    遇到下一个顶级 bullet / 标题 / 空行后的非列表内容 即视为段落结束。
    """
    lines = plan_text.splitlines()
    count = 0
    in_section = False
    pending_blank = False
    for line in lines:
        if RE_SCOPE_EXCLUDE.match(line):
            in_section = True
            pending_blank = False
            continue
        if not in_section:
            continue
        if not line.strip():
            pending_blank = True
            continue
        if RE_HEADING.match(line):
            break
        if RE_TOP_BULLET.match(line):
            # 下一个顶级 bullet（如"- 里程碑"）—— 段落结束
            break
        if RE_NESTED_BULLET.match(line):
            count += 1
            pending_blank = False
            continue
        if pending_blank:
            # 空行后出现非列表正文 —— 段落结束
            break
    return count


def check_requirement(req_dir: Path, report: Report) -> None:
    req_label = rel(req_dir)
    plan_file = req_dir / "plan.md"
    meta_file = req_dir / "meta.yaml"
    process_file = req_dir / "process.txt"

    if not plan_file.exists():
        report.add(
            req_label,
            Severity.ERROR,
            "E001",
            "plan.md 不存在（bootstrap 门禁硬要求）",
        )
        return

    plan_text = plan_file.read_text(encoding="utf-8")
    plan_label = rel(plan_file)

    found_markers = [m for m in TEMPLATE_MARKERS if m in plan_text]
    if found_markers:
        preview = "、".join(
            f'"{m[:20]}…"' if len(m) > 20 else f'"{m}"' for m in found_markers[:2]
        )
        report.add(
            plan_label,
            Severity.WARNING,
            "W001",
            f"保留 {len(found_markers)} 处模板占位符（{preview}），目标/风险疑似未填",
        )

    phase = _current_phase(meta_file)
    if phase and phase != "bootstrap":
        enter_ts = _phase_enter_time(process_file, phase)
        if enter_ts is not None:
            mtime = datetime.fromtimestamp(plan_file.stat().st_mtime, tz=timezone.utc)
            if mtime < enter_ts:
                report.add(
                    plan_label,
                    Severity.WARNING,
                    "W002",
                    (
                        f"mtime {mtime:%Y-%m-%dT%H:%M:%SZ} 早于进入 {phase} "
                        f"阶段（{enter_ts:%Y-%m-%dT%H:%M:%SZ}），未随阶段刷新"
                    ),
                )

    if _scope_exclude_items(plan_text) == 0:
        report.add(
            plan_label,
            Severity.WARNING,
            "W003",
            "范围段 '不包含' 无子条目（scope 防守缺口）",
        )


def _collect_targets(args: argparse.Namespace) -> list[Path]:
    if args.path:
        p = Path(args.path).resolve()
        if p.is_file() and p.name == "plan.md":
            return [p.parent]
        if p.is_dir():
            return [p]
        print(f"路径无效：{rel(p)}（需指向需求目录或 plan.md）", file=sys.stderr)
        sys.exit(2)
    if args.requirement:
        req_dir = REQUIREMENTS_DIR / args.requirement
        if not req_dir.exists():
            print(f"需求不存在：{rel(req_dir)}", file=sys.stderr)
            sys.exit(2)
        return [req_dir]
    if args.all:
        if not REQUIREMENTS_DIR.exists():
            return []
        return sorted(
            d for d in REQUIREMENTS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".") and (d / "meta.yaml").exists()
        )
    print("必须指定 <path> / --requirement <ID> / --all 之一", file=sys.stderr)
    sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="plan.md 新鲜度 + 非占位符软校验")
    parser.add_argument("path", nargs="?", help="需求目录或 plan.md 路径")
    parser.add_argument("--requirement", help="REQ-ID")
    parser.add_argument("--all", action="store_true", help="扫全部 requirements/")
    parser.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = parser.parse_args(argv)

    targets = _collect_targets(args)
    if not targets:
        print(paint("(无可扫描需求)", "cyan"))
        return 0

    report = Report()
    for req_dir in targets:
        if not req_dir.is_dir():
            continue
        try:
            check_requirement(req_dir, report)
        except OSError as exc:
            print(f"读取失败 {rel(req_dir)}: {exc}", file=sys.stderr)
            return 2

    print(report.render())
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
