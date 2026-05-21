"""F-010 · ReportRenderer 验收测试。

覆盖：Markdown 4 章节 + JSON 渲染 + 原子化写入。
接口/数据结构来源：detailed-design.md §组件 6（interfaces_frozen）
"""
from __future__ import annotations

import json
import re as _re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parents[1] / "scripts" / "lib"))
sys.path.insert(0, str(_THIS_DIR))

from context_usage_report import (  # noqa: E402
    GitTimestamp,
    ReportRenderer,
)
from _context_usage_helpers import (  # noqa: E402
    make_aggregator as _make_aggregator,
    make_applied as _make_applied,
    make_file as _make_file,
    make_ref as _make_ref,
)


def _make_renderer(
    config: dict | None = None,
    broken_links_count: int = 0,
    orphans_count: int = 0,
    now: datetime | None = None,
) -> ReportRenderer:
    """创建 ReportRenderer 测试实例（含默认值）。"""
    if config is None:
        config = {
            "context_dir": "context",
            "requirements_dir": "requirements",
            "since_days": 90,
            "high_value_reference_min": 3,
            "stale_threshold_days": 90,
        }
    if now is None:
        now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    return ReportRenderer(config, broken_links_count, orphans_count, now)


def test_renderer_init_raises_on_missing_config_key() -> None:
    """缺失必填 config key → KeyError。"""
    partial_config = {
        "context_dir": "context",
        "requirements_dir": "requirements",
    }
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    with pytest.raises(KeyError):
        ReportRenderer(partial_config, 0, 0, now)


def test_renderer_markdown_has_four_h2_sections_in_order() -> None:
    """render_markdown 输出 4 个 H2 标题，顺序固定：总览 → 高价值知识 → 待治理知识 → 引用明细。"""
    renderer = _make_renderer()
    md = renderer.render_markdown([], [])

    h2_pattern = r"^## (.+)$"
    h2_matches = list(_re.finditer(h2_pattern, md, _re.MULTILINE))
    h2_titles = [m.group(1) for m in h2_matches]

    assert len(h2_titles) >= 4
    assert h2_titles[0] == "总览"
    assert h2_titles[1] == "高价值知识"
    assert h2_titles[2] == "待治理知识"
    assert h2_titles[3] == "引用明细"


def test_renderer_markdown_empty_summaries() -> None:
    """summaries=[] 仍输出 4 个 H2 且不抛异常。"""
    renderer = _make_renderer()
    md = renderer.render_markdown([], [])
    assert "## 总览" in md
    assert "## 高价值知识" in md
    assert "## 待治理知识" in md
    assert "## 引用明细" in md
    assert isinstance(md, str)


def test_renderer_markdown_high_value_section() -> None:
    """status=high_value 的条目出现在「## 高价值知识」段。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/valuable.md")
    ref = _make_ref("context/team/valuable.md", source="requirements/r1/doc.md")
    applied = [_make_applied(ref)]

    refs = [_make_ref("context/team/valuable.md", source=f"requirements/r{i}/doc.md") for i in range(3)]
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/valuable.md": ["context/INDEX.md"]},
        references=refs,
        applied=applied,
        now=now,
    )
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    md = renderer.render_markdown(summaries, [])

    high_value_section = md.split("## 待治理知识")[0]
    assert "context/team/valuable.md" in high_value_section


def test_renderer_markdown_to_review_section_grouped_by_status() -> None:
    """待治理知识按 status 分小标题 H3（orphan/needs_review/visible_unused/stale）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file_orphan = _make_file("context/team/orphan.md")
    agg = _make_aggregator([file_orphan], now=now)
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    md = renderer.render_markdown(summaries, [])

    assert "### orphan" in md


def test_renderer_markdown_reference_evidence_section() -> None:
    """引用明细章节展示 reference_evidences（source/line/kind/context_line）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/referenced.md")
    ref = _make_ref(
        "context/team/referenced.md",
        source="requirements/r1/design.md",
        line=42,
        kind="markdown_link",
    )
    agg = _make_aggregator([file], references=[ref], now=now)
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    md = renderer.render_markdown(summaries, [])

    ref_section = md.split("## 引用明细")[-1]
    assert "context/team/referenced.md" in ref_section
    assert "requirements/r1/design.md" in ref_section


def test_renderer_json_has_all_toplevel_fields() -> None:
    """JSON 顶层字段齐全：generated_at/tool_version/schema_version/config/summary/files/warnings。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    renderer = _make_renderer(now=now)
    json_str = renderer.render_json([], [])

    data = json.loads(json_str)
    assert "generated_at" in data
    assert "tool_version" in data
    assert "schema_version" in data
    assert "config" in data
    assert "summary" in data
    assert "files" in data
    assert "warnings" in data


def test_renderer_json_tool_version_and_schema_version() -> None:
    """tool_version == "0.1.0"，schema_version == 1。"""
    renderer = _make_renderer()
    json_str = renderer.render_json([], [])
    data = json.loads(json_str)

    assert data["tool_version"] == "0.1.0"
    assert data["schema_version"] == 1


def test_renderer_json_summary_by_status_has_all_six_keys() -> None:
    """summary.by_status 含全部 6 个枚举值作为键。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/x.md")
    agg = _make_aggregator([file], now=now)
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    json_str = renderer.render_json(summaries, [])
    data = json.loads(json_str)

    by_status = data["summary"]["by_status"]
    expected_keys = {"orphan", "needs_review", "visible_unused", "high_value", "stale_candidate", "active"}
    assert set(by_status.keys()) == expected_keys


def test_renderer_json_summary_counts_are_int() -> None:
    """summary 中 total/broken_links/orphans 是 int；by_status 各值是 int。"""
    renderer = _make_renderer(broken_links_count=2, orphans_count=3)
    json_str = renderer.render_json([], [])
    data = json.loads(json_str)

    assert isinstance(data["summary"]["total"], int)
    assert isinstance(data["summary"]["broken_links"], int)
    assert isinstance(data["summary"]["orphans"], int)
    assert data["summary"]["broken_links"] == 2
    assert data["summary"]["orphans"] == 3
    for v in data["summary"]["by_status"].values():
        assert isinstance(v, int)


def test_renderer_json_datetime_format_iso8601_z() -> None:
    """datetime 字段输出 YYYY-MM-DDTHH:MM:SSZ 格式（ISO-8601 UTC）。"""
    now = datetime(2026, 5, 20, 8, 30, 45, tzinfo=timezone.utc)
    file = _make_file("context/team/x.md")
    ref = _make_ref("context/team/x.md", source="requirements/r1/doc.md")
    ts = GitTimestamp(
        first_commit_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        last_commit_at=datetime(2026, 5, 19, 10, 30, 0, tzinfo=timezone.utc),
        source="git_log",
    )
    agg = _make_aggregator(
        [file],
        references=[ref],
        git_timestamps={"requirements/r1/doc.md": ts, "context/team/x.md": ts},
        now=now,
    )
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    json_str = renderer.render_json(summaries, [])
    data = json.loads(json_str)

    generated_at = data["generated_at"]
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    assert _re.match(iso_pattern, generated_at)
    assert generated_at == "2026-05-20T08:30:45Z"

    if data["files"]:
        f = data["files"][0]
        if f["last_referenced_at"] is not None:
            assert _re.match(iso_pattern, f["last_referenced_at"])


def test_renderer_json_none_datetime_becomes_null() -> None:
    """None datetime → JSON null。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/z.md")
    agg = _make_aggregator([file], references=[], now=now)
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    json_str = renderer.render_json(summaries, [])
    data = json.loads(json_str)

    f = data["files"][0]
    assert f["first_referenced_at"] is None
    assert f["last_referenced_at"] is None


def test_renderer_json_enum_serialization_to_value() -> None:
    """Enum → .value 字符串（如 "orphan" 而非 "KnowledgeStatus.ORPHAN"）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/orphan.md")
    agg = _make_aggregator([file], now=now)
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    json_str = renderer.render_json(summaries, [])
    data = json.loads(json_str)

    f = data["files"][0]
    assert f["status"] == "orphan"
    assert isinstance(f["status"], str)


def test_renderer_json_reference_evidences_nested_structure() -> None:
    """reference_evidences 嵌套 dict（target/source/line/kind/context_line）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/x.md")
    ref = _make_ref("context/team/x.md", source="requirements/r1/doc.md", line=42)
    agg = _make_aggregator([file], references=[ref], now=now)
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    json_str = renderer.render_json(summaries, [])
    data = json.loads(json_str)

    f = data["files"][0]
    assert "reference_evidences" in f
    if f["reference_evidences"]:
        ev = f["reference_evidences"][0]
        assert ev["target"] == "context/team/x.md"
        assert "source" in ev
        assert "line" in ev
        assert "kind" in ev
        assert "context_line" in ev


def test_renderer_json_applied_evidences_nested_reference() -> None:
    """applied_evidences 嵌套 reference dict（目标 ReferenceEvidence 的所有字段）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/x.md")
    refs = [
        _make_ref("context/team/x.md", source=f"requirements/r{i}/doc.md")
        for i in range(3)
    ]
    applied = [_make_applied(refs[0])]
    agg = _make_aggregator([file], references=refs, applied=applied, now=now)
    summaries = agg.aggregate()

    renderer = _make_renderer(now=now)
    json_str = renderer.render_json(summaries, [])
    data = json.loads(json_str)

    f = data["files"][0]
    if f["applied_evidences"]:
        app_ev = f["applied_evidences"][0]
        assert "reference" in app_ev
        ref = app_ev["reference"]
        assert "target" in ref
        assert "source" in ref
        assert "line" in ref


def test_renderer_write_creates_parent_dirs(tmp_path: Path) -> None:
    """write 自动创建 parent 目录。"""
    output_file = tmp_path / "deep" / "nested" / "report.md"
    assert not output_file.parent.exists()

    ReportRenderer.write("test content", output_file)

    assert output_file.parent.exists()
    assert output_file.exists()
    assert output_file.read_text(encoding="utf-8") == "test content"


def test_renderer_write_overwrites_existing_file(tmp_path: Path) -> None:
    """write 覆盖已有文件。"""
    output_file = tmp_path / "report.md"
    output_file.write_text("old content", encoding="utf-8")

    ReportRenderer.write("new content", output_file)

    assert output_file.read_text(encoding="utf-8") == "new content"


def test_renderer_write_atomic_tmp_pattern(tmp_path: Path) -> None:
    """write 使用 .tmp 中间文件，OSError 在 tmp 阶段抛，不污染目标文件。"""
    output_file = tmp_path / "report.md"
    output_file.write_text("precious", encoding="utf-8")

    with patch("os.replace", side_effect=OSError("Mock disk full")):
        with pytest.raises(OSError):
            ReportRenderer.write("new content", output_file)

    assert output_file.read_text(encoding="utf-8") == "precious"


def test_renderer_write_utf8_encoding(tmp_path: Path) -> None:
    """write 输出 UTF-8 编码，含中文字符。"""
    output_file = tmp_path / "report.md"
    content = "# 知识利用率\n这是中文内容"

    ReportRenderer.write(content, output_file)

    assert output_file.read_text(encoding="utf-8") == content


def test_renderer_write_tmp_path_suffix(tmp_path: Path) -> None:
    """write 的 tmp 文件后缀为 .md.tmp。"""
    output_file = tmp_path / "report.md"

    original_write = Path.write_text
    written_paths = []

    def mock_write(self, *args, **kwargs):
        written_paths.append(str(self))
        return original_write(self, *args, **kwargs)

    with patch.object(Path, "write_text", mock_write):
        ReportRenderer.write("content", output_file)

    assert any(".tmp" in p for p in written_paths)


# F-010-FU F-D 回归：render_markdown 应消费 warnings 参数（不是死参数）


def test_renderer_markdown_renders_warnings_when_non_empty() -> None:
    """warnings 非空时追加 ## Warnings 段，列出每条 warning。"""
    renderer = _make_renderer()
    md = renderer.render_markdown(
        [],
        [
            "git log 失败（CalledProcessError），回退 fs_mtime",
            "reviews/foo.json 解析失败，跳过：JSONDecodeError at line 12 col 5",
        ],
    )
    assert "## Warnings" in md
    assert "- git log 失败（CalledProcessError），回退 fs_mtime" in md
    assert "- reviews/foo.json 解析失败" in md


def test_renderer_markdown_empty_warnings_no_section() -> None:
    """warnings 空时不输出 ## Warnings 段，保持 4 章节结构不被空段污染。"""
    renderer = _make_renderer()
    md = renderer.render_markdown([], [])
    assert "## Warnings" not in md
