"""tests for EvidenceScanner（F-006 验收测试）。

覆盖 F-006.md §验收标准：

  AC-1: ReferenceEvidence 含 target/source/line/kind/context_line 完整 5 字段
  AC-2: 4 种引用形式（markdown_link / raw_path / source_marker / json_value）各至少 1 用例
  AC-3: JSON 解析失败 fail-open（warnings 非空，scan 不抛）
  AC-4: 非 candidate 路径被过滤，不出现在结果中
  AC-5: code block 内伪引用不计入（mask_code_blocks 前置）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from context_usage_report import EvidenceScanner, ReferenceEvidence  # noqa: E402


# ---------------------------------------------------------------------------
# 辅助：建 fake repo 结构
# ---------------------------------------------------------------------------

def _make_fake_repo(tmp_path: Path) -> tuple[Path, Path, set[str]]:
    """造最小 fake repo：context/ 目录 + requirements/ 目录。

    Returns:
        (repo_root, requirements_dir, context_files)
    """
    repo_root = tmp_path

    # context 文件
    ctx = repo_root / "context" / "team"
    ctx.mkdir(parents=True)
    (ctx / "foo.md").write_text("# foo\n", encoding="utf-8")
    (ctx / "bar.md").write_text("# bar\n", encoding="utf-8")

    ctx_proj = repo_root / "context" / "project" / "myproj"
    ctx_proj.mkdir(parents=True)
    (ctx_proj / "spec.md").write_text("# spec\n", encoding="utf-8")

    context_files: set[str] = {
        "context/team/foo.md",
        "context/team/bar.md",
        "context/project/myproj/spec.md",
    }

    # requirements 目录（空，测试按需填充）
    req_dir = repo_root / "requirements"
    req_dir.mkdir(parents=True)

    return repo_root, req_dir, context_files


# ---------------------------------------------------------------------------
# AC-1 · ReferenceEvidence 5 字段完整
# ---------------------------------------------------------------------------


def test_reference_evidence_fields_complete(tmp_path: Path) -> None:
    """scan 返回的 ReferenceEvidence 含全部 5 字段且类型正确。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "req-001"
    doc.mkdir(parents=True)
    (doc / "requirement.md").write_text(
        "参见 [foo](context/team/foo.md)\n",
        encoding="utf-8",
    )

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    assert len(results) >= 1
    ev = results[0]
    assert isinstance(ev, ReferenceEvidence)
    assert isinstance(ev.target, str) and ev.target.startswith("context/")
    assert isinstance(ev.source, str) and ev.source.startswith("requirements/")
    assert isinstance(ev.line, int) and ev.line >= 1
    assert ev.kind in ("markdown_link", "raw_path", "source_marker", "json_value")
    assert isinstance(ev.context_line, str)


# ---------------------------------------------------------------------------
# AC-2a · markdown_link 引用形式
# ---------------------------------------------------------------------------


def test_markdown_link_kind(tmp_path: Path) -> None:
    """[text](context/team/foo.md) 形式识别为 markdown_link。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r001" / "notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "Line 1\n"
        "参见 [foo文档](context/team/foo.md)\n"
        "Line 3\n",
        encoding="utf-8",
    )

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    md_links = [ev for ev in results if ev.kind == "markdown_link"]
    assert len(md_links) >= 1, "应识别到 markdown_link"
    ev = md_links[0]
    assert ev.target == "context/team/foo.md"
    assert ev.line == 2
    assert "foo文档" in ev.context_line


# ---------------------------------------------------------------------------
# AC-2b · raw_path 引用形式
# ---------------------------------------------------------------------------


def test_raw_path_kind(tmp_path: Path) -> None:
    """行内裸路径 context/team/bar.md 识别为 raw_path。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r002" / "notes.md"
    doc.parent.mkdir(parents=True)
    # 用裸路径，不加方括号
    doc.write_text(
        "请参考文档 context/team/bar.md 了解详情。\n",
        encoding="utf-8",
    )

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    raw_paths = [ev for ev in results if ev.kind == "raw_path"]
    assert len(raw_paths) >= 1, "应识别到 raw_path"
    ev = raw_paths[0]
    assert ev.target == "context/team/bar.md"
    assert ev.line == 1


# ---------------------------------------------------------------------------
# AC-2c · source_marker 引用形式
# ---------------------------------------------------------------------------


def test_source_marker_kind(tmp_path: Path) -> None:
    """来源：context/team/foo.md:42 形式识别为 source_marker。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r003" / "artifact.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "这是一条结论。（来源：context/team/foo.md:42）\n",
        encoding="utf-8",
    )

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    markers = [ev for ev in results if ev.kind == "source_marker"]
    assert len(markers) >= 1, "应识别到 source_marker"
    ev = markers[0]
    assert ev.target == "context/team/foo.md"  # :42 后缀已剥
    assert ev.line == 1


# ---------------------------------------------------------------------------
# AC-2d · json_value 引用形式
# ---------------------------------------------------------------------------


def test_json_value_kind(tmp_path: Path) -> None:
    """JSON 字段值中的 context 路径识别为 json_value。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r004" / "meta.json"
    doc.parent.mkdir(parents=True)
    data = {
        "id": "r004",
        "references": ["context/team/foo.md", "https://example.com"],
        "nested": {"key": "context/project/myproj/spec.md"},
    }
    doc.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    json_vals = [ev for ev in results if ev.kind == "json_value"]
    targets = {ev.target for ev in json_vals}
    assert "context/team/foo.md" in targets, "JSON 数组中的路径应被识别"
    assert "context/project/myproj/spec.md" in targets, "JSON 嵌套对象中的路径应被识别"


# ---------------------------------------------------------------------------
# AC-3 · JSON 解析失败 fail-open
# ---------------------------------------------------------------------------


def test_json_parse_failure_fail_open(tmp_path: Path) -> None:
    """JSON 损坏时 scan 不抛异常；warnings 追加一条告警。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    bad_json = req_dir / "r005" / "broken.json"
    bad_json.parent.mkdir(parents=True)
    bad_json.write_text("{invalid json content!!!\n", encoding="utf-8")

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    # scan 不应抛
    results = scanner.scan()

    assert isinstance(results, list)  # 正常返回列表（可能为空）
    assert len(scanner.warnings) >= 1, "应追加至少一条 warning"
    assert any("broken.json" in w or "JSON" in w for w in scanner.warnings)


# ---------------------------------------------------------------------------
# AC-4 · 非 candidate 路径被过滤
# ---------------------------------------------------------------------------


def test_non_candidate_path_filtered(tmp_path: Path) -> None:
    """文档里引用了不在 context_files 集合中的路径，不应出现在结果中。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r006" / "notes.md"
    doc.parent.mkdir(parents=True)
    # context/team/unknown.md 不在 context_files 中
    doc.write_text(
        "参见 [unknown](context/team/unknown.md)\n"
        "参见 [foo](context/team/foo.md)\n",
        encoding="utf-8",
    )

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    targets = {ev.target for ev in results}
    assert "context/team/unknown.md" not in targets, "非 candidate 路径不应出现"
    assert "context/team/foo.md" in targets, "candidate 路径仍应出现"


# ---------------------------------------------------------------------------
# AC-5 · code block 内伪引用不计入
# ---------------------------------------------------------------------------


def test_code_block_pseudo_reference_excluded(tmp_path: Path) -> None:
    """fenced code block 内的 context 路径不应被计入（mask_code_blocks 前置）。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r007" / "notes.md"
    doc.parent.mkdir(parents=True)
    # code block 内的路径是伪引用，不应被扫描
    doc.write_text(
        "正文不含引用。\n"
        "```\n"
        "context/team/foo.md\n"
        "```\n"
        "正文结尾。\n",
        encoding="utf-8",
    )

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    assert len(results) == 0, (
        f"code block 内路径不应被计入，实际结果：{results}"
    )


# ---------------------------------------------------------------------------
# 同行去重策略：同行 markdown_link 优先于 raw_path
# ---------------------------------------------------------------------------


def test_same_line_dedup_prefers_markdown_link(tmp_path: Path) -> None:
    """同一行同一目标：markdown_link 优先级高于 raw_path，结果只保留一条。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r008" / "notes.md"
    doc.parent.mkdir(parents=True)
    # 这行既是 markdown_link 形式，也可被 raw_path 正则匹配
    doc.write_text(
        "参见 [foo](context/team/foo.md) 的描述。\n",
        encoding="utf-8",
    )

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    # 同行同 target 最多一条
    line1_results = [ev for ev in results if ev.line == 1 and ev.target == "context/team/foo.md"]
    assert len(line1_results) == 1, f"同行同 target 应去重为 1 条，实际：{line1_results}"
    assert line1_results[0].kind == "markdown_link", "markdown_link 优先级更高应被保留"


# ---------------------------------------------------------------------------
# 多文件扫描：.txt 和 .yaml 也应被扫描
# ---------------------------------------------------------------------------


def test_txt_and_yaml_files_scanned(tmp_path: Path) -> None:
    """.txt 和 .yaml 文件也参与文本扫描，裸路径应被识别。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    txt_file = req_dir / "r009" / "notes.txt"
    txt_file.parent.mkdir(parents=True)
    txt_file.write_text(
        "参考 context/team/bar.md 了解配置。\n",
        encoding="utf-8",
    )

    yaml_file = req_dir / "r009" / "meta.yaml"
    yaml_file.write_text(
        "references:\n"
        "  - context/team/foo.md\n",
        encoding="utf-8",
    )

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    targets = {ev.target for ev in results}
    assert "context/team/bar.md" in targets, ".txt 中的裸路径应被识别"
    assert "context/team/foo.md" in targets, ".yaml 中的裸路径应被识别"


# ---------------------------------------------------------------------------
# AC-3 补充 · fail-open 覆盖：文本文件 PermissionError
# ---------------------------------------------------------------------------


def test_text_scan_permission_error_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """文本文件读权限拒绝时，warnings 累一条 + scan 不抛。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r010" / "notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("参考 context/team/foo.md\n", encoding="utf-8")

    original_read_text = Path.read_text

    def _patched_read_text(self: Path, *args, **kwargs):  # type: ignore[override]
        if self == doc:
            raise PermissionError("Permission denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    assert isinstance(results, list), "scan() 不应抛异常"
    assert len(scanner.warnings) >= 1, "应追加至少一条 warning"
    assert any("notes.md" in w or "不可读" in w for w in scanner.warnings), (
        f"warning 应提及不可读文件，实际：{scanner.warnings}"
    )
    # 该文件内容不应出现在结果中
    sources = {ev.source for ev in results}
    assert not any("r010" in s for s in sources), "PermissionError 的文件不应出现在结果中"


# ---------------------------------------------------------------------------
# AC-3 补充 · fail-open 覆盖：resolve() 越界 repo_root（路径穿越）
# ---------------------------------------------------------------------------


def test_resolve_path_traversal_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve() 越界 repo_root 时跳过并累 warnings，scan 不抛。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    doc = req_dir / "r011" / "notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("参考 context/team/foo.md\n", encoding="utf-8")

    # 构造越界路径：在 repo_root 之外
    outside_path = tmp_path.parent / "outside_file.md"
    original_resolve = Path.resolve

    def _patched_resolve(self: Path, *args, **kwargs):  # type: ignore[override]
        resolved = original_resolve(self, *args, **kwargs)
        # 只对目标文档模拟越界
        if self == doc:
            return outside_path
        return resolved

    monkeypatch.setattr(Path, "resolve", _patched_resolve)

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    assert isinstance(results, list), "scan() 不应抛异常"
    assert len(scanner.warnings) >= 1, "越界应追加至少一条 warning"
    assert any("越界" in w or "repo_root" in w.lower() for w in scanner.warnings), (
        f"warning 应提及越界，实际：{scanner.warnings}"
    )
    sources = {ev.source for ev in results}
    assert not any("r011" in s for s in sources), "越界文件不应出现在结果中"


# ---------------------------------------------------------------------------
# AC-3 补充 · fail-open 覆盖：JSON 嵌套过深 RecursionError
# ---------------------------------------------------------------------------


def test_json_recursion_depth_fail_open(tmp_path: Path) -> None:
    """JSON 嵌套过深时 RecursionError fail-open：warnings 累一条，scan 不抛。"""
    repo_root, req_dir, context_files = _make_fake_repo(tmp_path)

    # 构造深度 2000 的嵌套 JSON（远超默认递归限制 ~1000）
    depth = 2000
    deep_json = '{"a":' * depth + '"x"' + "}" * depth

    doc = req_dir / "r012" / "deep.json"
    doc.parent.mkdir(parents=True)
    doc.write_text(deep_json, encoding="utf-8")

    scanner = EvidenceScanner(req_dir, context_files, repo_root)
    results = scanner.scan()

    assert isinstance(results, list), "scan() 不应抛 RecursionError"
    assert len(scanner.warnings) >= 1, "嵌套过深应追加至少一条 warning"
    assert any("嵌套过深" in w for w in scanner.warnings), (
        f"warning 应含'嵌套过深'，实际：{scanner.warnings}"
    )
