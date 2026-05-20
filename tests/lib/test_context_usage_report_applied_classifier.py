"""tests for AppliedSignalClassifier（F-007 验收测试）。

覆盖 F-007 §验收标准：

  AC-1: AppliedEvidence 含 reference / rule / matched_keyword / section_heading 完整 4 字段
  AC-2: 窗口边界正确（前 5 / 后 10 / 同 ## ）
  AC-2b: ## 不同小节 → 不命中
  AC-3: fenced code 内关键字不命中（mask_code_blocks 生效）
  AC-4: 显式升级短语任一命中即归类 applied（含中文/英文/含空格短语）
  AC-5: 保守原则——关键字在窗口边界外不命中
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from context_usage_report import (  # noqa: E402
    AppliedEvidence,
    AppliedSignalClassifier,
    ReferenceEvidence,
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_evidence(
    target: str = "context/team/foo.md",
    source: str = "requirements/req-001/notes.md",
    line: int = 1,
    kind: str = "markdown_link",
    context_line: str = "",
) -> ReferenceEvidence:
    """构造 ReferenceEvidence 实例（默认值覆盖最常见场景）。"""
    return ReferenceEvidence(
        target=target,
        source=source,
        line=line,
        kind=kind,  # type: ignore[arg-type]
        context_line=context_line,
    )


def _make_cache(tmp_path: Path, source_rel: str, content: str) -> dict[Path, str]:
    """生成 file_cache：key 为绝对路径，value 为文件内容字符串。"""
    abs_path = tmp_path / source_rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    return {abs_path: content}


# ---------------------------------------------------------------------------
# AC-1 · AppliedEvidence 4 字段完整
# ---------------------------------------------------------------------------


def test_applied_evidence_fields_complete(tmp_path: Path) -> None:
    """classify() 返回的 AppliedEvidence 含全部 4 字段且类型正确。"""
    source_rel = "requirements/req-001/notes.md"
    # 构造：引用在 ## 小节内，窗口内有关键字
    content = (
        "# 文档\n"
        "## 决策记录\n"
        "这是引用行，参见 context/team/foo.md\n"
        "风险分析：此方案风险较低。\n"
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=3, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    # 至少一条命中（window_hit）
    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) >= 1, f"应有 window_hit 命中，实际：{results}"
    hit = hits[0]
    assert isinstance(hit, AppliedEvidence)
    assert hit.reference == ev
    assert hit.rule in ("window_hit", "explicit_upgrade")
    assert isinstance(hit.matched_keyword, str) and len(hit.matched_keyword) > 0
    # window_hit 时 section_heading 不为 None
    assert hit.section_heading is not None
    assert isinstance(hit.section_heading, str)


# ---------------------------------------------------------------------------
# AC-2 · 窗口边界：前 5 / 后 10 行内命中 + 同 ## 小节
# ---------------------------------------------------------------------------


def test_window_boundary_within_hits(tmp_path: Path) -> None:
    """关键字恰好在前 5 行内（边界值）→ 命中。"""
    source_rel = "requirements/req-002/notes.md"
    # 引用在第 7 行，关键字在第 2 行（距离 5，= WINDOW_BEFORE），同一 ## 小节
    lines = [
        "# 文档\n",          # L1
        "## 分析小节\n",      # L2  → 开启 H2
        "风险：此处有风险。\n",  # L3  关键字"风险"
        "背景说明。\n",        # L4
        "另一段。\n",          # L5
        "再一段。\n",          # L6
        "引用行 context/team/foo.md\n",  # L7  ref_lineno=7，window=[2..17]
        "后续内容。\n",        # L8
    ]
    content = "".join(lines)
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=7, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) >= 1, "关键字在前 5 行内应命中"
    assert hits[0].matched_keyword == "风险"
    assert hits[0].section_heading == "分析小节"


def test_window_boundary_after_10_hits(tmp_path: Path) -> None:
    """关键字恰好在后 10 行内（边界值）→ 命中。"""
    source_rel = "requirements/req-003/notes.md"
    # 引用在第 3 行，关键字在第 13 行（距离 10，= WINDOW_AFTER），同一 ## 小节
    # 注意：小节标题不含关键字，避免 heading 行干扰断言
    lines = ["# 文档\n", "## 详细记录\n", "引用行 context/team/foo.md\n"]
    lines += ["填充行。\n"] * 9  # L4..L12
    lines.append("Decision 分析。\n")  # L13  关键字，距引用 L3 差 10 = WINDOW_AFTER
    lines.append("其他内容。\n")       # L14
    content = "".join(lines)
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=3, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) >= 1, "关键字在后 10 行内应命中"
    assert hits[0].matched_keyword == "Decision"


# ---------------------------------------------------------------------------
# AC-2b · 不同 ## 小节 → 不命中
# ---------------------------------------------------------------------------


def test_different_section_no_hit(tmp_path: Path) -> None:
    """关键字在窗口内但属于不同 ## 小节 → 路径 A 不命中。"""
    source_rel = "requirements/req-004/notes.md"
    # 引用在第 4 行（## 小节 A），关键字在第 6 行（## 小节 B）
    content = (
        "# 文档\n"           # L1
        "## 小节 A\n"        # L2
        "背景说明。\n"        # L3
        "引用 context/team/foo.md\n"  # L4  ref_lineno=4，section=小节 A
        "## 小节 B\n"        # L5  新 H2，切换 section
        "风险分析。\n"        # L6  关键字"风险"在小节 B，与引用不同 section
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=4, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) == 0, f"不同 ## 小节内关键字不应命中，实际：{results}"


# ---------------------------------------------------------------------------
# AC-3 · fenced code 内关键字不命中
# ---------------------------------------------------------------------------


def test_fenced_code_keyword_excluded(tmp_path: Path) -> None:
    """fenced code block 内的关键字经 mask_code_blocks 后不应命中。"""
    source_rel = "requirements/req-005/notes.md"
    content = (
        "# 文档\n"
        "## 实现小节\n"
        "引用 context/team/foo.md\n"      # L3  ref_lineno=3
        "```\n"
        "Decision = '这是代码注释'\n"     # L5  在 fenced code 内，应被 mask
        "风险 = True\n"                   # L6  在 fenced code 内，应被 mask
        "```\n"
        "正文无关键字。\n"
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=3, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) == 0, f"fenced code 内关键字不应命中，实际：{results}"


def test_inline_code_keyword_excluded(tmp_path: Path) -> None:
    """inline code 内的关键字不应命中（`风险` 被 mask 掉）。"""
    source_rel = "requirements/req-005b/notes.md"
    content = (
        "# 文档\n"
        "## 测试小节\n"
        "引用 context/team/foo.md\n"       # L3  ref_lineno=3
        "这是 `风险` 的 inline code。\n"   # L4  关键字在 inline code 内
        "普通段落。\n"
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=3, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) == 0, f"inline code 内关键字不应命中，实际：{results}"


# ---------------------------------------------------------------------------
# AC-4 · 显式升级短语命中（含中文、英文、含空格短语）
# ---------------------------------------------------------------------------


def test_explicit_upgrade_chinese_phrase(tmp_path: Path) -> None:
    """中文升级短语"升级为 checklist"命中 → rule=explicit_upgrade。"""
    source_rel = "requirements/req-006/notes.md"
    content = (
        "# 文档\n"
        "这条经验已升级为 checklist。\n"  # 含升级短语
        "引用 context/team/foo.md\n"
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=3, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "explicit_upgrade"]
    assert len(hits) >= 1, f"中文升级短语应命中，实际：{results}"
    assert hits[0].matched_keyword == "升级为 checklist"
    assert hits[0].section_heading is None  # explicit_upgrade 不提供 section_heading


def test_explicit_upgrade_english_phrase(tmp_path: Path) -> None:
    """英文升级短语"按该经验落 test"命中 → rule=explicit_upgrade。"""
    source_rel = "requirements/req-007/notes.md"
    content = (
        "# 文档\n"
        "已按该经验落 test，覆盖边界场景。\n"
        "引用 context/team/foo.md\n"
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=3, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "explicit_upgrade"]
    assert len(hits) >= 1, f"英文升级短语应命中，实际：{results}"
    assert hits[0].matched_keyword == "按该经验落 test"


def test_explicit_upgrade_all_phrases_hit(tmp_path: Path) -> None:
    """文件含多条升级短语时，至少命中一条（取第一个命中）。"""
    source_rel = "requirements/req-008/notes.md"
    content = (
        "# 文档\n"
        "引用 context/team/foo.md\n"
        "来自该经验的设计。\n"
        "同时升级为 SOP。\n"
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=2, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "explicit_upgrade"]
    assert len(hits) >= 1, "含升级短语时应命中"
    assert hits[0].matched_keyword in AppliedSignalClassifier.UPGRADE_PHRASES


# ---------------------------------------------------------------------------
# AC-5 · 保守原则——关键字在窗口边界外不命中
# ---------------------------------------------------------------------------


def test_keyword_outside_window_before_no_hit(tmp_path: Path) -> None:
    """关键字在引用行前第 6 行（超出 WINDOW_BEFORE=5）→ 不命中。"""
    source_rel = "requirements/req-009/notes.md"
    # 引用在 L8，关键字在 L2（距离 6 > 5 = WINDOW_BEFORE），同一 ## 小节
    lines = [
        "# 文档\n",           # L1
        "## 分析小节\n",       # L2  → 开启 H2
        "风险 在这里。\n",     # L3  关键字，距引用 L8 差 5 行（L3→L8 差 5，但 L3 是 3，L8 是 8，差 = 8-3 = 5）
    ]
    # 等等，WINDOW_BEFORE=5 means 前 5 行。引用在 L8，window 从 L3(8-5=3) 到 L18(8+10)。
    # 要使关键字"在边界外"，需要关键字在 L2（即 8-6=2），不在窗口 [L3..L18] 内。
    # 重新构造：引用在 L8，关键字在 L2（距离 6）
    lines = [
        "# 文档\n",           # L1
        "## 大小节\n",         # L2  → 开启 H2
        "风险 关键字。\n",     # L3  距引用 L9 差 6 行：window=[L4..L19]，L3 < L4，在窗口外
        "填充行。\n",          # L4
        "填充行。\n",          # L5
        "填充行。\n",          # L6
        "填充行。\n",          # L7
        "填充行。\n",          # L8
        "引用 context/team/foo.md\n",  # L9  ref_lineno=9，window=[4..19]，L3 < 4
        "后续。\n",            # L10
    ]
    content = "".join(lines)
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=9, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) == 0, f"窗口外关键字（前第 6 行）不应命中，实际：{results}"


def test_keyword_outside_window_after_no_hit(tmp_path: Path) -> None:
    """关键字在引用行后第 11 行（超出 WINDOW_AFTER=10）→ 不命中。"""
    source_rel = "requirements/req-010/notes.md"
    # 引用在 L3，关键字在 L14（距离 11 > 10 = WINDOW_AFTER），同一 ## 小节
    lines = [
        "# 文档\n",          # L1
        "## 测试小节\n",      # L2  → 开启 H2
        "引用 context/team/foo.md\n",  # L3  ref_lineno=3，window=[1..13]
    ]
    lines += ["填充行。\n"] * 10  # L4..L13
    lines.append("风险 超出范围。\n")  # L14  距离 11 > 10，在窗口外
    content = "".join(lines)
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=3, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) == 0, f"窗口外关键字（后第 11 行）不应命中，实际：{results}"


# ---------------------------------------------------------------------------
# 额外：双路命中 → 各产一条 AppliedEvidence（rule 字段不同）
# ---------------------------------------------------------------------------


def test_double_hit_produces_two_results(tmp_path: Path) -> None:
    """同一 reference 同时满足路径 A + 路径 B → 各产一条，不去重。"""
    source_rel = "requirements/req-011/notes.md"
    content = (
        "# 文档\n"
        "## 升级记录\n"
        "已升级为 SOP，详见下方。\n"       # 升级短语（路径 B）
        "引用 context/team/foo.md\n"       # L4  ref_lineno=4
        "风险：已纳入 SOP 管控。\n"         # 关键字"风险"在窗口内（路径 A）
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=4, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    rules = {r.rule for r in results}
    assert "window_hit" in rules, f"应有 window_hit，实际：{results}"
    assert "explicit_upgrade" in rules, f"应有 explicit_upgrade，实际：{results}"
    assert len(results) == 2, f"双路命中应各产一条，实际：{results}"


# ---------------------------------------------------------------------------
# 额外：file_cache 无对应 source → 跳过不抛
# ---------------------------------------------------------------------------


def test_missing_file_cache_entry_no_exception(tmp_path: Path) -> None:
    """file_cache 中无对应 source 文件时，classify 不抛异常，返回空列表。"""
    ev = _make_evidence(line=1, source="requirements/nonexistent/notes.md")
    classifier = AppliedSignalClassifier()

    # 空 file_cache
    results = classifier.classify([ev], {})

    assert results == [], f"无 cache 时应返回空列表，实际：{results}"


# ---------------------------------------------------------------------------
# 额外：引用行在第一个 H2 之前（无小节）→ 路径 A 不命中
# ---------------------------------------------------------------------------


def test_evidence_before_first_h2_no_window_hit(tmp_path: Path) -> None:
    """引用行位于第一个 ## 之前（section_heading=None）→ 路径 A 不命中（保守原则）。"""
    source_rel = "requirements/req-012/notes.md"
    content = (
        "# 大标题\n"
        "引用 context/team/foo.md\n"    # L2  ref_lineno=2，无 H2，section=None
        "风险分析。\n"                  # L3  关键字在窗口内，但 section=None
        "## 小节\n"                    # L4  H2 在引用之后
        "内容。\n"
    )
    cache = _make_cache(tmp_path, source_rel, content)
    ev = _make_evidence(line=2, source=source_rel)
    classifier = AppliedSignalClassifier()

    results = classifier.classify([ev], cache)

    hits = [r for r in results if r.rule == "window_hit"]
    assert len(hits) == 0, f"H2 之前引用行不应 window_hit，实际：{results}"
