"""tests for scripts/lib/markdown_links.py（F-003 验收测试）。

覆盖 7 个公开 API：
  LINK_RE           — 正则匹配规则
  extract_links     — 链接提取（含 mask 联动）
  resolve_link      — 路径解析（仓内/外链/越界）
  slugify           — heading slug 生成
  extract_headings  — 多级 heading 解析
  glob_match        — 支持 ** 的 glob 匹配
  mask_code_blocks  — fenced / inline code 遮蔽
"""
from __future__ import annotations

import sys
from pathlib import Path

# 将 scripts/lib 加入 path，与既有测试保持一致
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from markdown_links import (
    LINK_RE,
    MarkdownLink,
    extract_headings,
    extract_links,
    glob_match,
    mask_code_blocks,
    resolve_link,
    slugify,
)


# ---------------------------------------------------------------------------
# LINK_RE — 正则匹配规则
# ---------------------------------------------------------------------------


def test_link_re_matches_single_link() -> None:
    """单条 [text](url) 被匹配。"""
    m = LINK_RE.search("[hello](world.md)")
    assert m is not None
    assert m.group(1) == "hello"
    assert m.group(2) == "world.md"


def test_link_re_does_not_match_image() -> None:
    """图片 ![alt](src) 不应被匹配（负向前瞻 (?<!!)）。"""
    assert LINK_RE.search("![alt](image.png)") is None


def test_link_re_matches_multiple_on_same_line() -> None:
    """同一行多个链接均被匹配。"""
    line = "[a](a.md) and [b](b.md)"
    matches = LINK_RE.findall(line)
    assert len(matches) == 2
    assert matches[0] == ("a", "a.md")
    assert matches[1] == ("b", "b.md")


# ---------------------------------------------------------------------------
# extract_links — 链接提取
# ---------------------------------------------------------------------------


def test_extract_links_empty_text_returns_empty() -> None:
    """空文本返回空列表。"""
    assert extract_links("") == []


def test_extract_links_single_link_line_number() -> None:
    """单链接，行号为 1-based。"""
    links = extract_links("[foo](bar.md)")
    assert len(links) == 1
    assert links[0] == MarkdownLink(text="foo", url="bar.md", line=1)


def test_extract_links_multiline_correct_line_numbers() -> None:
    """跨行文本，行号对应各自所在行。"""
    md = "first line\n[a](a.md)\nthird line\n[b](b.md)"
    links = extract_links(md)
    assert len(links) == 2
    assert links[0].line == 2
    assert links[1].line == 4


def test_extract_links_code_block_pseudolink_skipped() -> None:
    """fenced code 块内的 '[text](url)' 不应被提取。"""
    md = "```\n[fake](fake.md)\n```\n[real](real.md)"
    links = extract_links(md)
    assert len(links) == 1
    assert links[0].url == "real.md"


# ---------------------------------------------------------------------------
# slugify — heading slug 生成（以实际源码行为为准）
# ---------------------------------------------------------------------------


def test_slugify_ascii_lowercase() -> None:
    """纯英文标题转小写，空格变 -。"""
    assert slugify("Hello World") == "hello-world"


def test_slugify_chinese_preserved() -> None:
    """中文字符被保留（\\w 覆盖 Unicode）。"""
    slug = slugify("上下文工程")
    assert "上下文工程" in slug


def test_slugify_mixed_chinese_english() -> None:
    """中英文混合：英文小写、空格转 -、中文保留。"""
    slug = slugify("Context 工程 Principles")
    # 英文部分应小写，中文保留，空格变 -
    assert "context" in slug
    assert "工程" in slug
    assert "principles" in slug
    assert " " not in slug


def test_slugify_punctuation_stripped() -> None:
    """非 \\w / 中文 / 空白 / - 的标点被去掉。"""
    slug = slugify("Hello, World!")
    assert "," not in slug
    assert "!" not in slug
    assert "hello" in slug


def test_slugify_multiple_spaces_become_single_hyphen() -> None:
    """多个空白折叠为单个 -（re.sub(r'\\s+', '-', ...)）。"""
    slug = slugify("a   b")
    assert slug == "a-b"


# ---------------------------------------------------------------------------
# resolve_link — 路径解析
# ---------------------------------------------------------------------------


def test_resolve_link_external_returns_none(tmp_path: Path) -> None:
    """http:// 外链返回 None。"""
    result = resolve_link("http://example.com", tmp_path / "src.md", tmp_path)
    assert result is None


def test_resolve_link_intra_anchor_returns_none(tmp_path: Path) -> None:
    """#anchor 纯锚点返回 None。"""
    result = resolve_link("#section", tmp_path / "src.md", tmp_path)
    assert result is None


def test_resolve_link_existing_file_returns_path(tmp_path: Path) -> None:
    """仓内存在的文件返回绝对路径（非 None）。"""
    target = tmp_path / "docs" / "README.md"
    target.parent.mkdir(parents=True)
    target.write_text("# hi")
    src = tmp_path / "src.md"
    result = resolve_link("docs/README.md", src, tmp_path)
    assert result is not None
    assert result == target.resolve()


def test_resolve_link_nonexistent_file_returns_path_not_none(tmp_path: Path) -> None:
    """仓内不存在的文件仍返回理论路径 Path（断链由调用方判定，不返回 None）。"""
    src = tmp_path / "src.md"
    result = resolve_link("nonexistent.md", src, tmp_path)
    assert result is not None
    assert isinstance(result, Path)


def test_resolve_link_out_of_repo_returns_none(tmp_path: Path) -> None:
    """../../ 越界到 repo_root 外返回 None。"""
    src = tmp_path / "a" / "b" / "src.md"
    src.parent.mkdir(parents=True)
    result = resolve_link("../../../etc/passwd", src, tmp_path)
    assert result is None


def test_resolve_link_fragment_stripped(tmp_path: Path) -> None:
    """foo.md#bar 中 fragment 被截掉，解析 foo.md 部分。"""
    target = tmp_path / "foo.md"
    target.write_text("# foo")
    src = tmp_path / "src.md"
    result = resolve_link("foo.md#bar", src, tmp_path)
    assert result is not None
    assert result == target.resolve()


# ---------------------------------------------------------------------------
# extract_headings — 多级 heading 解析
# ---------------------------------------------------------------------------


def test_extract_headings_multiple_levels() -> None:
    """## / ### / #### 均被识别，level 对应 # 数量。"""
    md = "## H2\n### H3\n#### H4"
    headings = extract_headings(md)
    assert len(headings) == 3
    assert headings[0][0] == 2
    assert headings[1][0] == 3
    assert headings[2][0] == 4


def test_extract_headings_text_and_slug() -> None:
    """返回 (level, text, slug) 三元组，slug = slugify(text)。"""
    md = "## Hello World"
    headings = extract_headings(md)
    assert len(headings) == 1
    level, text, slug = headings[0]
    assert level == 2
    assert text == "Hello World"
    assert slug == slugify("Hello World")


def test_extract_headings_chinese_text() -> None:
    """中文标题被正确解析，text 保留原始中文。"""
    md = "## 上下文工程"
    headings = extract_headings(md)
    assert len(headings) == 1
    level, text, slug = headings[0]
    assert text == "上下文工程"
    assert "上下文工程" in slug


def test_extract_headings_preserves_order() -> None:
    """按出现顺序返回。"""
    md = "### C\n## A\n#### B"
    headings = extract_headings(md)
    texts = [h[1] for h in headings]
    assert texts == ["C", "A", "B"]


# ---------------------------------------------------------------------------
# glob_match — 支持 ** 的 glob 匹配
# ---------------------------------------------------------------------------


def test_glob_match_simple_star() -> None:
    """简单 * 匹配：无 ** 时委托 fnmatch，* 在 fnmatch 中可跨 /。"""
    assert glob_match("context/foo.md", "context/*.md") is True
    # fnmatch 的 * 跨目录分隔符，因此 context/sub/foo.md 也匹配 context/*.md
    assert glob_match("context/sub/foo.md", "context/*.md") is True
    # 完全不同前缀则不匹配
    assert glob_match("other/foo.md", "context/*.md") is False


def test_glob_match_double_star_any_depth() -> None:
    """** 匹配任意层级路径。"""
    assert glob_match("context/team/foo.md", "context/**/*.md") is True
    assert glob_match("context/team/sub/bar.md", "context/**/*.md") is True


def test_glob_match_question_mark_single_char() -> None:
    """? 仅匹配单个非 / 字符。"""
    assert glob_match("foo.md", "fo?.md") is True
    assert glob_match("fooo.md", "fo?.md") is False


def test_glob_match_no_match() -> None:
    """不匹配的路径返回 False。"""
    assert glob_match("requirements/REQ-001/meta.yaml", "context/**") is False


# ---------------------------------------------------------------------------
# mask_code_blocks — fenced / inline code 遮蔽（≥ 3 用例）
# ---------------------------------------------------------------------------


def test_mask_code_blocks_fenced_replaced_by_spaces() -> None:
    """fenced ``` 块内字符被替换为空格，非 code 区原文保留。"""
    md = "before\n```\n[link](url)\n```\nafter"
    masked = mask_code_blocks(md)
    lines = masked.splitlines()
    # 'before' 和 'after' 行原文不变
    assert lines[0] == "before"
    assert lines[4] == "after"
    # fenced block 行（含开关行）被空格替换
    assert lines[1].strip() == ""
    assert lines[2].strip() == ""
    assert lines[3].strip() == ""


def test_mask_code_blocks_inline_code_replaced() -> None:
    """inline `code` 内字符被替换为等长空格，其余保留。"""
    md = "see `foo` here"
    masked = mask_code_blocks(md)
    assert "see" in masked
    assert "here" in masked
    # 'foo' 被空格替换
    assert "foo" not in masked
    assert len(masked) == len(md)


def test_mask_code_blocks_multiline_fenced_with_language_tag() -> None:
    """跨行 fenced（```python ... ```）整体被遮蔽，长度等长。"""
    md = "```python\ndef hello():\n    pass\n```\nnormal"
    masked = mask_code_blocks(md)
    assert len(masked) == len(md)
    # code 区行均为空格
    lines = masked.splitlines()
    assert lines[0].strip() == ""   # ```python 行被替换
    assert lines[1].strip() == ""   # def hello(): 行被替换
    assert lines[2].strip() == ""   # pass 行被替换
    assert lines[3].strip() == ""   # ``` 结束行被替换
    assert lines[4] == "normal"     # 非 code 区原文保留


def test_mask_code_blocks_length_preserved_with_trailing_newline() -> None:
    """原文以 \\n 结尾时，masked 结果长度与原文相同。"""
    md = "```\ncode\n```\n"
    masked = mask_code_blocks(md)
    assert len(masked) == len(md)


def test_mask_code_blocks_non_code_area_unchanged() -> None:
    """非 code 区的普通文本内容原封不动。"""
    md = "# Heading\n\nSome paragraph text here.\n"
    masked = mask_code_blocks(md)
    assert masked == md
