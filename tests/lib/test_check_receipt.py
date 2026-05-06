"""check_receipt.py 单测（F-001）。

覆盖：
  - TC-F1-1 case1: schema_version=1.0 + 字段全合规 → exit 0（pass fixture）
  - TC-F1-1 case2: 缺 required field → exit 1，stderr 含字段名（fail fixture）
  - TC-F1-1 case3: status enum 越界（如 "FAILED"）→ exit 1（fail fixture）
  - TS-001: data 缺 schema_version → exit 1，stderr 含 "schema_version 必填"
  - TS-002: data["schema_version"] = "0.9"（不在 SUPPORTED）→ exit 1，stderr 含迁移脚本路径
  - TS-003: data["schema_version"] = "1.0"（在 SUPPORTED）→ 走后续校验（正常通过）
  - TS-004: schema 文件自身 schema_version ≠ "1.0" → exit 2（schema 损坏）
  - TS-005: data["schema_version"] = "1.0.0"（多余 patch 段）→ exit 1（format 校验拒绝）

外部依赖（schema 文件）通过 monkeypatch + tmp_path 隔离。
共用 fixtures 落 tests/lib/fixtures/receipt/（detailed-design.md §4.5 末尾约定）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

# ---------- 路径常量 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHECK_RECEIPT = _REPO_ROOT / "scripts" / "lib" / "check_receipt.py"

# 注入 scripts/lib 到 sys.path（与其他 tests/lib/ 下的测试一致）
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# ---------- 工具函数 ----------


def _write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def _valid_receipt() -> dict:
    """返回一份合法的 receipt.json 数据（基线）。"""
    return {
        "schema_version": "1.0",
        "feature_id": "F-001",
        "status": "DONE",
        "commit_sha": "abc1234",
        "files_changed": ["scripts/lib/check_receipt.py"],
        "test_summary": "pytest tests/ 全绿，共 10 个用例",
        "touches_violations": [],
        "concerns": [],
        "missing_context": "",
        "block_reason": "",
        "timestamp": "2026-05-01T12:00:00+08:00",
    }


def _valid_schema() -> dict:
    """返回合法的 receipt-schema.yaml 内容（L1 schema_version=1.0）。"""
    return {
        "schema_version": "1.0",
        "required_fields": [
            "schema_version", "feature_id", "status", "commit_sha",
            "files_changed", "test_summary", "touches_violations",
            "concerns", "missing_context", "block_reason", "timestamp",
        ],
        "enums": {
            "status": ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"],
        },
        "format": {
            "schema_version": r"^\d+\.\d+$",
            "feature_id": r"^F-\d{3}$",
            "timestamp": "iso8601",
            "commit_sha": r"^([0-9a-f]{7,40}|HEAD)$",
        },
        "conditional_required": [
            {"when": {"status": "DONE_WITH_CONCERNS"}, "non_empty": ["concerns"]},
            {"when": {"status": "NEEDS_CONTEXT"}, "non_empty": ["missing_context"]},
            {"when": {"status": "BLOCKED"}, "non_empty": ["block_reason"]},
        ],
    }


# ---------- 导入被测模块（设置 SCHEMA_PATH 前先 import，再 monkeypatch） ----------
import check_receipt as _cr_mod  # noqa: E402（conftest.py 已注入 sys.path）


def _reload_with_schema(tmp_path: Path, schema_data: dict) -> Path:
    """把 schema 写到 tmp_path，返回 schema 文件路径（monkeypatch 用）。"""
    schema_file = tmp_path / "receipt-schema.yaml"
    _write_yaml(schema_file, schema_data)
    return schema_file


# ======================== TC-F1-1 case1 pass fixture ========================

def test_valid_receipt_passes(tmp_path, monkeypatch):
    """given_valid_receipt_when_check_then_exit_0（pass fixture）。

    详细设计 §4.5 TC-F1-1 case1。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    receipt_file = tmp_path / "F-001.receipt.json"
    _write_json(receipt_file, _valid_receipt())

    report = _cr_mod.validate(_valid_receipt(), _valid_schema(), str(receipt_file))
    assert not report.has_errors, f"期望 0 error，实际错误：{report._errors}"


# ======================== TC-F1-1 case2 fail：缺 required field ========================

def test_missing_required_field_fails(tmp_path, monkeypatch):
    """given_receipt_missing_required_field_when_check_then_exit_1_and_stderr_contains_field_name。

    详细设计 §4.5 TC-F1-1 case2。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    del data["commit_sha"]  # 故意删去必填字段

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert report.has_errors, "期望有 error"
    # 错误消息必须包含字段名
    errors_text = " ".join(report._errors)
    assert "commit_sha" in errors_text, f"stderr 应含 'commit_sha'，实际：{errors_text}"


# ======================== TC-F1-1 case3 fail：status enum 越界 ========================

def test_invalid_status_enum_fails(tmp_path, monkeypatch):
    """given_receipt_status_invalid_enum_when_check_then_exit_1。

    详细设计 §4.5 TC-F1-1 case3。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    data["status"] = "FAILED"  # 不在枚举内

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert report.has_errors, "期望有 error"
    errors_text = " ".join(report._errors)
    assert "status" in errors_text, f"stderr 应含 'status'，实际：{errors_text}"
    assert "FAILED" in errors_text, f"stderr 应含 'FAILED'，实际：{errors_text}"


# ======================== TS-001: data 缺 schema_version ========================

def test_ts001_missing_schema_version(tmp_path, monkeypatch):
    """TS-001：data 缺 schema_version → exit 1，stderr 含 'schema_version 必填'。

    详细设计 §4.5 TS-001。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    del data["schema_version"]

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert report.has_errors
    errors_text = " ".join(report._errors)
    assert "schema_version" in errors_text and "必填" in errors_text, (
        f"stderr 应含 'schema_version 必填'，实际：{errors_text}"
    )


# ======================== TS-002: schema_version = "0.9"（不在 SUPPORTED） ========================

def test_ts002_unsupported_schema_version(tmp_path, monkeypatch):
    """TS-002：data schema_version='0.9' 不在 SUPPORTED_VERSIONS → exit 1，stderr 含迁移脚本路径。

    详细设计 §4.5 TS-002。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    data["schema_version"] = "0.9"

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert report.has_errors
    errors_text = " ".join(report._errors)
    assert "0.9" in errors_text, f"stderr 应含 '0.9'，实际：{errors_text}"
    # 迁移脚本路径占位必须在错误消息里
    assert "migrate_receipt" in errors_text, (
        f"stderr 应含迁移脚本路径占位 'migrate_receipt'，实际：{errors_text}"
    )


# ======================== TS-003: schema_version = "1.0"（在 SUPPORTED） ========================

def test_ts003_supported_schema_version_passes(tmp_path, monkeypatch):
    """TS-003：data schema_version='1.0' 在 SUPPORTED → 走后续校验（正常通过）。

    详细设计 §4.5 TS-003。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    data["schema_version"] = "1.0"  # 明确在 SUPPORTED_VERSIONS 内

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert not report.has_errors, f"期望 0 error，实际：{report._errors}"


# ======================== TS-004: schema 文件自身 schema_version ≠ "1.0" → exit 2 ========================

def test_ts004_schema_file_bad_version_raises_schema_load_error(tmp_path, monkeypatch):
    """TS-004：schema 文件 schema_version='2.0' → _load_schema() 抛 SchemaLoadError（schema 损坏）。

    详细设计 §4.5 TS-004。
    F-11 修复后：_load_schema() 是库函数，失败时抛 SchemaLoadError 而非 sys.exit(2)；
    CLI main() 负责捕获并 exit 2。
    """
    bad_schema = _valid_schema()
    bad_schema["schema_version"] = "2.0"
    schema_file = tmp_path / "receipt-schema.yaml"
    _write_yaml(schema_file, bad_schema)

    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    with pytest.raises(_cr_mod.SchemaLoadError) as exc_info:
        _cr_mod._load_schema()
    assert "1.0" in str(exc_info.value) or "2.0" in str(exc_info.value), (
        f"SchemaLoadError 消息应含版本信息，实际：{exc_info.value}"
    )


# ======================== TS-005: schema_version = "1.0.0"（多余 patch 段） ========================

def test_ts005_schema_version_with_patch_fails(tmp_path, monkeypatch):
    """TS-005：data schema_version='1.0.0' format 校验拒绝（不接受 patch 段）→ exit 1。

    详细设计 §4.5 TS-005。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    data["schema_version"] = "1.0.0"  # 多余 patch 段，format regex 拒绝

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert report.has_errors, "期望 format 校验拒绝 '1.0.0'"
    errors_text = " ".join(report._errors)
    assert "schema_version" in errors_text, (
        f"stderr 应含 'schema_version'，实际：{errors_text}"
    )


# ======================== 额外：conditional 规则覆盖 ========================

def test_done_with_concerns_requires_nonempty_concerns(tmp_path, monkeypatch):
    """given_status_DONE_WITH_CONCERNS_and_empty_concerns_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    data["status"] = "DONE_WITH_CONCERNS"
    data["concerns"] = []  # 空列表，但 DONE_WITH_CONCERNS 时必须非空

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert report.has_errors
    errors_text = " ".join(report._errors)
    assert "concerns" in errors_text


def test_done_status_with_nonempty_concerns_fails(tmp_path, monkeypatch):
    """given_status_DONE_and_nonempty_concerns_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    data["status"] = "DONE"
    data["concerns"] = ["有一个小疑虑"]  # DONE 时 concerns 必须是 []

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert report.has_errors
    errors_text = " ".join(report._errors)
    assert "concerns" in errors_text


def test_needs_context_requires_missing_context(tmp_path, monkeypatch):
    """given_status_NEEDS_CONTEXT_and_empty_missing_context_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cr_mod, "SCHEMA_PATH", schema_file)

    data = _valid_receipt()
    data["status"] = "NEEDS_CONTEXT"
    data["missing_context"] = ""  # 空字符串，但 NEEDS_CONTEXT 时必须非空

    report = _cr_mod.validate(data, _valid_schema(), "test_receipt.json")
    assert report.has_errors
    errors_text = " ".join(report._errors)
    assert "missing_context" in errors_text
