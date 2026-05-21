"""check_task_frontmatter.py 单测（F-003）。

覆盖：
  - TC-F3-1 case1: status=invalid_value（枚举越界）→ exit 1
  - TC-F3-1 case2: 缺 touches → exit 1
  - TC-F3-1 case3: 缺 status → exit 1
  - TS-001: data 缺 schema_version → exit 1，stderr 含 "schema_version 必填"
  - TS-002: data["schema_version"]="0.9"（不在 SUPPORTED）→ exit 1，stderr 含迁移脚本路径
  - TS-003: data["schema_version"]="1.0"（在 SUPPORTED）→ 走后续校验通过
  - TS-004: schema 文件自身 schema_version ≠ "1.0" → 抛 SchemaLoadError
  - TS-005: data["schema_version"]="1.0.0"（多余 patch 段）→ exit 1（format 拒绝）
  - 一条 happy path（合法 frontmatter → exit 0）

外部依赖（schema 文件、task.md 文件）通过 monkeypatch + tmp_path 隔离。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# ---------- 路径常量 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]

_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# ---------- 被测模块 ----------
import check_task_frontmatter as _ctf_mod  # noqa: E402


# ---------- 工具函数 ----------

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def _write_task_md(path: Path, frontmatter: dict) -> None:
    """把 frontmatter dict 写成 task.md（--- 块格式）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_text = yaml.safe_dump(frontmatter, allow_unicode=True, default_flow_style=False)
    content = f"---\n{fm_text}---\n\n# Task body\n"
    path.write_text(content, encoding="utf-8")


def _valid_frontmatter() -> dict:
    """返回一份合法的 task.md frontmatter（基线）。"""
    return {
        "schema_version": "1.0",
        "feature_id": "F-003",
        "title": "task-frontmatter-schema + check_task_frontmatter + GATE-TASK-FRONTMATTER",
        "status": "pending",
        "complexity": "medium",
        "depends_on": [],
        "touches": [
            "context/team/engineering-spec/task-frontmatter-schema.yaml",
            "scripts/lib/check_task_frontmatter.py",
        ],
        "created_at": "2026-05-06 10:00:00",
        "updated_at": "2026-05-06 10:00:00",
    }


def _valid_schema() -> dict:
    """返回合法的 task-frontmatter-schema.yaml 内容（L1 schema_version=1.0）。"""
    return {
        "schema_version": "1.0",
        "required_fields": [
            "schema_version",
            "feature_id",
            "title",
            "status",
            "complexity",
            "depends_on",
            "touches",
            "created_at",
            "updated_at",
        ],
        "format": {
            "schema_version": r"^\d+\.\d+$",
            "feature_id": r"^F-\d{3}$",
            "depends_on_item": r"^F-\d{3}$",
        },
        "enums": {
            "status": ["pending", "in-progress", "done"],
            "complexity": ["trivial", "light", "medium", "heavy"],
        },
    }


def _reload_with_schema(tmp_path: Path, schema_data: dict) -> Path:
    """把 schema 写到 tmp_path，返回 schema 文件路径（monkeypatch 用）。"""
    schema_file = tmp_path / "task-frontmatter-schema.yaml"
    _write_yaml(schema_file, schema_data)
    return schema_file


# ======================== TC-F3-1 case1: status=invalid_value → fail ========================

def test_tc_f3_1_case1_invalid_status_fails(tmp_path, monkeypatch):
    """TC-F3-1 case1：status=invalid_value（枚举越界）→ exit 1。

    status 枚举为 pending/in-progress/done，"invalid_value" 不在枚举内 → 报错。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    data["status"] = "invalid_value"

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors, "期望有 error（status=invalid_value）"
    errors_text = " ".join(report.errors)
    assert "status" in errors_text, f"错误消息应含 'status'，实际：{errors_text}"
    assert "invalid_value" in errors_text, f"错误消息应含 'invalid_value'，实际：{errors_text}"


# ======================== TC-F3-1 case2: 缺 touches → fail ========================

def test_tc_f3_1_case2_missing_touches_fails(tmp_path, monkeypatch):
    """TC-F3-1 case2：缺 touches 字段 → exit 1，错误消息含 "touches 必填"。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    del data["touches"]

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors, "期望有 error（缺 touches）"
    errors_text = " ".join(report.errors)
    assert "touches" in errors_text, f"错误消息应含 'touches'，实际：{errors_text}"
    assert "必填" in errors_text, f"错误消息应含 '必填'，实际：{errors_text}"


# ======================== TC-F3-1 case3: 缺 status → fail ========================

def test_tc_f3_1_case3_missing_status_fails(tmp_path, monkeypatch):
    """TC-F3-1 case3：缺 status 字段 → exit 1，错误消息含 "status 必填"。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    del data["status"]

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors, "期望有 error（缺 status）"
    errors_text = " ".join(report.errors)
    assert "status" in errors_text, f"错误消息应含 'status'，实际：{errors_text}"
    assert "必填" in errors_text, f"错误消息应含 '必填'，实际：{errors_text}"


# ======================== TS-001: data 缺 schema_version ========================

def test_ts001_missing_schema_version(tmp_path, monkeypatch):
    """TS-001：data 缺 schema_version → exit 1，stderr 含 'schema_version 必填'。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    del data["schema_version"]

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "schema_version" in errors_text and "必填" in errors_text, (
        f"错误消息应含 'schema_version 必填'，实际：{errors_text}"
    )


# ======================== TS-002: schema_version="0.9"（不在 SUPPORTED） ========================

def test_ts002_unsupported_schema_version(tmp_path, monkeypatch):
    """TS-002：data schema_version='0.9' 不在 SUPPORTED_VERSIONS → exit 1，stderr 含迁移脚本路径。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    data["schema_version"] = "0.9"

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "0.9" in errors_text, f"错误消息应含 '0.9'，实际：{errors_text}"
    assert "migrate_task_frontmatter" in errors_text, (
        f"错误消息应含迁移脚本路径 'migrate_task_frontmatter'，实际：{errors_text}"
    )


# ======================== TS-003: schema_version="1.0"（在 SUPPORTED） ========================

def test_ts003_supported_schema_version_passes(tmp_path, monkeypatch):
    """TS-003：data schema_version='1.0' 在 SUPPORTED → 走后续校验（正常通过）。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    data["schema_version"] = "1.0"

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert not report.has_errors, f"期望 0 error，实际：{report.errors}"


# ======================== TS-004: schema 文件自身 schema_version ≠ "1.0" → 抛 SchemaLoadError ========================

def test_ts004_schema_file_bad_version_raises_schema_load_error(tmp_path, monkeypatch):
    """TS-004：schema 文件 schema_version='2.0' → _load_schema() 抛 SchemaLoadError（schema 损坏）。"""
    bad_schema = _valid_schema()
    bad_schema["schema_version"] = "2.0"
    schema_file = tmp_path / "task-frontmatter-schema.yaml"
    _write_yaml(schema_file, bad_schema)

    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    with pytest.raises(_ctf_mod.SchemaLoadError) as exc_info:
        _ctf_mod._load_schema()
    assert "1.0" in str(exc_info.value) or "2.0" in str(exc_info.value), (
        f"SchemaLoadError 消息应含版本信息，实际：{exc_info.value}"
    )


# ======================== TS-005: schema_version="1.0.0"（多余 patch 段） ========================

def test_ts005_schema_version_with_patch_fails(tmp_path, monkeypatch):
    """TS-005：data schema_version='1.0.0' format 校验拒绝（不接受 patch 段）→ exit 1。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    data["schema_version"] = "1.0.0"

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors, "期望 format 校验拒绝 '1.0.0'"
    errors_text = " ".join(report.errors)
    assert "schema_version" in errors_text, (
        f"错误消息应含 'schema_version'，实际：{errors_text}"
    )


# ======================== happy path: 合法 frontmatter → exit 0 ========================

def test_valid_frontmatter_passes(tmp_path, monkeypatch):
    """given_valid_task_frontmatter_when_check_then_no_errors（happy path）。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert not report.has_errors, f"期望 0 error，实际：{report.errors}"


# ======================== 额外：complexity 枚举越界 → fail ========================

def test_invalid_complexity_fails(tmp_path, monkeypatch):
    """given_complexity_invalid_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    data["complexity"] = "low"  # 应为 trivial/light/medium/heavy

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "complexity" in errors_text
    assert "low" in errors_text


# ======================== 额外：feature_id 格式不对 → fail ========================

def test_invalid_feature_id_format_fails(tmp_path, monkeypatch):
    """given_feature_id_format_wrong_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    data["feature_id"] = "F-3"  # 应为 F-003

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "feature_id" in errors_text


# ======================== 额外：depends_on 元素格式不对 → fail ========================

def test_invalid_depends_on_item_fails(tmp_path, monkeypatch):
    """given_depends_on_item_format_wrong_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    data["depends_on"] = ["F-1"]  # 应为 F-001

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "depends_on" in errors_text


# ======================== 额外：_load_task_frontmatter 无 frontmatter → exit 1 ========================

def test_load_task_frontmatter_no_frontmatter_exits_1(tmp_path, monkeypatch):
    """given_task_md_without_frontmatter_when_load_then_exit_1。

    首行非 '---' 视为无 frontmatter，_load_task_frontmatter 应 sys.exit(1)。
    """
    task_file = tmp_path / "F-003.md"
    task_file.write_text("# No frontmatter here\n", encoding="utf-8")

    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", _reload_with_schema(tmp_path, _valid_schema()))

    with pytest.raises(SystemExit) as exc_info:
        _ctf_mod._load_task_frontmatter(task_file)
    assert exc_info.value.code == 1


# ======================== 额外：touches 不是列表 → fail ========================

def test_touches_not_list_fails(tmp_path, monkeypatch):
    """given_touches_is_string_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    data["touches"] = "scripts/lib/check_task_frontmatter.py"  # 应为列表

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "touches" in errors_text


# ======================== 额外：缺多个字段（累积错误） ========================

def test_missing_multiple_fields_accumulates_errors(tmp_path, monkeypatch):
    """given_multiple_required_fields_missing_when_check_then_all_reported。

    验证累积错误模式：不 fail-fast，全部必填缺失都报出来。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_ctf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_frontmatter()
    del data["title"]
    del data["created_at"]
    del data["updated_at"]

    report = _ctf_mod.validate(data, _valid_schema(), "test_task.md")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "title" in errors_text
    assert "created_at" in errors_text
    assert "updated_at" in errors_text
    assert len(report.errors) >= 3, f"期望至少 3 条错误，实际：{len(report.errors)}"


# ---------- 双模 CLI（Bug-10）：目录 vs 单文件 ----------


def test_cli_accepts_directory(tmp_path):
    """传入目录 → rglob *.md 批量校验，全 valid → exit 0"""
    import subprocess, sys, textwrap
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "scripts" / "lib" / "check_task_frontmatter.py"
    for n in (1, 2, 3):
        (tmp_path / f"F-00{n}.md").write_text(textwrap.dedent(f"""
            ---
            schema_version: "1.0"
            feature_id: F-00{n}
            title: t
            status: pending
            complexity: light
            depends_on: []
            touches: ["scripts/lib/x.py"]
            created_at: 2026-05-21T15:00:00
            updated_at: 2026-05-21T15:00:00
            ---
            body
        """).lstrip(), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(cli), str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_cli_directory_aggregates_failures(tmp_path):
    """目录内含一个非法文件 → 聚合 exit 1"""
    import subprocess, sys, textwrap
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "scripts" / "lib" / "check_task_frontmatter.py"
    (tmp_path / "F-001.md").write_text(textwrap.dedent("""
        ---
        schema_version: "1.0"
        feature_id: F-001
        title: t
        status: pending
        complexity: light
        depends_on: []
        touches: ["scripts/lib/x.py"]
        created_at: 2026-05-21T15:00:00
        updated_at: 2026-05-21T15:00:00
        ---
    """).lstrip(), encoding="utf-8")
    (tmp_path / "F-002.md").write_text("---\nfeature_id: not_valid\n---\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(cli), str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode == 1


def test_cli_empty_directory(tmp_path):
    """目录无 *.md → exit 0（带 warning stderr）"""
    import subprocess, sys
    repo_root = Path(__file__).resolve().parents[2]
    cli = repo_root / "scripts" / "lib" / "check_task_frontmatter.py"
    proc = subprocess.run([sys.executable, str(cli), str(tmp_path)], capture_output=True, text=True)
    assert proc.returncode == 0
