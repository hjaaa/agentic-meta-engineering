"""context_usage_evidence — F-006 EvidenceScanner 组件。

负责：
  - ReferenceEvidence 数据载体 (frozen dataclass)
  - _RAW_PATH_RE / _SOURCE_MARKER_RE 正则常量
  - _strip_line_suffix / _resolve_url_to_context_rel 辅助函数
  - _scan_text_lines / _scan_json_values 扫描内核
  - EvidenceScanner: 扫 requirements/** 识别对 context/** 的显式引用
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from markdown_links import mask_code_blocks, resolve_link  # noqa: E402


@dataclass(frozen=True)
class ReferenceEvidence:
    """requirements 文档中对 context 文件的一条显式引用。

    五字段对应 detailed-design.md §数据结构；frozen 便于放进 set/dict。
    """

    target: str       # 被引用的 context 文件 rel_path（POSIX）
    source: str       # 引用所在的 requirements 文件 rel_path（POSIX）
    line: int         # 1-based
    kind: Literal["markdown_link", "raw_path", "source_marker", "json_value"]
    context_line: str  # 该行原始文本（strip 行尾换行符）


# 同行去重优先级（数字越小越优先，优先级高的 kind 保留）
_KIND_PRIORITY: dict[str, int] = {
    "markdown_link": 0,
    "source_marker": 1,
    "json_value": 2,
    "raw_path": 3,
}

# raw_path 正则：匹配行内独立出现的 context/ 相对路径（.md/.txt/.yaml/.yml/.json 结尾），
# 排除被 ( 或 / 紧接（避免重复捕获 markdown_link 括号内路径）。
_RAW_PATH_RE = re.compile(
    r"(?<![\(/])\bcontext/[^\s,，()\[\]`\"']+\.(?:md|txt|yaml|yml|json)\b"
)

# source_marker 正则：`来源：context/...` 或 `来源:context/...`，允许 :line 后缀
# 终止符允许：空白、文件末尾、中/西文标点（含全角括号 ）。）
_SOURCE_MARKER_RE = re.compile(
    r"来源[:：]\s*(context/[^\s,，:：\[\]`\"'（）]+?)(?::\d+)?(?=[\s,，（）\]\)。]|$)"
)


def _strip_line_suffix(path_str: str) -> str:
    """剥掉 context/path.md:42 里的 :行号 后缀，返回干净路径。"""
    return re.sub(r":\d+$", "", path_str)


def _resolve_url_to_context_rel(
    url: str, source_path: Path, repo_root: Path
) -> str | None:
    """把 Markdown link URL 解析为 repo-root 相对路径字符串，用于 context_files 查找。

    策略（优先级）：
    1. 若 URL 以 `context/` 开头（requirements 里最常见写法，表示 repo-root 相对），
       直接拼 repo_root / url 并规范化。
    2. 否则用 resolve_link 按 source_path 相对路径解析。

    Returns:
        POSIX rel_path（相对 repo_root）；无法解析或越界返回 None。
    """
    from urllib.parse import unquote as _unquote

    _repo_root = repo_root.resolve()
    path_part, _, _ = url.partition("#")
    path_part = _unquote(path_part).strip()
    if not path_part:
        return None

    if path_part.startswith("context/") or path_part.startswith("/context/"):
        clean = path_part.lstrip("/")
        candidate = (repo_root / clean).resolve()
        try:
            return candidate.relative_to(_repo_root).as_posix()
        except ValueError:
            return None

    resolved = resolve_link(url, source_path, repo_root)
    if resolved is None:
        return None
    try:
        return resolved.relative_to(_repo_root).as_posix()
    except ValueError:
        return None


def _scan_text_lines(
    lines: list[str],
    masked_lines: list[str],
    source_rel: str,
    source_path: Path,
    repo_root: Path,
    context_files: set[str],
) -> list[ReferenceEvidence]:
    """对已 mask 的文本行扫描 markdown_link / raw_path / source_marker 三种引用。

    Args:
        lines:        原始行列表（未 mask）
        masked_lines: mask_code_blocks 处理后的行列表
        source_rel:   扫描文件的 rel_path（POSIX，相对 repo_root）
        source_path:  扫描文件的绝对路径（供 resolve_link 使用）
        repo_root:    仓库根（resolve_link 越界判定 + rel_path 计算）
        context_files: 候选 context 路径集合

    Returns:
        list[ReferenceEvidence]，同行去重后。
    """
    best: dict[tuple[int, str], tuple[int, ReferenceEvidence]] = {}

    def _add(ev: ReferenceEvidence) -> None:
        key = (ev.line, ev.target)
        priority = _KIND_PRIORITY[ev.kind]
        if key not in best or priority < best[key][0]:
            best[key] = (priority, ev)

    for i, (orig_line, masked_line) in enumerate(zip(lines, masked_lines), start=1):
        # ---- markdown_link ----
        for m in re.finditer(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)", masked_line):
            url = m.group(2).strip()
            target_rel = _resolve_url_to_context_rel(url, source_path, repo_root)
            if target_rel is None:
                continue
            if target_rel in context_files:
                _add(ReferenceEvidence(
                    target=target_rel,
                    source=source_rel,
                    line=i,
                    kind="markdown_link",
                    context_line=orig_line.rstrip("\n"),
                ))

        # ---- source_marker ----
        for m in re.finditer(_SOURCE_MARKER_RE, masked_line):
            raw = m.group(1)
            target_rel = _strip_line_suffix(raw)
            if target_rel in context_files:
                _add(ReferenceEvidence(
                    target=target_rel,
                    source=source_rel,
                    line=i,
                    kind="source_marker",
                    context_line=orig_line.rstrip("\n"),
                ))

        # ---- raw_path ----
        for m in re.finditer(_RAW_PATH_RE, masked_line):
            target_rel = m.group(0)
            if target_rel in context_files:
                _add(ReferenceEvidence(
                    target=target_rel,
                    source=source_rel,
                    line=i,
                    kind="raw_path",
                    context_line=orig_line.rstrip("\n"),
                ))

    return [ev for _, ev in sorted(best.values(), key=lambda x: (x[1].line, x[1].target))]


def _scan_json_values(
    obj: object,
    context_files: set[str],
    line_hint: int = 1,
) -> list[tuple[str, int]]:
    """递归遍历 JSON 对象，取所有 str 值中匹配的 context 路径。

    Returns:
        list[(target_rel, line_hint)]  ——  JSON 不保留行号，统一用 line_hint=1。
    """
    results: list[tuple[str, int]] = []
    if isinstance(obj, str):
        for m in re.finditer(_RAW_PATH_RE, obj):
            target_rel = m.group(0)
            if target_rel in context_files:
                results.append((target_rel, line_hint))
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(_scan_json_values(v, context_files, line_hint))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_scan_json_values(item, context_files, line_hint))
    return results


class EvidenceScanner:
    """扫 requirements/** 下文档，识别对 context/** 文件的显式引用。

    职责（detailed-design §组件 3）：
    - rglob 扫 requirements_dir 下 .md/.txt/.json/.yaml/.yml
    - 按后缀分发到文本扫描或 JSON 扫描
    - 识别 4 种引用形式：markdown_link / raw_path / source_marker / json_value
    - 输出 list[ReferenceEvidence]；fail-open，不抛业务异常
    """

    def __init__(
        self,
        requirements_dir: Path,
        context_files: set[str],
        repo_root: Path,
    ) -> None:
        """
        Args:
            requirements_dir: 扫描根（默认 REPO_ROOT/requirements）
            context_files:    ContextInventory 输出的 rel_path 集合，用于过滤噪音
            repo_root:        仓库根（绝对路径），用于 resolve_link 与 rel_path 计算
        """
        self._requirements_dir = requirements_dir
        self._context_files = set(context_files)
        self._repo_root = repo_root.resolve()
        self._warnings: list[str] = []

    def scan(self) -> list[ReferenceEvidence]:
        """单次扫描，返回 list[ReferenceEvidence]。fail-open，不抛业务异常。"""
        results: list[ReferenceEvidence] = []
        suffixes = {".md", ".txt", ".json", ".yaml", ".yml"}

        for file_path in sorted(self._requirements_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in suffixes:
                continue

            try:
                source_rel = file_path.resolve().relative_to(self._repo_root).as_posix()
            except ValueError:
                self._warnings.append(
                    f"[EvidenceScanner] 文件越界 repo_root，跳过：{file_path}"
                )
                continue

            if file_path.suffix.lower() == ".json":
                results.extend(self._scan_json_file(file_path, source_rel))
            else:
                results.extend(self._scan_text_file(file_path, source_rel))

        return results

    def _scan_text_file(
        self, file_path: Path, source_rel: str
    ) -> list[ReferenceEvidence]:
        """读文本文件，mask code blocks（.md/.txt 有效），然后扫 3 种引用。"""
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._warnings.append(
                f"[EvidenceScanner] 文件不可读，跳过：{file_path} — {exc}"
            )
            return []

        masked = mask_code_blocks(text)
        orig_lines = text.splitlines()
        masked_lines = masked.splitlines()

        return _scan_text_lines(
            lines=orig_lines,
            masked_lines=masked_lines,
            source_rel=source_rel,
            source_path=file_path,
            repo_root=self._repo_root,
            context_files=self._context_files,
        )

    def _scan_json_file(
        self, file_path: Path, source_rel: str
    ) -> list[ReferenceEvidence]:
        """读 JSON 文件，递归取所有字符串值中的 context 路径（json_value kind）。

        解析失败 fail-open：warnings 追加，不抛，返回空列表。
        """
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._warnings.append(
                f"[EvidenceScanner] JSON 文件不可读，跳过：{file_path} — {exc}"
            )
            return []

        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            self._warnings.append(
                f"[EvidenceScanner] JSON 解析失败，跳过：{file_path} — {exc}"
            )
            return []

        lines = text.splitlines()
        seen: dict[tuple[int, str], ReferenceEvidence] = {}
        try:
            json_hits = _scan_json_values(obj, self._context_files)
        except RecursionError:
            self._warnings.append(
                f"[EvidenceScanner] JSON 嵌套过深，跳过：{source_rel}"
            )
            return []
        for target_rel, line_no in json_hits:
            actual_line = line_no
            for idx, raw_line in enumerate(lines, start=1):
                if target_rel in raw_line:
                    actual_line = idx
                    break
            key = (actual_line, target_rel)
            if key not in seen:
                context_line = lines[actual_line - 1] if actual_line <= len(lines) else ""
                seen[key] = ReferenceEvidence(
                    target=target_rel,
                    source=source_rel,
                    line=actual_line,
                    kind="json_value",
                    context_line=context_line.rstrip("\n"),
                )

        return sorted(seen.values(), key=lambda ev: (ev.line, ev.target))

    @property
    def warnings(self) -> list[str]:
        """累计的非致命告警（解析失败、越界等）。"""
        return list(self._warnings)
