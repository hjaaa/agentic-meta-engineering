"""Markdown 链接 / heading / slug 解析公共模块。

被 scripts/lib/check_index.py 与 scripts/lib/context_usage_report.py 共用。
纯函数模块，无 CLI 入口。所有路径解析以 REPO_ROOT 为基准。
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

# 与 check_index.py:31 一致：[text](url)，不匹配图片 ![alt](url)
LINK_RE: re.Pattern = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
# 与 check_index.py:33 一致：^# 多级标题
HEADING_RE: re.Pattern = re.compile(r"^(#+)\s+(.+?)\s*$")

# inline code span：N 个反引号包不含反引号/换行的内容
_RE_INLINE_CODE = re.compile(r"`+[^`\n]+?`+")

# 外链/协议前缀
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "ftp://", "tel://", "tel:")


class MarkdownLink(NamedTuple):
    """单条 Markdown 链接的解析结果。

    Attributes:
        text: 链接显示文本（`[text](url)` 的 text 部分），可为空字符串
        url:  原始 url 字符串，未做 urldecode 与路径解析
        line: 链接所在行号，1-based
    """

    text: str
    url: str
    line: int


def mask_code_blocks(md_text: str) -> str:
    """把 fenced code (``` / ~~~) 与 inline code (` `) 内的字符替换为空白，
    保持行列偏移不变。

    用途：避免 `LINK_RE` / `HEADING_RE` 误匹配 code 内的 markdown。

    Args:
        md_text: Markdown 全文字符串（可多行）。

    Returns:
        同长度字符串，code 区被空格填充；非 code 区原文保留。
        保证：len(result) == len(md_text)，每个换行符位置不变。

    Side-effects: 无（纯函数）。
    """
    out: list[str] = []
    in_fence = False
    fence_marker = ""  # 记录开启 fence 的标记（``` 或 ~~~）

    for line in md_text.splitlines():
        stripped = line.lstrip()
        # 判断是否是 fenced code 的开始或结束行
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = "```" if stripped.startswith("```") else "~~~"
            if not in_fence:
                # 开始 fenced block
                in_fence = True
                fence_marker = marker
                out.append(" " * len(line))
            elif marker == fence_marker:
                # 结束 fenced block（结束行必须与开始 marker 类型一致）
                in_fence = False
                fence_marker = ""
                out.append(" " * len(line))
            else:
                # 在 fenced block 内，另一种 marker 当普通内容
                out.append(" " * len(line))
            continue

        if in_fence:
            out.append(" " * len(line))
            continue

        # 非 fenced 区：mask inline code（用等长空格替换）
        masked = _RE_INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)
        out.append(masked)

    result = "\n".join(out)
    # splitlines() 会丢掉末尾换行符；若原文以换行结尾，补回保持长度一致
    if md_text.endswith("\n"):
        result += "\n"
    return result


def extract_links(md_text: str) -> list[MarkdownLink]:
    """从 Markdown 文本抽取所有非图片链接。

    Args:
        md_text: 文件全文。允许多行；不读 fenced code 内的"伪链接"（实现里调
                 `mask_code_blocks` 先 mask，再在 masked 文本上运行 LINK_RE，
                 但返回的 text/url 从原始行取值）。

    Returns:
        list[MarkdownLink]，按行号升序。空文本返回空列表。

    Side-effects: 无（纯函数）。
    """
    masked = mask_code_blocks(md_text)
    out: list[MarkdownLink] = []
    orig_lines = md_text.splitlines()
    masked_lines = masked.splitlines()

    for i, (orig_line, masked_line) in enumerate(zip(orig_lines, masked_lines), start=1):
        for m in LINK_RE.finditer(masked_line):
            # url/text 从原始行同位置取，保证内容未被 mask 污染
            orig_m = LINK_RE.search(orig_line, m.start())
            if orig_m and orig_m.start() == m.start():
                text = orig_m.group(1)
                url = orig_m.group(2).strip()
            else:
                text = m.group(1)
                url = m.group(2).strip()
            out.append(MarkdownLink(text=text, url=url, line=i))

    return out


def is_external_or_intra_anchor(link_url: str) -> bool:
    """判定是否为外链或纯 anchor 引用，跳过统计。

    判定条件（任一为真即跳过）：
    - 以 `http://` / `https://` / `mailto:` / `ftp://` / `tel:` 等协议前缀开头
    - 以 `#` 开头（intra-document anchor）
    - 空字符串

    Args:
        link_url: 原始 url 字符串。

    Returns:
        True = 跳过（外链/anchor/空）；False = 仓内引用需进一步 resolve。

    Side-effects: 无（纯函数）。
    """
    if not link_url:
        return True
    if link_url.startswith("#"):
        return True
    for prefix in _EXTERNAL_PREFIXES:
        if link_url.startswith(prefix):
            return True
    return False


def resolve_link(
    link_url: str, source_file: Path, repo_root: Path
) -> Path | None:
    """把 Markdown link 的 url 解析为仓库内绝对路径。

    Args:
        link_url:    原始 url（可能含 `./` / `../` / fragment `#anchor` / url-encoding）
        source_file: 链接所在文件的绝对路径（用于相对路径解析）
        repo_root:   仓库根（绝对路径）

    Returns:
        - 仓内文件 → 绝对路径 Path（目标不存在时仍返回理论路径，断链由调用方判定）
        - 外链 / intra-anchor / mailto / 空 → None
        - 解析结果不在 repo_root 子树内（如 `../../` 越界）→ None

    幂等：同样输入返回同样路径；不做任何 IO 写操作。

    Raises: 不抛任何异常（解析失败返回 None）。
    """
    if is_external_or_intra_anchor(link_url):
        return None

    try:
        # 截断 anchor
        path_part, _, _ = link_url.partition("#")
        path_part = unquote(path_part)

        if not path_part:
            return None

        if path_part.startswith("/"):
            # 绝对路径（从 repo 根）
            target = repo_root / path_part.lstrip("/")
        else:
            # 相对路径（基准：source_file 所在目录）
            target = (source_file.parent / path_part).resolve()

        # 安全检查：不允许越界到 repo_root 外
        # 用 resolve() 展开 symlink 后比较，避免 macOS /var → /private/var 问题
        resolved_root = repo_root.resolve()
        resolved_target = target.resolve()
        try:
            resolved_target.relative_to(resolved_root)
        except ValueError:
            return None

        return resolved_target
    except Exception:
        return None


def slugify(heading_text: str) -> str:
    """把标题文本规约为 anchor slug。

    规则（与 check_index.py:78 _slugify 等价）：
    1. 小写（strip 首尾空格）
    2. 去掉非 `\\w`（即 [a-zA-Z0-9_]）、非中文（一-龥）、非空白、非连字符的字符
    3. 把空白替换为 `-`

    注意：与 detailed-design 描述的"非字母数字替换为 -"略有差异——
    实际以 check_index.py 的行为为准：中文字符和下划线被保留（\\w 包含 Unicode 字母）。

    Args:
        heading_text: 标题原始文本（不含 `#` 前缀）。

    Returns:
        slug 字符串，可能为空字符串（如纯符号标题）。

    Side-effects: 无（纯函数）。
    """
    s = heading_text.lower().strip()
    s = re.sub(r"[^\w一-龥\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s


def extract_headings(md_text: str) -> list[tuple[int, str, str]]:
    """抽取所有 heading（level / text / slug）。

    Args:
        md_text: Markdown 全文字符串。

    Returns:
        list[(level, text, slug)]，按出现顺序。
        - level: int，H1=1, H6=6
        - text: 标题原始文本（不含 `#` 与首尾空格）
        - slug: slugify(text) 结果

    Side-effects: 无（纯函数）。
    """
    out: list[tuple[int, str, str]] = []
    for line in md_text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            out.append((level, text, slugify(text)))
    return out


def glob_match(rel_path: str, pattern: str) -> bool:
    """支持 `**` 的 glob 匹配。

    扩展自 fnmatch：`**` 视为"任意层级"，其余交 fnmatch。与
    `check_index.py:_fnmatch_glob` 等价。

    Args:
        rel_path: 相对 repo_root 的路径（`/` 分隔）
        pattern:  glob 表达式（支持 `*` / `?` / `**`）

    Returns:
        True = 路径匹配该模式；False = 不匹配。

    幂等：纯函数，无副作用。
    """
    if "**" not in pattern:
        return fnmatch.fnmatch(rel_path, pattern)

    # 把 ** 变正则 .*，* 变 [^/]*，? 变 [^/]
    regex_parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i : i + 2] == "**":
            regex_parts.append(".*")
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                i += 1
        elif pattern[i] == "*":
            regex_parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            regex_parts.append("[^/]")
            i += 1
        elif pattern[i] == ".":
            regex_parts.append(r"\.")
            i += 1
        else:
            regex_parts.append(re.escape(pattern[i]))
            i += 1

    regex = "^" + "".join(regex_parts) + "$"
    return re.match(regex, rel_path) is not None
