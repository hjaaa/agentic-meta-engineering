"""共享工具：路径、颜色、严重度、退出码约定。

退出码约定（check-meta / check-index 统一）：
  0 — 无 error（warning 允许存在；--strict 时 warning 也算失败）
  1 — 存在 error
  2 — 脚本自身异常（文件找不到、YAML 解析失败等）
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class WorkflowError(Exception):
    """workflow 引擎统一异常基类。

    所有 workflow_loader / run_state / dispatcher 等模块的运行时确定性错误
    （文件找不到、状态非法、event 校验失败等）都抛此基类，跨模块 except
    时类对象同一性才能成立（避免重复定义导致 except 条件分支失效）。
    """


def infer_run_id_from_branch(repo_root: Path) -> str | None:
    """从当前 git 分支推断 canonical run_id（feat/req-<id> 格式）。

    返回值：
        str  — 命中目录的 canonical run_id：
                 1) 新 key 格式 feat/req-<YYYYMMDD-slug>：stripped 直接命中目录 → 返 stripped
                 2) 旧 key 格式 feat/req-<YYYY-NNN>：stripped 找不到目录时
                    尝试 REQ-/RUN-/REL- 前缀 + uppercase → 命中即返回带前缀形式
                 3) 都找不到：返回 stripped（保持原行为，让调用方报路径不存在）
        None — 非 feat/req-<id> 分支，或 git 命令失败

    F-005/F-009 等 9 个命令共用此函数。
    REQ-2026-014：legacy fallback 让 feat/req-2026-014 → REQ-2026-014（与 jsonl
    workflow_started.run_id 一致），实现 spec §11 Phase 3 "infer_run_id_from_branch
    兼容新旧 key" 的能力（验收 #7）。
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=5,
        )
        branch = result.stdout.strip()
        if not branch.startswith("feat/req-"):
            return None
        stripped = branch[len("feat/req-"):]

        for base in ("requirements", "runs"):
            if (repo_root / base / stripped).is_dir():
                return stripped

        upper = stripped.upper()
        if not any(upper.startswith(p) for p in ("REQ-", "RUN-", "REL-")):
            for prefix in ("REQ-", "RUN-", "REL-"):
                candidate = f"{prefix}{upper}"
                for base in ("requirements", "runs"):
                    if (repo_root / base / candidate).is_dir():
                        return candidate

        return stripped
    except Exception as exc:
        logging.debug("git rev-parse failed: %s", exc)
    return None


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

    def findings(self) -> list[tuple[str, str, str, str]]:
        """返回当前所有 finding 的浅拷贝。供需要遍历 sub-report 的下游使用。"""
        return list(self._findings)

    def exit_code(self, strict: bool) -> int:
        if self.errors:
            return 1
        if strict and self.warnings:
            return 1
        return 0
