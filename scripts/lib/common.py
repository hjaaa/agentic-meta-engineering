"""共享工具：路径、颜色、严重度、退出码约定。

退出码约定（check-meta / check-index 统一）：
  0 — 无 error（warning 允许存在；--strict 时 warning 也算失败）
  1 — 存在 error
  2 — 脚本自身异常（文件找不到、YAML 解析失败等）
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class Severity:
    ERROR = "error"
    WARNING = "warning"


def _is_tty() -> bool:
    return sys.stdout.isatty()


def paint(text: str, color: str) -> str:
    if not _is_tty():
        return text
    codes = {"red": "31", "yellow": "33", "green": "32", "cyan": "36", "bold": "1"}
    code = codes.get(color)
    return f"\033[{code}m{text}\033[0m" if code else text


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


class Report:
    """聚合多文件多条目的 findings。"""

    def __init__(self) -> None:
        self._findings: list[tuple[str, str, str, str]] = []  # (file, severity, code, message)

    def add(self, file: str, severity: str, code: str, message: str) -> None:
        self._findings.append((file, severity, code, message))

    @property
    def errors(self) -> int:
        return sum(1 for _, s, *_ in self._findings if s == Severity.ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for _, s, *_ in self._findings if s == Severity.WARNING)

    def render(self) -> str:
        if not self._findings:
            return paint("✓ 无问题", "green")

        lines = []
        by_file: dict[str, list[tuple[str, str, str]]] = {}
        for f, sev, code, msg in self._findings:
            by_file.setdefault(f, []).append((sev, code, msg))

        for file in sorted(by_file.keys()):
            lines.append(paint(file, "bold"))
            for sev, code, msg in by_file[file]:
                icon = "❌" if sev == Severity.ERROR else "⚠️ "
                color = "red" if sev == Severity.ERROR else "yellow"
                lines.append(f"  {icon} {paint(code, color)}: {msg}")
            lines.append("")

        summary = f"Total: {self.errors} error, {self.warnings} warning"
        lines.append(paint(summary, "cyan"))
        return "\n".join(lines)

    def exit_code(self, strict: bool) -> int:
        if self.errors:
            return 1
        if strict and self.warnings:
            return 1
        return 0
