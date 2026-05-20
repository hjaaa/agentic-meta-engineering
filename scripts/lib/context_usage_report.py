"""context/** 知识利用率统计——核心组件（F-004 起逐步落地）。

本模块对 detailed-design.md §接口签名 / §数据结构 的实现承诺：

  - 数据载体 frozen dataclass：KnowledgeFile（F-004）
  - 扫描组件 ContextInventory（F-004）
  - IndexGraph / EvidenceScanner / ... 后续 feature 接入

不读文件内容、只列路径与 stat——内容解析由 markdown_links 模块负责。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import sys

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from markdown_links import (  # noqa: E402
    extract_links,
    glob_match,
    resolve_link,
)


@dataclass(frozen=True)
class KnowledgeFile:
    """context/** 下一个被纳入统计的 md 文件。

    五字段与 detailed-design.md §数据结构 一一对应；frozen 保证下游聚合阶段
    放进 set / dict key 不会因引用相等性意外改写。
    """

    path: Path
    rel_path: str
    kind: Literal["team", "project"]
    size_bytes: int
    fs_mtime: datetime


def _classify_kind(rel_path: str) -> Literal["team", "project"]:
    """按 rel_path 第二段判定 team / project。

    `context/team/...` → "team"；`context/project/<X>/...` → "project"。
    其余形态（如 `context/foo.md` 直接挂根、或第一段非 `context`）一律
    归 "team"——detailed-design.md §数据结构 把 kind 收敛为二选一字面量，
    不引入 "other" 第三态，避免下游分支扩散。

    路径分段约定：调用方传入的 rel_path 已是 POSIX `/` 风格（由
    ContextInventory.scan 统一规范化）。
    """
    parts = rel_path.split("/")
    if len(parts) >= 2 and parts[0] == "context" and parts[1] == "project":
        return "project"
    return "team"


class ContextInventory:
    """枚举 context/** 下所有纳入统计的 md 文件。

    职责（detailed-design §组件 1）：
    - rglob('*.md') 扫 context_dir 下所有 md
    - 应用 index-config.yaml ignore 规则（复用 markdown_links.glob_match）
    - 剔除 INDEX.md
    - 输出 list[KnowledgeFile]（不读内容，只列路径与 stat）
    """

    def __init__(
        self,
        context_dir: Path,
        ignore_patterns: list[str],
        repo_root: Path,
    ) -> None:
        """
        Args:
            context_dir: 扫描根（默认 REPO_ROOT/context）
            ignore_patterns: 来自 index-config.yaml 的忽略 glob，可空列表
            repo_root: 用于计算相对路径

        Raises:
            FileNotFoundError: context_dir 不存在
        """
        if not context_dir.exists():
            raise FileNotFoundError(f"context_dir 不存在：{context_dir}")
        self._context_dir = context_dir
        self._ignore_patterns = list(ignore_patterns)
        self._repo_root = repo_root.resolve()

    def scan(self) -> list[KnowledgeFile]:
        """单次扫描，返回过滤后的文件列表。

        幂等：多次调用返回同一结果（在 fs 不变前提下）。
        性能预期：5000 文件 < 1s（仅 rglob + ignore 匹配，不读内容）。
        """
        results: list[KnowledgeFile] = []
        for path in sorted(self._context_dir.rglob("*.md")):
            if not path.is_file():
                continue
            if path.name == "INDEX.md":
                continue
            rel_path = path.resolve().relative_to(self._repo_root).as_posix()
            if any(glob_match(rel_path, p) for p in self._ignore_patterns):
                continue
            stat = path.stat()
            results.append(
                KnowledgeFile(
                    path=path,
                    rel_path=rel_path,
                    kind=_classify_kind(rel_path),
                    size_bytes=stat.st_size,
                    fs_mtime=datetime.fromtimestamp(
                        int(stat.st_mtime), tz=timezone.utc
                    ),
                )
            )
        return results


# ---------------------------------------------------------------------------
# F-005 · IndexGraph：扫 context/**/INDEX.md，识别断链与孤岛
# 接口/数据结构来源：detailed-design.md §组件 2 / §数据结构（interfaces_frozen）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BrokenLink:
    """INDEX.md 里列了但 fs 不存在的链接。

    四字段对应 detailed-design.md §BrokenLink；frozen 便于放进 set/dict。
    """

    index_path: str   # 出现断链的 INDEX.md 的 rel_path（POSIX）
    line: int         # 1-based 行号
    target: str       # 目标 rel_path（理论的，fs 上不存在）；POSIX
    link_text: str    # 原始 link text


@dataclass(frozen=True)
class IndexGraphResult:
    """IndexGraph.build() 的产物。

    三字段对应 detailed-design.md §IndexGraphResult。
    """

    indexed_by: dict[str, list[str]]
    broken_links: list[BrokenLink]
    orphans: list[KnowledgeFile]


class IndexGraph:
    """构建 context/**/INDEX.md 的链接图（detailed-design §组件 2）。

    职责：
      - rglob 扫 context_dir 下所有 INDEX.md（INDEX 自身从不被 ignore）
      - 用 markdown_links.extract_links + resolve_link 解析每条 link
      - 输出 indexed_by / broken_links / orphans 三视图

    幂等：纯计算，无 IO 写。
    """

    def __init__(self, context_dir: Path, repo_root: Path) -> None:
        """
        Args:
            context_dir: INDEX 扫描根（默认 REPO_ROOT/context）
            repo_root:   仓库根，用于 rel_path 计算 + resolve_link 越界判定
        """
        self._context_dir = context_dir
        self._repo_root = repo_root.resolve()

    def _process_index_file(
        self, index_path: Path, index_rel: str
    ) -> tuple[list[tuple[str, str]], list[BrokenLink]]:
        """处理单个 INDEX.md：读文件 + 遍历每条 link，返回该 INDEX 的局部结果。

        Args:
            index_path: INDEX.md 的绝对路径
            index_rel:  INDEX.md 相对仓库根的 POSIX rel_path

        Returns:
            (indexed_items, broken_links)
              - indexed_items: list of (target_rel, index_rel)，调用方据此聚合 indexed_by
              - broken_links:  本 INDEX 内的断链列表

        约定（与 build() 一致）：
          - 外链 / intra-anchor / 越界：跳过
          - INDEX → INDEX：跳过（INDEX 是索引方，不计入 indexed_by）
          - INDEX 不可读：返回 ([], []) (fail-open)
        """
        try:
            md_text = index_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # INDEX 不可读：跳过，不计断链（fail-open；与 EvidenceScanner 一致基调）
            return [], []

        indexed_items: list[tuple[str, str]] = []
        broken_links: list[BrokenLink] = []

        for link in extract_links(md_text):
            resolved = resolve_link(link.url, index_path, self._repo_root)
            if resolved is None:
                # 外链 / intra-anchor / 越界 → 跳过
                continue
            target_rel = resolved.relative_to(self._repo_root).as_posix()
            if not resolved.exists():
                broken_links.append(
                    BrokenLink(
                        index_path=index_rel,
                        line=link.line,
                        target=target_rel,
                        link_text=link.text,
                    )
                )
                continue
            # INDEX 自身不作为被索引对象（避免 INDEX → INDEX 循环计入）
            if resolved.name == "INDEX.md":
                continue
            indexed_items.append((target_rel, index_rel))

        return indexed_items, broken_links

    def build(self, files: list[KnowledgeFile]) -> IndexGraphResult:
        """单次构建，返回 IndexGraphResult。

        Args:
            files: ContextInventory.scan() 输出，用于 cross-check 孤岛

        约定：
          - INDEX.md 自身不计入 indexed_by 的 key（INDEX 是索引方，不是被索引方）
          - indexed_by[target] 列表按字典序排序
          - broken_links 按 (index_path, line) 升序
          - orphans 按 rel_path 升序
        """
        indexed_by: dict[str, list[str]] = {}
        broken_links: list[BrokenLink] = []

        for index_path in sorted(self._context_dir.rglob("INDEX.md")):
            if not index_path.is_file():
                continue
            index_rel = index_path.resolve().relative_to(self._repo_root).as_posix()
            items, broken = self._process_index_file(index_path, index_rel)
            for target_rel, idx_rel in items:
                indexed_by.setdefault(target_rel, []).append(idx_rel)
            broken_links.extend(broken)

        # indexed_by 每个 list 字典序排序
        for k in indexed_by:
            indexed_by[k] = sorted(indexed_by[k])

        # orphans：files 中 rel_path 未出现在 indexed_by key 的子集
        orphans = sorted(
            (kf for kf in files if kf.rel_path not in indexed_by),
            key=lambda kf: kf.rel_path,
        )

        broken_links.sort(key=lambda b: (b.index_path, b.line))

        return IndexGraphResult(
            indexed_by=indexed_by,
            broken_links=broken_links,
            orphans=orphans,
        )


# ---------------------------------------------------------------------------
# F-006 · EvidenceScanner：扫 requirements/** 文档，识别对 context/** 的显式引用
# 接口/数据结构来源：detailed-design.md §组件 3 / §数据结构（interfaces_frozen）
# ---------------------------------------------------------------------------

from markdown_links import mask_code_blocks  # noqa: E402 (already on sys.path)


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

# raw_path 正则：匹配行内独立出现的 context/ 相对路径（.md 结尾），
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
    # 只剥最后一个 :数字 后缀
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

    # 截断 anchor
    path_part, _, _ = url.partition("#")
    path_part = _unquote(path_part).strip()
    if not path_part:
        return None

    # 策略 1：URL 以 context/ 开头，视为 repo-root 相对路径
    if path_part.startswith("context/") or path_part.startswith("/context/"):
        clean = path_part.lstrip("/")
        candidate = (repo_root / clean).resolve()
        try:
            return candidate.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            return None

    # 策略 2：普通相对路径，用 resolve_link 按 source_path 解析
    resolved = resolve_link(url, source_path, repo_root)
    if resolved is None:
        return None
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
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
    # key = (line_no, target) → (kind, ReferenceEvidence)，取优先级最高者
    best: dict[tuple[int, str], tuple[int, ReferenceEvidence]] = {}

    def _add(ev: ReferenceEvidence) -> None:
        """按优先级更新 best 字典（同行同 target 取更具体 kind）。"""
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
    source_rel: str,
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
            results.extend(_scan_json_values(v, source_rel, context_files, line_hint))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_scan_json_values(item, source_rel, context_files, line_hint))
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
        context_files: set[str],  # 候选目标路径集合（相对 repo_root，POSIX）
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
                results.extend(
                    self._scan_json_file(file_path, source_rel)
                )
            else:
                # .md / .txt / .yaml / .yml → 文本扫描
                results.extend(
                    self._scan_text_file(file_path, source_rel)
                )

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

        # mask code blocks（对 yaml/txt 也做，无副作用；mask 后伪引用被过滤）
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
            json_hits = _scan_json_values(obj, source_rel, self._context_files)
        except RecursionError:
            self._warnings.append(
                f"[EvidenceScanner] JSON 嵌套过深，跳过：{source_rel}"
            )
            return []
        for target_rel, line_no in json_hits:
            # JSON 扫描行号用近似值（从 1 开始）；若同 target 多次出现取首次
            # 尝试在原文中定位第一次出现的行
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


# ---------------------------------------------------------------------------
# F-007 · AppliedSignalClassifier：复合窗口 + 显式升级，把 ReferenceEvidence
# 升级判定为 AppliedEvidence
# 接口/数据结构来源：detailed-design.md §组件 4 / §数据结构（interfaces_frozen）
# ---------------------------------------------------------------------------

import re as _re_applied  # noqa: E402（已在顶层 import re，此为别名避免遮蔽）


@dataclass(frozen=True)
class AppliedEvidence:
    """一条被判定为 applied 的引用证据。

    字段对应 detailed-design.md §AppliedEvidence（interfaces_frozen）。
    """

    reference: ReferenceEvidence            # 升级前的原始引用（F-006 dataclass）
    rule: Literal["window_hit", "explicit_upgrade"]  # 命中规则
    matched_keyword: str                    # 命中的关键字 / 短语
    section_heading: str | None             # 仅 window_hit 提供；文件无 ## heading 则 None


# 用于识别 ## 二级标题（H2，不多不少两个 # ）
_H2_RE = _re_applied.compile(r"^##\s+(.+?)\s*$")
# 用于识别任意标题（H1-H6），用于终止当前 H2 小节
_ANY_H_RE = _re_applied.compile(r"^(#{1,6})\s+")


def _build_section_map(lines: list[str]) -> dict[int, str | None]:
    """把 masked_text 的每一行映射到所属 ## 二级小节标题。

    规则（保守原则）：
    - 第一个 H2 之前的行（包括 H1 下方）→ None（不参与窗口同小节判定）
    - 位于某 H2 之内、下一个 H1/H2 之前的行 → 该 H2 标题文本
    - H1 重置当前小节为 None（H1 结束前一个 H2 的作用域）

    Args:
        lines: masked_text.splitlines() 的结果（行 index 0-based，行号 1-based = index+1）

    Returns:
        dict，key 为 1-based 行号，value 为所属 H2 标题文本（或 None）。
    """
    result: dict[int, str | None] = {}
    current_section: str | None = None

    for idx, line in enumerate(lines):
        lineno = idx + 1
        # 检测 H1（# 单个井号）：重置 section
        h_match = _ANY_H_RE.match(line)
        if h_match:
            level = len(h_match.group(1))
            if level == 1:
                current_section = None
            elif level == 2:
                h2_match = _H2_RE.match(line)
                current_section = h2_match.group(1) if h2_match else None
            # H3+ 不改变当前 H2 小节
        result[lineno] = current_section

    return result


class AppliedSignalClassifier:
    """把 ReferenceEvidence 升级判定为 AppliedEvidence。

    判定规则（来源：requirement.md + detailed-design.md §组件 4）：

    路径 A（复合窗口命中）：
      - 引用所在行在某 ## 二级小节内（section_heading 不为 None）
      - AND 前 5 行 + 后 10 行（16 行窗口，masked 文本）内出现关键字
      - 关键字不在 fenced/inline code 内（mask_code_blocks 已处理）
      - 关键字与引用行必须在同一 ## 小节

    路径 B（显式升级声明）：
      - 引用所在行的源文件全文（masked）出现任一 UPGRADE_PHRASES 短语
      - 子串匹配

    两路任一命中即为 applied；同一 reference 双路均命中时各产一条（不去重）。
    保守原则：宁可漏判，不可误判——窗口边界外不命中，不同 ## 小节不命中。
    """

    WINDOW_BEFORE: int = 5
    WINDOW_AFTER: int = 10
    APPLIED_KEYWORDS: frozenset[str] = frozenset({"Decision", "决策", "应对", "风险", "验证"})
    UPGRADE_PHRASES: frozenset[str] = frozenset({
        "升级为 checklist", "升级为 SOP", "升级为测试", "升级为 gate",
        "升级为 hook", "来自该经验", "按该经验落 test", "按该经验落 gate",
    })

    def classify(
        self, evidences: list[ReferenceEvidence], file_cache: dict[Path, str]
    ) -> list[AppliedEvidence]:
        """对每条 ReferenceEvidence 判定是否构成 applied。

        Args:
            evidences:   来自 EvidenceScanner 的引用证据列表
            file_cache:  source 文件内容缓存，key 为绝对路径 Path，value 为文件全文

        Returns:
            list[AppliedEvidence]，只包含命中条目。同一 reference 双路命中时各产一条。

        不抛业务异常（fail-open 风格）。
        """
        results: list[AppliedEvidence] = []

        # 按 source 文件分组，每个文件只处理一次 mask 和 section map
        from collections import defaultdict
        by_source: dict[str, list[ReferenceEvidence]] = defaultdict(list)
        for ev in evidences:
            by_source[ev.source].append(ev)

        for source_rel, evs in by_source.items():
            # 尝试从 file_cache 中找到对应内容（key 为绝对路径）
            raw_text: str | None = None
            for cache_key, cache_val in file_cache.items():
                try:
                    if str(cache_key).endswith(source_rel) or cache_key.name == Path(source_rel).name:
                        # 精确后缀匹配
                        if str(cache_key).replace("\\", "/").endswith(source_rel):
                            raw_text = cache_val
                            break
                except Exception:
                    continue

            if raw_text is None:
                # file_cache 中无此文件，跳过（保守：不命中）
                continue

            try:
                masked_text = mask_code_blocks(raw_text)
                masked_lines = masked_text.splitlines()
                section_map = _build_section_map(masked_lines)
                total_lines = len(masked_lines)
            except Exception:
                continue

            # 预计算：全文是否含显式升级短语（路径 B，全文级别）
            upgrade_hit: str | None = None
            for phrase in self.UPGRADE_PHRASES:
                if phrase in masked_text:
                    upgrade_hit = phrase
                    break

            for ev in evs:
                ref_lineno = ev.line  # 1-based

                # --- 路径 B：显式升级声明（全文匹配） ---
                if upgrade_hit is not None:
                    results.append(AppliedEvidence(
                        reference=ev,
                        rule="explicit_upgrade",
                        matched_keyword=upgrade_hit,
                        section_heading=None,
                    ))

                # --- 路径 A：复合窗口命中 ---
                ref_section = section_map.get(ref_lineno)
                if ref_section is None:
                    # 引用行不在任何 ## 小节内，路径 A 不命中（保守原则）
                    continue

                # 计算窗口范围（1-based，含边界）
                win_start = max(1, ref_lineno - self.WINDOW_BEFORE)
                win_end = min(total_lines, ref_lineno + self.WINDOW_AFTER)

                window_keyword: str | None = None
                for lineno in range(win_start, win_end + 1):
                    # 关键字命中行必须与引用行在同一 ## 小节
                    if section_map.get(lineno) != ref_section:
                        continue
                    line_text = masked_lines[lineno - 1]  # 0-based index
                    for kw in self.APPLIED_KEYWORDS:
                        if kw in line_text:
                            window_keyword = kw
                            break
                    if window_keyword is not None:
                        break

                if window_keyword is not None:
                    results.append(AppliedEvidence(
                        reference=ev,
                        rule="window_hit",
                        matched_keyword=window_keyword,
                        section_heading=ref_section,
                    ))

        return results
