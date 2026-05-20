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
import subprocess
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


@dataclass(frozen=True)
class GitTimestamp:
    """git log 查询结果或 fs_mtime 回退的时间戳载体。

    三字段对应 detailed-design.md §数据结构（F-008）；frozen 便于放进 set/dict。
    """

    first_commit_at: datetime | None   # 文件首次提交（UTC，秒精度）；空仓/shallow → None
    last_commit_at: datetime | None    # 最近一次 commit（UTC，秒精度）
    source: Literal["git_log", "fs_mtime"]  # 数据来源


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


def fetch_git_timestamps(
    files: list[KnowledgeFile],
    since_days: int,
    *,
    repo_root: Path | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, GitTimestamp], list[str]]:
    """批量获取文件的 git 提交时间戳（F-008）。

    通过 git log 子进程查询文件的首次与最近提交时间；失败时回退 fs_mtime。

    Args:
        files:       KnowledgeFile 列表（含 rel_path 和 fs_mtime）
        since_days:  查询范围（days），传给 git log --since
        repo_root:   仓库根（默认 Path.cwd()）；git log cwd 参数
        now:         注入当前时间（用于测试）；在回退场景不使用，仅预留

    Returns:
        tuple:
            - dict，key 为 KnowledgeFile.rel_path（POSIX），value 为 GitTimestamp
            - warnings 列表（仅包含全局异常提示，非单文件级）

    异常处理（detailed-design.md L677-L693）：
        - subprocess.CalledProcessError / FileNotFoundError / OSError → 全局回退
        - 每个文件取 fs_mtime 并设 source="fs_mtime", first_commit_at=None
        - warnings 追加一条全局提示（非每文件）
    """
    if repo_root is None:
        repo_root = Path.cwd()
    repo_root = repo_root.resolve()

    if not files:
        return {}, []

    warnings: list[str] = []
    result: dict[str, GitTimestamp] = {}

    try:
        # 构造 git log 命令：fetch 所有文件的首次和最近提交时间
        # --since=<N>d：只查最近 N 天
        # --name-only：每个 commit 后跟修改的文件列表
        # --pretty=%H|%cI：commit hash | ISO8601 时间戳（含时区）
        # --：明确分隔，避免歧义
        rel_paths = [f.rel_path for f in files]
        cmd = [
            "git", "log",
            f"--since={since_days}d",
            "--name-only",
            "--pretty=%H|%cI",
            "--",
        ] + rel_paths

        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            text=True,
            check=True,
            capture_output=True,
            timeout=30,
        )

        # 解析 git log 输出
        # git log 输出格式（newest-first）：
        #   hash|ISO8601
        #   (blank line)
        #   file1
        #   file2
        #   hash|ISO8601
        #   (blank line)
        #   file3
        # ...
        # git log 默认最新优先，所以第一个见到的 commit 是最新的（last_commit_at）
        output = proc.stdout
        timestamps: dict[str, tuple[datetime, datetime]] = {}  # path → (first, last)

        if output.strip():
            lines = output.split("\n")
            current_commit_time: datetime | None = None

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    # 空行：跳过
                    continue

                if "|" in stripped:
                    # 新 commit header（格式：hash|ISO8601）
                    try:
                        ts_str = stripped.split("|", 1)[1]
                        current_commit_time = (
                            datetime.fromisoformat(ts_str)
                            .astimezone(timezone.utc)
                            .replace(microsecond=0)
                        )
                    except (ValueError, IndexError):
                        current_commit_time = None
                elif current_commit_time is not None:
                    # 文件路径：关联到当前 commit_time
                    path = stripped
                    if path not in timestamps:
                        # 首次见到该文件
                        # git log newest-first，所以这次见到是 last_commit_at
                        # 下次再见到时才是 first_commit_at
                        timestamps[path] = (current_commit_time, current_commit_time)
                    else:
                        # 再次见到该文件
                        # 保持前面记录的 last_commit_at，更新 first_commit_at
                        _, last = timestamps[path]
                        timestamps[path] = (current_commit_time, last)

        # 构造返回结果
        for f in files:
            if f.rel_path in timestamps:
                first, last = timestamps[f.rel_path]
                result[f.rel_path] = GitTimestamp(
                    first_commit_at=first,
                    last_commit_at=last,
                    source="git_log",
                )
            else:
                # 文件不在 git log 结果中（可能超出 since_days 范围）
                # 视为未找到 git 记录，用 fs_mtime 回退
                result[f.rel_path] = GitTimestamp(
                    first_commit_at=None,
                    last_commit_at=f.fs_mtime,
                    source="fs_mtime",
                )

    except subprocess.TimeoutExpired:
        # git log 超时（大仓库 / 网络挂载磁盘 / git 卡死）：回退 fs_mtime
        warnings.append("git log 超时（30s），回退 fs_mtime")
        for f in files:
            result[f.rel_path] = GitTimestamp(
                first_commit_at=None,
                last_commit_at=f.fs_mtime,
                source="fs_mtime",
            )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        # git log 失败或 git 缺失：全部回退到 fs_mtime
        # 只记异常类型名，避免泄漏完整 cmd / 路径列表
        warnings.append(f"git log 失败（{type(exc).__name__}），回退 fs_mtime")
        for f in files:
            result[f.rel_path] = GitTimestamp(
                first_commit_at=None,
                last_commit_at=f.fs_mtime,
                source="fs_mtime",
            )

    return result, warnings


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

import re as _re_applied  # noqa: E402


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


def _section_line_range(
    section_map: dict[int, str | None], target_section: str, total_lines: int
) -> tuple[int, int]:
    """返回 target_section 对应的行范围 [start, end]（1-based inclusive）。

    线性扫描 section_map，找出连续属于 target_section 的最早 start 和最晚 end。
    若未找到则返回 (1, 0)（空范围）。
    """
    start: int | None = None
    end: int | None = None
    for ln in range(1, total_lines + 1):
        if section_map.get(ln) == target_section:
            if start is None:
                start = ln
            end = ln
    if start is None:
        return (1, 0)
    return (start, end)  # type: ignore[return-value]


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

        # F-007 fix G-4：O(K) 预建索引，避免 endswith(source_rel) 子串误匹配
        # 例：source_rel="team/x.md" 不再同时命中 "/abs/team/x.md" 和 "/abs/other/x.md"
        cache_by_rel: dict[str, str] = {}
        cache_by_name: dict[str, str] = {}
        for cache_key, cache_text in file_cache.items():
            key_str = str(cache_key).replace("\\", "/")
            cache_by_rel[key_str] = cache_text
            cache_by_name[cache_key.name] = cache_text

        for source_rel, evs in by_source.items():
            # 精确匹配：归一化 source_rel
            normalized = source_rel.replace("\\", "/")
            raw_text: str | None = cache_by_rel.get(normalized)
            if raw_text is None:
                # fallback 1：cache key 以 '/' + normalized 结尾（带分隔符，避免子串误匹配）
                for ckey, ctext in cache_by_rel.items():
                    if ckey == normalized or ckey.endswith("/" + normalized):
                        raw_text = ctext
                        break
            if raw_text is None:
                # fallback 2：basename 匹配（最弱，保留以兼容 F-006 EvidenceScanner 行为）
                raw_text = cache_by_name.get(Path(normalized).name)
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

            for ev in evs:
                ref_lineno = ev.line  # 1-based

                # --- 路径 B：显式升级声明（## 二级小节级匹配） ---
                # FU-3：与路径 A 对称，遵守保守原则（spec L48）
                # reference 所在 ## 小节内出现任一 UPGRADE_PHRASES → 命中
                # reference 在第一个 H2 之前（section=None）→ 路径 B 也跳过
                ref_section_b = section_map.get(ref_lineno)
                if ref_section_b is not None:
                    sec_start, sec_end = _section_line_range(
                        section_map, ref_section_b, total_lines
                    )
                    section_text = "\n".join(masked_lines[sec_start - 1 : sec_end])
                    upgrade_hit: str | None = None
                    for phrase in self.UPGRADE_PHRASES:
                        if phrase in section_text:
                            upgrade_hit = phrase
                            break
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


# ---------------------------------------------------------------------------
# F-009 · UsageAggregator：聚合四路证据 + 评分 + 状态分类
# 接口/数据结构来源：detailed-design.md §组件 5 / §KnowledgeStatus /
#   §KnowledgeUsageSummary / §评分规则 / §状态机表（interfaces_frozen）
# ---------------------------------------------------------------------------

from enum import Enum  # noqa: E402


class KnowledgeStatus(str, Enum):
    """知识文件的利用状态分类。详见 detailed-design.md §KnowledgeStatus。"""

    ORPHAN = "orphan"
    NEEDS_REVIEW = "needs_review"
    VISIBLE_UNUSED = "visible_unused"
    HIGH_VALUE = "high_value"
    STALE_CANDIDATE = "stale_candidate"
    ACTIVE = "active"


@dataclass(frozen=True)
class KnowledgeUsageSummary:
    """单个知识文件的使用汇总。详见 detailed-design.md §KnowledgeUsageSummary（14 字段）。"""

    path: str
    kind: Literal["team", "project"]
    indexed: bool
    index_paths: list[str]
    reference_count: int
    applied_signal_count: int
    first_referenced_at: datetime | None
    last_referenced_at: datetime | None
    last_modified_at: datetime | None
    last_modified_at_source: Literal["git_log", "fs_mtime"]
    status: KnowledgeStatus
    score: int
    reference_evidences: list[ReferenceEvidence]
    applied_evidences: list[AppliedEvidence]


class UsageAggregator:
    """聚合所有证据 + 评分 + 状态分类。

    职责：
    - 把 ContextInventory / IndexGraph / EvidenceScanner / AppliedSignalClassifier
      四路结果与 git log 时间戳合并
    - 计算 usage_score（见 §评分规则）
    - 按状态分类规则归类（见 §状态机表）
    """

    # 评分上限（来源：requirement.md）
    INDEXED_WEIGHT: int = 2
    REFERENCE_WEIGHT: int = 3
    REFERENCE_CAP: int = 30
    APPLIED_WEIGHT: int = 8
    APPLIED_CAP: int = 40
    RECENCY_30D_SCORE: int = 10
    RECENCY_90D_SCORE: int = 5

    # 时间窗口（来源：requirement.md）
    STALE_THRESHOLD_DAYS: int = 90
    HIGH_VALUE_REFERENCE_MIN: int = 3  # [待用户确认]

    def __init__(
        self,
        inventory: list[KnowledgeFile],
        index_result: IndexGraphResult,
        references: list[ReferenceEvidence],
        applied: list[AppliedEvidence],
        git_timestamps: dict[str, GitTimestamp],  # path → GitTimestamp
        now: datetime,  # 注入便于测试
    ) -> None:
        self._inventory = inventory
        self._index_result = index_result
        self._references = references
        self._applied = applied
        self._git_timestamps = git_timestamps
        self._now = now

    def aggregate(self) -> list[KnowledgeUsageSummary]:
        """单次聚合。

        Returns:
            list[KnowledgeUsageSummary]，长度 == len(inventory)，按 score 降序 + rel_path 升序。

        幂等：纯计算。
        """
        # 预构建索引，避免 O(N²) 遍历
        # target → list[ReferenceEvidence]
        ref_by_target: dict[str, list[ReferenceEvidence]] = {}
        for ev in self._references:
            ref_by_target.setdefault(ev.target, []).append(ev)

        # target → list[AppliedEvidence]
        applied_by_target: dict[str, list[AppliedEvidence]] = {}
        for ev in self._applied:
            applied_by_target.setdefault(ev.reference.target, []).append(ev)

        results: list[KnowledgeUsageSummary] = []
        for file in self._inventory:
            rel = file.rel_path

            # IndexGraph
            indexed_paths = self._index_result.indexed_by.get(rel, [])
            indexed = len(indexed_paths) > 0

            # EvidenceScanner
            file_refs = ref_by_target.get(rel, [])
            reference_count = len(file_refs)

            # AppliedSignalClassifier
            file_applied = applied_by_target.get(rel, [])
            applied_signal_count = len(file_applied)

            # 时间戳：last_referenced_at / first_referenced_at
            # = 引用本文件的所有 requirements source 文件的 last_commit_at max / first_commit_at min
            # 仅采纳 source=="git_log" 的时间戳：fs_mtime 不参与 recency / first_referenced 计算
            # （detailed-design.md L691-692：异常路径 GitTimestamp(source="fs_mtime") 时 recency_score=0）
            ref_sources = {ev.source for ev in file_refs}
            last_referenced_at: datetime | None = None
            first_referenced_at: datetime | None = None
            for src in ref_sources:
                ts = self._git_timestamps.get(src)
                if ts is None or ts.source != "git_log":
                    continue
                if ts.last_commit_at is not None:
                    if last_referenced_at is None or ts.last_commit_at > last_referenced_at:
                        last_referenced_at = ts.last_commit_at
                if ts.first_commit_at is not None:
                    if first_referenced_at is None or ts.first_commit_at < first_referenced_at:
                        first_referenced_at = ts.first_commit_at

            # last_modified_at：优先 git_timestamps[rel].last_commit_at，回退 fs_mtime
            file_ts = self._git_timestamps.get(rel)
            if file_ts is not None:
                last_modified_at = file_ts.last_commit_at
                last_modified_at_source: Literal["git_log", "fs_mtime"] = file_ts.source
            else:
                last_modified_at = file.fs_mtime
                last_modified_at_source = "fs_mtime"

            # 评分与状态分类
            partial: dict = {
                "indexed": indexed,
                "reference_count": reference_count,
                "applied_signal_count": applied_signal_count,
                "last_referenced_at": last_referenced_at,
            }
            score = self._compute_score(partial, self._now)
            status = self._classify_status(partial, self._now)

            # 证据排序：reference_evidences 按 (source, line) 升序
            sorted_refs = sorted(file_refs, key=lambda e: (e.source, e.line))
            # applied_evidences 按 (reference.source, reference.line) 升序
            sorted_applied = sorted(file_applied, key=lambda e: (e.reference.source, e.reference.line))

            results.append(KnowledgeUsageSummary(
                path=rel,
                kind=file.kind,
                indexed=indexed,
                index_paths=indexed_paths,
                reference_count=reference_count,
                applied_signal_count=applied_signal_count,
                first_referenced_at=first_referenced_at,
                last_referenced_at=last_referenced_at,
                last_modified_at=last_modified_at,
                last_modified_at_source=last_modified_at_source,
                status=status,
                score=score,
                reference_evidences=sorted_refs,
                applied_evidences=sorted_applied,
            ))

        # 按 score 降序 + rel_path 升序
        results.sort(key=lambda s: (-s.score, s.path))
        return results

    def _compute_score(self, s: dict, now: datetime) -> int:
        """评分计算，规则见 detailed-design.md §评分规则。

        s 字段：indexed / reference_count / applied_signal_count / last_referenced_at
        """
        indexed_score = self.INDEXED_WEIGHT if s["indexed"] else 0

        reference_score = min(
            s["reference_count"] * self.REFERENCE_WEIGHT,
            self.REFERENCE_CAP,
        )

        applied_score = min(
            s["applied_signal_count"] * self.APPLIED_WEIGHT,
            self.APPLIED_CAP,
        )

        recency_score = 0
        if s["last_referenced_at"] is not None:
            delta_days = (now - s["last_referenced_at"]).days
            if delta_days <= 30:
                recency_score = self.RECENCY_30D_SCORE
            elif delta_days <= 90:
                recency_score = self.RECENCY_90D_SCORE

        return indexed_score + reference_score + applied_score + recency_score

    def _classify_status(self, s: dict, now: datetime) -> KnowledgeStatus:
        """状态分类，规则见 detailed-design.md §状态机表。

        s 字段：indexed / reference_count / applied_signal_count / last_referenced_at
        判定按顺序逐条匹配，先匹配先归类。
        """
        if not s["indexed"]:
            if s["reference_count"] == 0:
                return KnowledgeStatus.ORPHAN
            else:
                return KnowledgeStatus.NEEDS_REVIEW

        # indexed = True
        if s["reference_count"] == 0:
            return KnowledgeStatus.VISIBLE_UNUSED

        if (s["applied_signal_count"] >= 1
                and s["reference_count"] >= self.HIGH_VALUE_REFERENCE_MIN):
            return KnowledgeStatus.HIGH_VALUE

        if s["last_referenced_at"] is not None:
            delta_days = (now - s["last_referenced_at"]).days
            if delta_days > self.STALE_THRESHOLD_DAYS:
                return KnowledgeStatus.STALE_CANDIDATE

        return KnowledgeStatus.ACTIVE


# ---------------------------------------------------------------------------
# F-010 · ReportRenderer：渲染 Markdown 4 章节 + JSON
# 接口/数据结构来源：detailed-design.md §组件 6 / §数据结构 JSON 顶层结构（interfaces_frozen）
# ---------------------------------------------------------------------------

import os  # noqa: E402


def _to_iso8601(dt: datetime | None) -> str | None:
    """将 datetime 转换为 ISO-8601 UTC 字符串，None 保留为 None。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # 假定 naive datetime 是 UTC
        dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')


class ReportRenderer:
    """渲染 Markdown 4 章节 + JSON 报告。

    职责：
    - render_markdown：输出固定 4 章节（总览 → 高价值知识 → 待治理知识 → 引用明细）
    - render_json：序列化为 JSON 结构（schema 见详设）
    - write：原子化写入文件
    """

    TOOL_VERSION: str = "0.1.0"
    JSON_SCHEMA_URL: str = "https://example.invalid/context-usage-report.schema.json"

    def __init__(
        self,
        config: dict,
        broken_links_count: int,
        orphans_count: int,
        now: datetime,
    ) -> None:
        """初始化 ReportRenderer。

        Args:
            config: 含 5 个必填 key（context_dir/requirements_dir/since_days/
                    high_value_reference_min/stale_threshold_days）；缺失抛 KeyError
            broken_links_count: 断链计数
            orphans_count: 孤岛计数
            now: 生成时间（UTC）
        """
        required_keys = {
            "context_dir", "requirements_dir", "since_days",
            "high_value_reference_min", "stale_threshold_days"
        }
        missing = required_keys - set(config.keys())
        if missing:
            raise KeyError(f"config 缺失必填键：{missing}")
        self._config = config
        self._broken_links_count = broken_links_count
        self._orphans_count = orphans_count
        self._now = now

    def render_markdown(
        self, summaries: list[KnowledgeUsageSummary], warnings: list[str]
    ) -> str:
        """渲染 Markdown 报告（4 章节固定顺序）。

        幂等：纯字符串拼接，无 IO。

        Returns:
            Markdown 字符串（UTF-8）
        """
        lines: list[str] = []

        # 标题和生成时间
        lines.append("# Context 知识利用率报告")
        lines.append("")
        iso_time = _to_iso8601(self._now) or "Unknown"
        lines.append(f"生成时间：{iso_time}  · 工具版本：{self.TOOL_VERSION}")
        lines.append("")

        # ---- 总览 ----
        lines.append("## 总览")
        lines.append("")
        total = len(summaries)
        by_status = {status: 0 for status in KnowledgeStatus}
        for s in summaries:
            by_status[s.status] += 1
        lines.append("| 状态 | 计数 |")
        lines.append("|---|---|")
        lines.append(f"| 总计 | {total} |")
        for status in KnowledgeStatus:
            lines.append(f"| {status.value} | {by_status[status]} |")
        lines.append(f"| 断链 | {self._broken_links_count} |")
        lines.append(f"| 孤岛 | {self._orphans_count} |")
        lines.append("")

        # ---- 高价值知识 ----
        lines.append("## 高价值知识")
        lines.append("")
        high_value = [s for s in summaries if s.status == KnowledgeStatus.HIGH_VALUE]
        if high_value:
            lines.append("| 文件 | 分数 | 引用数 | 应用信号数 | 最后引用 |")
            lines.append("|---|---|---|---|---|")
            for s in high_value:
                last_ref = _to_iso8601(s.last_referenced_at) or "—"
                lines.append(
                    f"| {s.path} | {s.score} | {s.reference_count} | "
                    f"{s.applied_signal_count} | {last_ref} |"
                )
            lines.append("")
        else:
            lines.append("（无）")
            lines.append("")

        # ---- 待治理知识 ----
        lines.append("## 待治理知识")
        lines.append("")
        to_review = [
            s for s in summaries
            if s.status in (
                KnowledgeStatus.ORPHAN,
                KnowledgeStatus.NEEDS_REVIEW,
                KnowledgeStatus.VISIBLE_UNUSED,
                KnowledgeStatus.STALE_CANDIDATE,
            )
        ]
        if to_review:
            for status_val in [
                KnowledgeStatus.ORPHAN,
                KnowledgeStatus.NEEDS_REVIEW,
                KnowledgeStatus.VISIBLE_UNUSED,
                KnowledgeStatus.STALE_CANDIDATE,
            ]:
                status_items = [s for s in to_review if s.status == status_val]
                if not status_items:
                    continue
                lines.append(f"### {status_val.value}")
                lines.append("")
                lines.append("| 文件 | 分数 | 引用数 |")
                lines.append("|---|---|---|")
                for s in sorted(status_items, key=lambda x: -x.score):
                    lines.append(f"| {s.path} | {s.score} | {s.reference_count} |")
                lines.append("")
        else:
            lines.append("（无）")
            lines.append("")

        # ---- 引用明细 ----
        lines.append("## 引用明细")
        lines.append("")
        files_with_refs = [s for s in summaries if s.reference_evidences]
        if files_with_refs:
            for s in files_with_refs:
                lines.append(f"### {s.path}")
                lines.append("")
                lines.append("| 来源 | 行号 | 类型 | 引用行 |")
                lines.append("|---|---|---|---|")
                for ev in s.reference_evidences:
                    lines.append(
                        f"| {ev.source} | {ev.line} | {ev.kind} | "
                        f"{ev.context_line[:50]}... |"
                    )
                lines.append("")
        else:
            lines.append("（无）")
            lines.append("")

        # F-010-FU F-D：仅在 warnings 非空时追加段，避免 4 章节结构被空段污染
        if warnings:
            lines.append("## Warnings")
            lines.append("")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

        return "\n".join(lines)

    def render_json(
        self, summaries: list[KnowledgeUsageSummary], warnings: list[str]
    ) -> str:
        """渲染 JSON 报告。

        schema 见 detailed-design.md §数据结构 JSON 顶层结构。
        datetime → ISO-8601 字符串；Enum → .value；None → null。

        幂等：纯字符串转换。

        Returns:
            JSON 字符串（UTF-8）
        """
        # 构造 by_status
        by_status = {status.value: 0 for status in KnowledgeStatus}
        for s in summaries:
            by_status[s.status.value] += 1

        # 序列化 summaries
        files_list = []
        for s in summaries:
            ref_evs = []
            for ev in s.reference_evidences:
                ref_evs.append({
                    "target": ev.target,
                    "source": ev.source,
                    "line": ev.line,
                    "kind": ev.kind,
                    "context_line": ev.context_line,
                })
            app_evs = []
            for ev in s.applied_evidences:
                ref_dict = {
                    "target": ev.reference.target,
                    "source": ev.reference.source,
                    "line": ev.reference.line,
                    "kind": ev.reference.kind,
                    "context_line": ev.reference.context_line,
                }
                app_evs.append({
                    "reference": ref_dict,
                    "rule": ev.rule,
                    "matched_keyword": ev.matched_keyword,
                    "section_heading": ev.section_heading,
                })
            files_list.append({
                "path": s.path,
                "kind": s.kind,
                "indexed": s.indexed,
                "index_paths": s.index_paths,
                "reference_count": s.reference_count,
                "applied_signal_count": s.applied_signal_count,
                "first_referenced_at": _to_iso8601(s.first_referenced_at),
                "last_referenced_at": _to_iso8601(s.last_referenced_at),
                "last_modified_at": _to_iso8601(s.last_modified_at),
                "last_modified_at_source": s.last_modified_at_source,
                "status": s.status.value,
                "score": s.score,
                "reference_evidences": ref_evs,
                "applied_evidences": app_evs,
            })

        result = {
            "generated_at": _to_iso8601(self._now),
            "tool_version": self.TOOL_VERSION,
            "schema_version": 1,
            "config": {
                "context_dir": self._config["context_dir"],
                "requirements_dir": self._config["requirements_dir"],
                "since_days": self._config["since_days"],
                "high_value_reference_min": self._config["high_value_reference_min"],
                "stale_threshold_days": self._config["stale_threshold_days"],
            },
            "summary": {
                "total": len(summaries),
                "by_status": by_status,
                "broken_links": self._broken_links_count,
                "orphans": self._orphans_count,
            },
            "files": files_list,
            "warnings": warnings,
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def write(content: str, output_path: Path) -> None:
        """原子化写入文件。

        副作用：
        - 自动 mkdir -p output_path.parent
        - 先写 tmp，再 os.replace（原子覆盖）
        - UTF-8 编码

        Args:
            content: 待写入内容（字符串）
            output_path: 目标路径（Path 对象）

        Raises:
            OSError: 磁盘写失败（tmp 写阶段抛，不影响既有文件）
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, output_path)


# ---------------------------------------------------------------------------
# F-011 · CLI 入口：main() + argparse + 6 档退出码
# 接口/数据结构来源：detailed-design.md §CLI 入口 / §CLI Arguments / §异常处理表
# ---------------------------------------------------------------------------

import argparse


def _parse_since(since: str) -> int:
    r"""解析 --since 字符串为天数。

    格式：`\d+(d|w|m)$`。例：
      - "90d" → 90
      - "2w" → 14
      - "3m" → 90
      - "abc" → ValueError

    Args:
        since: 时间跨度字符串

    Returns:
        天数

    Raises:
        ValueError: 格式非法
    """
    match = re.match(r"^(\d+)([dwm])$", since)
    if not match:
        raise ValueError(f"invalid --since format: {since}, expected \\d+(d|w|m)")

    count = int(match.group(1))
    unit = match.group(2)

    if unit == "d":
        return count
    elif unit == "w":
        return count * 7
    elif unit == "m":
        return count * 30
    else:
        raise ValueError(f"unknown unit: {unit}")


def _check_dirs(context_dir: Path, requirements_dir: Path) -> int | None:
    """校验输入目录。返回 exit code 或 None 表示通过。"""
    if not context_dir.is_dir():
        print(f"ERROR: context-dir 不存在或非目录: {context_dir}", file=sys.stderr)
        return 2
    if not requirements_dir.is_dir():
        print(
            f"ERROR: requirements-dir 不存在或非目录: {requirements_dir}",
            file=sys.stderr,
        )
        return 2
    return None


def _build_file_cache(
    evidences: list[ReferenceEvidence],
    requirements_dir: Path,
    warnings: list[str],
) -> dict[Path, str]:
    """从引用证据收集 source 文件内容缓存。"""
    file_cache: dict[Path, str] = {}
    for evidence in evidences:
        src_path = requirements_dir / evidence.source
        if src_path not in file_cache and src_path.is_file():
            try:
                file_cache[src_path] = src_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                warnings.append(f"读取 {evidence.source} 失败: {e}")
    return file_cache


def _print_summary(summaries: list[KnowledgeUsageSummary], warnings: list[str]) -> None:
    """输出摘要统计到 stdout，warnings 逐条打到 stderr。

    detailed-design.md L781-782：warning / error 行走 stderr，行格式 `<LEVEL> <message>`。
    F-011 review M1 fix：原实现仅打数量到 stdout，CI grep `WARN ` 无法收集。
    """
    status_counts: dict[str, int] = {}
    for s in summaries:
        status = s.status.value if isinstance(s.status, KnowledgeStatus) else str(s.status)
        status_counts[status] = status_counts.get(status, 0) + 1
    print(f"总数: {len(summaries)}")
    for status in sorted(status_counts.keys()):
        print(f"  {status}: {status_counts[status]}")
    if warnings:
        print(f"Warnings: {len(warnings)}")
        # 每条 warning 走 stderr，对齐设计 L781-782「<LEVEL> <message>」
        for w in warnings:
            print(f"WARN {w}", file=sys.stderr)


def _render_and_write(
    renderer: ReportRenderer,
    summaries: list[KnowledgeUsageSummary],
    warnings: list[str],
    args: argparse.Namespace,
) -> int:
    """渲染并写入报告。返回 exit code：0=success，5=write error。

    F-011 review M2 fix：先 render 两份 content 再批量 write，缩小半写窗口。
    若 json 写失败时 md 已落盘，stderr 提示用户哪一份成功。
    """
    md_content: str | None = None
    json_content: str | None = None

    # 先 render（纯计算，不可能 OSError）
    try:
        if args.format in ("md", "both"):
            md_content = renderer.render_markdown(summaries, warnings)
        if args.format in ("json", "both"):
            json_content = renderer.render_json(summaries, warnings)
    except Exception as e:
        # render 阶段异常（不应发生，但兜底）
        print(f"ERROR: 渲染失败: {e}", file=sys.stderr)
        return 5

    # 批量 write（两次 write 之间仍非原子，但窗口已最小化）
    md_written = False
    try:
        if md_content is not None:
            renderer.write(md_content, args.output)
            md_written = True
        if json_content is not None:
            renderer.write(json_content, args.json_output)
        return 0
    except OSError as e:
        # 半写状态告知（M2 设计契约：保留写错误 → exit 5）
        print(f"ERROR: 写报告失败: {e}", file=sys.stderr)
        if md_written and json_content is not None:
            print(
                f"WARN 部分写入：md 已成功 ({args.output})，json 未写 ({args.json_output})",
                file=sys.stderr,
            )
        return 5


def _build_all_files_for_git(
    files: list[KnowledgeFile],
    evidences: list[ReferenceEvidence],
    requirements_dir: Path,
    warnings: list[str],
) -> list[KnowledgeFile]:
    """合并 context files + reference source files 用于 git 时间戳查询。"""
    all_files: list[KnowledgeFile] = files.copy()
    reference_source_paths: set[str] = {e.source for e in evidences}

    for src_rel in reference_source_paths:
        src_abs = requirements_dir / src_rel
        if src_abs.is_file():
            try:
                kf = KnowledgeFile(
                    path=src_abs,
                    rel_path=src_rel,
                    kind="team",
                    size_bytes=src_abs.stat().st_size,
                    fs_mtime=datetime.fromtimestamp(
                        src_abs.stat().st_mtime, tz=timezone.utc
                    ).replace(microsecond=0),
                )
                all_files.append(kf)
            except OSError as e:
                warnings.append(f"读取文件元数据 {src_rel} 失败: {e}")
    return all_files


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数。

    Args:
        argv: sys.argv[1:] 风格；None 时从 sys.argv 读

    Returns:
        argparse.Namespace，含所有参数

    Raises:
        SystemExit: argparse 自动处理（--help / 格式错误）
    """
    from common import REPO_ROOT

    parser = argparse.ArgumentParser(
        prog="context_usage_report",
        description="生成 context/** 知识利用率统计报告",
    )

    parser.add_argument(
        "--context-dir",
        type=Path,
        default=REPO_ROOT / "context",
        help="context 目录路径（默认 REPO_ROOT/context）",
    )
    parser.add_argument(
        "--requirements-dir",
        type=Path,
        default=REPO_ROOT / "requirements",
        help="requirements 目录路径（默认 REPO_ROOT/requirements）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "reports" / "context-usage.md",
        help="Markdown 报告输出路径（默认 REPO_ROOT/reports/context-usage.md）",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPO_ROOT / "reports" / "context-usage.json",
        help="JSON 报告输出路径（默认 REPO_ROOT/reports/context-usage.json）",
    )
    parser.add_argument(
        "--since",
        type=str,
        default="90d",
        help="查询范围（默认 90d）；格式 \\d+(d|w|m)，例 90d / 2w / 3m",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="过滤 context/project/<X>/；若不指定则不过滤",
    )
    parser.add_argument(
        "--only-experience",
        action="store_true",
        help="仅统计 context/team/experience/** 下的文件",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["md", "json", "both"],
        default="both",
        help="报告格式（默认 both）",
    )
    parser.add_argument(
        "--fail-on-broken-index",
        action="store_true",
        help="若检出 INDEX 断链则 exit 3",
    )
    parser.add_argument(
        "--fail-on-orphan",
        action="store_true",
        help="若检出孤岛文件则 exit 4",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="仓库根（测试注入）",
    )

    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    """执行报告生成逻辑。返回 exit code 0-5。"""
    # 校验输入目录
    err = _check_dirs(args.context_dir, args.requirements_dir)
    if err:
        return err

    # 解析 --since 与初始化
    try:
        since_days = _parse_since(args.since)
    except ValueError as e:
        print(f"ERROR: 无效的 --since 参数: {e}", file=sys.stderr)
        return 1

    warnings: list[str] = []

    # 扫描与过滤
    inv = ContextInventory(
        context_dir=args.context_dir,
        ignore_patterns=["**/draft/**", "**/INDEX.md"],
        repo_root=args.repo_root,
    )
    files = inv.scan()
    if args.only_experience:
        files = [f for f in files if "experience" in f.rel_path]
    if args.project:
        files = [
            f
            for f in files
            if f.rel_path.startswith(f"context/project/{args.project}/")
        ]

    graph_result = IndexGraph(
        context_dir=args.context_dir, repo_root=args.repo_root
    ).build(files)
    scanner = EvidenceScanner(
        requirements_dir=args.requirements_dir,
        context_files={f.rel_path for f in files},
        repo_root=args.repo_root,
    )
    evidences = scanner.scan()
    warnings.extend(scanner.warnings)

    # 分类 + git 时间戳
    file_cache = _build_file_cache(evidences, args.requirements_dir, warnings)
    applied = AppliedSignalClassifier().classify(evidences, file_cache)
    all_files_for_git = _build_all_files_for_git(
        files, evidences, args.requirements_dir, warnings
    )
    timestamps, git_warnings = fetch_git_timestamps(
        all_files_for_git, since_days, repo_root=args.repo_root
    )
    warnings.extend(git_warnings)

    # 聚合
    summaries = UsageAggregator(
        inventory=files,
        index_result=graph_result,
        references=evidences,
        applied=applied,
        git_timestamps=timestamps,
        now=datetime.now(tz=timezone.utc),
    ).aggregate()

    # 渲染 + 写入
    renderer = ReportRenderer(
        config={
            "context_dir": str(args.context_dir),
            "requirements_dir": str(args.requirements_dir),
            "since_days": since_days,
            "high_value_reference_min": 3,
            "stale_threshold_days": 90,
        },
        broken_links_count=len(graph_result.broken_links),
        orphans_count=len(graph_result.orphans),
        now=datetime.now(tz=timezone.utc),
    )

    exit_code = _render_and_write(renderer, summaries, warnings, args)
    if exit_code != 0:
        return exit_code

    # 输出摘要 + 检查标志
    _print_summary(summaries, warnings)

    if args.fail_on_broken_index and graph_result.broken_links:
        print(
            f"ERROR: BROKEN_LINKS_DETECTED ({len(graph_result.broken_links)} 条)",
            file=sys.stderr,
        )
        return 3
    if args.fail_on_orphan and graph_result.orphans:
        print(
            f"ERROR: ORPHANS_DETECTED ({len(graph_result.orphans)} 个文件)",
            file=sys.stderr,
        )
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    Args:
        argv: sys.argv[1:] 风格参数列表；None 时用 sys.argv[1:]

    Returns:
        进程退出码（0-5）
    """
    try:
        args = _parse_args(argv)
        return _run(args)
    except SystemExit:
        # argparse 自动处理 --help / 错误参数，返回 exit code 2
        # 设计中 "exit 1：argparse 自动"，让 argparse 行为保持原样
        raise


if __name__ == "__main__":
    sys.exit(main())
