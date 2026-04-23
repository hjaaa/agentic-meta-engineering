"""刨根问底（Source-or-Mark）三态校验。

把"每条关键信息必须三态之一"这条软约束下沉为可执行检查。

检查项：
  E001  [待补充] 段落缺假设四要素（内容/依据/风险/验证时机）至少 3 个
  E002  （来源：...）引用路径不存在
  E003  （来源：path:N）行号超出目标文件
  W001  出现 [待用户确认]/[待补充] 但文档缺 '## 待澄清清单' 章节
  W002  段落含强约束数字断言但整段无三态标记（疑似第四态幻觉）
  W003  待澄清清单条目数少于 [待用户确认] + [待补充] 标记总数

事实源：
  context/team/ai-collaboration.md §"规则一：刨根问底（Source-or-Mark）"
  .claude/skills/requirement-doc-writer/reference/sourcing-rules.md

用法：
  python3 scripts/lib/check_sourcing.py <path.md> [--strict]
  python3 scripts/lib/check_sourcing.py --requirement <REQ-ID> [--strict]
  python3 scripts/lib/check_sourcing.py --all [--strict]

退出码见 common.py。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from common import REPO_ROOT, Report, Severity, paint, rel

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# 中英文括号均兼容；来源关键字后允许中英文冒号
RE_SRC = re.compile(r"[（(]\s*来源\s*[：:]\s*([^）)]+?)\s*[）)]")
RE_PENDING_USER = re.compile(r"\[待用户确认\]")
RE_PENDING_FILL = re.compile(r"\[待补充\]")

ASSUMPTION_ELEMENTS = ("内容", "依据", "风险", "验证时机")

# 强约束动词 + 后续 30 字内出现数字，视为断言信号
RE_CONSTRAINT = re.compile(
    r"(必须|不得|禁止|只能|至少|不超过|不少于|默认|最多|最少).{0,30}?\d"
)

RE_CLARIFY_HEADING = re.compile(r"^#{2,6}\s*待澄清清单?\s*$")
RE_LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\S")
RE_HEADING = re.compile(r"^#{1,6}\s+\S")
RE_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def _split_paragraphs(text: str) -> list[tuple[int, str]]:
    """按空行切段，返回 [(起始行号 1-based, 段内容), ...]。"""
    paras: list[tuple[int, str]] = []
    buf: list[str] = []
    start: int | None = None
    for idx, line in enumerate(text.splitlines(), start=1):
        if line.strip() == "":
            if buf:
                paras.append((start or idx, "\n".join(buf)))
                buf = []
                start = None
        else:
            if start is None:
                start = idx
            buf.append(line)
    if buf:
        paras.append((start or 1, "\n".join(buf)))
    return paras


def _strip_code_blocks(text: str) -> str:
    """把 ``` 围栏的代码块置空，避免把示例当成断言。"""
    out: list[str] = []
    in_block = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_block = not in_block
            out.append("")
            continue
        out.append("" if in_block else line)
    return "\n".join(out)


def _has_any_marker(para: str) -> bool:
    return bool(
        RE_SRC.search(para) or RE_PENDING_USER.search(para) or RE_PENDING_FILL.search(para)
    )


def _count_elements(para: str) -> int:
    return sum(1 for kw in ASSUMPTION_ELEMENTS if kw in para)


def _resolve_reference(ref: str, md_file: Path) -> tuple[Path | None, int | None]:
    """解析 `path` 或 `path:line` / `path#line`。"""
    ref = ref.strip().rstrip("。，,.")
    m = re.match(r"^(?P<p>[^:#]+?)(?:[:#](?P<l>\d+))?\s*$", ref)
    if not m:
        return None, None
    p = m.group("p").strip()
    line = int(m.group("l")) if m.group("l") else None

    candidates: list[Path] = []
    if p.startswith("/"):
        candidates.append(Path(p))
    candidates.append((md_file.parent / p).resolve())
    candidates.append((REPO_ROOT / p.lstrip("/")).resolve())
    for c in candidates:
        try:
            if c.exists():
                return c, line
        except OSError:
            continue
    return None, line


def _clarify_section_stats(lines: list[str]) -> tuple[bool, int]:
    """返回 (是否找到'待澄清清单'章节, 清单下条目数)。"""
    found = False
    items = 0
    in_section = False
    for line in lines:
        if RE_CLARIFY_HEADING.match(line):
            found = True
            in_section = True
            continue
        if in_section and RE_HEADING.match(line):
            in_section = False
            continue
        if in_section and RE_LIST_ITEM.match(line):
            items += 1
    return found, items


def check_file(md_file: Path, report: Report) -> None:
    raw_text = md_file.read_text(encoding="utf-8")
    text = _strip_code_blocks(raw_text)
    lines = text.splitlines()
    paras = _split_paragraphs(text)
    file_label = rel(md_file)

    # E001：[待补充] 要素至少 3 个（内容/依据/风险/验证时机）
    for start, content in paras:
        if RE_PENDING_FILL.search(content) and _count_elements(content) < 3:
            report.add(
                file_label,
                Severity.ERROR,
                "E001",
                f"第 {start} 行 [待补充] 缺假设要素（内容/依据/风险/验证时机≥3）",
            )

    # E002 / E003：引用存在性与行号
    for m in RE_SRC.finditer(raw_text):
        raw_ref = m.group(1)
        line_no = raw_text[: m.start()].count("\n") + 1
        resolved, line = _resolve_reference(raw_ref, md_file)
        if resolved is None:
            report.add(
                file_label,
                Severity.ERROR,
                "E002",
                f"第 {line_no} 行引用路径不存在：{raw_ref}",
            )
            continue
        if line is not None:
            try:
                total = sum(
                    1 for _ in resolved.open("r", encoding="utf-8", errors="ignore")
                )
            except OSError:
                total = 0
            if line > total:
                report.add(
                    file_label,
                    Severity.ERROR,
                    "E003",
                    f"第 {line_no} 行引用 {raw_ref} 行号超出目标文件（共 {total} 行）",
                )

    # W001 / W003：待澄清清单
    pending_count = len(RE_PENDING_USER.findall(raw_text)) + len(
        RE_PENDING_FILL.findall(raw_text)
    )
    has_section, item_count = _clarify_section_stats(raw_text.splitlines())
    if pending_count > 0 and not has_section:
        report.add(
            file_label,
            Severity.WARNING,
            "W001",
            f"文档含 {pending_count} 处 [待用户确认]/[待补充] 但缺 '## 待澄清清单' 章节",
        )
    elif has_section and item_count < pending_count:
        report.add(
            file_label,
            Severity.WARNING,
            "W003",
            f"待澄清清单条目 {item_count} 条 < 标记总数 {pending_count}",
        )

    # W002：疑似第四态（强约束数字断言且整段无三态标记）
    for start, content in paras:
        if not RE_CONSTRAINT.search(content):
            continue
        if _has_any_marker(content):
            continue
        # 表格行跳过
        if all(RE_TABLE_ROW.match(ln) or not ln.strip() for ln in content.splitlines()):
            continue
        # 模板占位跳过
        if "__" in content:
            continue
        report.add(
            file_label,
            Severity.WARNING,
            "W002",
            f"第 {start} 行起段落含强约束数字断言但缺三态标记（疑似第四态）",
        )


def _collect_targets(args: argparse.Namespace) -> list[Path]:
    if args.path:
        return [Path(args.path).resolve()]
    if args.requirement:
        req_dir = REQUIREMENTS_DIR / args.requirement / "artifacts"
        if not req_dir.exists():
            print(f"需求不存在或无 artifacts/：{rel(req_dir)}", file=sys.stderr)
            sys.exit(2)
        return sorted(req_dir.rglob("*.md"))
    if args.all:
        if not REQUIREMENTS_DIR.exists():
            return []
        return sorted(REQUIREMENTS_DIR.glob("*/artifacts/**/*.md"))
    print("必须指定 <path> / --requirement <ID> / --all 之一", file=sys.stderr)
    sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="刨根问底（Source-or-Mark）三态校验")
    parser.add_argument("path", nargs="?", help="单个 .md 文件路径")
    parser.add_argument("--requirement", help="REQ-ID：扫该需求下 artifacts/")
    parser.add_argument("--all", action="store_true", help="扫全部 requirements/*/artifacts")
    parser.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = parser.parse_args(argv)

    targets = _collect_targets(args)
    if not targets:
        print(paint("(无可扫描文件)", "cyan"))
        return 0

    report = Report()
    for t in targets:
        if not t.exists() or t.suffix != ".md":
            continue
        try:
            check_file(t, report)
        except OSError as exc:
            print(f"读取失败 {rel(t)}: {exc}", file=sys.stderr)
            return 2

    print(report.render())
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
