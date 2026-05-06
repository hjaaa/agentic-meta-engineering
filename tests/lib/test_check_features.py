"""check_features.py 单测（F-002）。

覆盖：
  - TC-F2-1 case1: status 不在 schema required_fields → features.json 含 status 字段也不报 status 越界
  - TC-F2-1 case2: complexity=giant → exit 1，stderr 含 "complexity 值 'giant' 不在 enum"
  - TC-F2-1 case3: features[2] 缺 title → exit 1，stderr 含 "features[2].title 必填"
  - TS-001: data 缺 schema_version → exit 1，stderr 含 "schema_version 必填"
  - TS-002: data["schema_version"] = "0.9"（不在 SUPPORTED）→ exit 1，stderr 含迁移脚本路径
  - TS-003: data["schema_version"] = "1.0"（在 SUPPORTED）→ 走后续校验（正常通过）
  - TS-004: schema 文件自身 schema_version ≠ "1.0" → 抛 SchemaLoadError（schema 损坏）
  - TS-005: data["schema_version"] = "1.0.0"（多余 patch 段）→ exit 1（format 校验拒绝）

外部依赖（schema 文件）通过 monkeypatch + tmp_path 隔离。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

# ---------- 路径常量 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 注入 scripts/lib 到 sys.path（与其他 tests/lib/ 下的测试一致）
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# ---------- 工具函数 ----------


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)


def _valid_feature(fid: str = "F-001", complexity: str = "medium") -> dict:
    """返回一条合法的 feature 数据（基线）。"""
    return {
        "id": fid,
        "title": f"Feature {fid} 标题",
        "description": f"Feature {fid} 描述，说明功能范围和目标",
        "modules": ["scripts/lib"],
        "depends_on": [],
        "depends_on_features": [],
        "complexity": complexity,
        "touches": [f"scripts/lib/check_{fid.lower()}.py"],
        "acceptance": ["单测全绿", "gate 校验通过"],
    }


def _valid_features_data(num_features: int = 2) -> dict:
    """返回合法的 features.json 数据（基线）。"""
    return {
        "schema_version": "1.0",
        "requirement_id": "REQ-2026-008",
        "features": [_valid_feature(f"F-{i+1:03d}") for i in range(num_features)],
    }


def _valid_schema() -> dict:
    """返回合法的 features-schema.yaml 内容（L1 schema_version=1.0）。"""
    return {
        "schema_version": "1.0",
        "required_fields": [
            "schema_version",
            "requirement_id",
            "features",
        ],
        "format": {
            "schema_version": r"^\d+\.\d+$",
            "requirement_id": r"^REQ-\d{4}-\d{3}$",
        },
        "feature_required_fields": [
            "id",
            "title",
            "description",
            "modules",
            "depends_on",
            "depends_on_features",
            "complexity",
            "touches",
            "acceptance",
        ],
        "feature_format": {
            "id": r"^F-\d{3}$",
            "depends_on_features_item": r"^F-\d{3}$",
        },
        "enums": {
            "complexity": ["trivial", "light", "medium", "heavy"],
        },
        "optional_feature_fields": ["estimate_days", "interfaces_frozen"],
    }


# ---------- 导入被测模块 ----------
import check_features as _cf_mod  # noqa: E402  # conftest.py 已注入 sys.path


def _reload_with_schema(tmp_path: Path, schema_data: dict) -> Path:
    """把 schema 写到 tmp_path，返回 schema 文件路径（monkeypatch 用）。"""
    schema_file = tmp_path / "features-schema.yaml"
    _write_yaml(schema_file, schema_data)
    return schema_file


# ======================== TC-F2-1 case1: status 不在 schema → 不报 status 越界 ========================

def test_status_field_not_in_schema_no_error(tmp_path, monkeypatch):
    """given_features_json_with_status_field_when_check_then_no_status_error（TC-F2-1 case1）。

    status 不在 features-schema.yaml required_fields / enums 内，
    即使 features.json 含 status 字段，也不应报 status 相关错误。
    验证：包含 status 字段的合法 features.json → 校验通过（exit 0）。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(2)
    # 给每个 feature 加 status 字段（模拟旧版本数据混入）
    for f in data["features"]:
        f["status"] = "pending"

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert not report.has_errors, (
        f"status 字段不在 schema，不应报错。实际错误：{report.errors}"
    )


# ======================== TC-F2-1 case2: complexity=giant → fail ========================

def test_complexity_giant_fails(tmp_path, monkeypatch):
    """given_complexity_giant_when_check_then_exit_1_complexity_enum_error（TC-F2-1 case2）。

    complexity 枚举为 trivial/light/medium/heavy，"giant" 不在枚举内 → 报错。
    错误消息必须含 "complexity 值 'giant' 不在 enum"。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    data["features"][0]["complexity"] = "giant"

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors, "期望有 error（complexity=giant）"
    errors_text = " ".join(report.errors)
    assert "complexity" in errors_text, f"错误消息应含 'complexity'，实际：{errors_text}"
    assert "giant" in errors_text, f"错误消息应含 'giant'，实际：{errors_text}"
    # 错误消息应含 "不在 enum" 或 "枚举" 字样
    assert "enum" in errors_text or "枚举" in errors_text, (
        f"错误消息应含 enum/枚举，实际：{errors_text}"
    )


# ======================== TC-F2-1 case3: features[2] 缺 title → fail ========================

def test_feature_missing_title_at_index_two_fails(tmp_path, monkeypatch):
    """given_features_index_2_missing_title_when_check_then_exit_1_features_2_title_error（TC-F2-1 case3）。

    features[2]（第 3 条）缺少 title 字段 → 报错。
    错误消息必须含 "features[2].title 必填"。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(3)
    del data["features"][2]["title"]  # 故意删去 index=2 的 title

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors, "期望有 error（features[2] 缺 title）"
    errors_text = " ".join(report.errors)
    assert "features[2]" in errors_text, f"错误消息应含 'features[2]'，实际：{errors_text}"
    assert "title" in errors_text, f"错误消息应含 'title'，实际：{errors_text}"
    assert "必填" in errors_text, f"错误消息应含 '必填'，实际：{errors_text}"


# ======================== TS-001: data 缺 schema_version ========================

def test_ts001_missing_schema_version(tmp_path, monkeypatch):
    """TS-001：data 缺 schema_version → exit 1，stderr 含 'schema_version 必填'。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    del data["schema_version"]

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "schema_version" in errors_text and "必填" in errors_text, (
        f"stderr 应含 'schema_version 必填'，实际：{errors_text}"
    )


# ======================== TS-002: schema_version = "0.9"（不在 SUPPORTED） ========================

def test_ts002_unsupported_schema_version(tmp_path, monkeypatch):
    """TS-002：data schema_version='0.9' 不在 SUPPORTED_VERSIONS → exit 1，stderr 含迁移脚本路径。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    data["schema_version"] = "0.9"

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "0.9" in errors_text, f"stderr 应含 '0.9'，实际：{errors_text}"
    assert "migrate_features" in errors_text, (
        f"stderr 应含迁移脚本路径占位 'migrate_features'，实际：{errors_text}"
    )


# ======================== TS-003: schema_version = "1.0"（在 SUPPORTED） ========================

def test_ts003_supported_schema_version_passes(tmp_path, monkeypatch):
    """TS-003：data schema_version='1.0' 在 SUPPORTED → 走后续校验（正常通过）。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    data["schema_version"] = "1.0"

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert not report.has_errors, f"期望 0 error，实际：{report.errors}"


# ======================== TS-004: schema 文件自身 schema_version ≠ "1.0" → 抛 SchemaLoadError ========================

def test_ts004_schema_file_bad_version_raises_schema_load_error(tmp_path, monkeypatch):
    """TS-004：schema 文件 schema_version='2.0' → _load_schema() 抛 SchemaLoadError（schema 损坏）。"""
    bad_schema = _valid_schema()
    bad_schema["schema_version"] = "2.0"
    schema_file = tmp_path / "features-schema.yaml"
    _write_yaml(schema_file, bad_schema)

    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    with pytest.raises(_cf_mod.SchemaLoadError) as exc_info:
        _cf_mod._load_schema()
    assert "1.0" in str(exc_info.value) or "2.0" in str(exc_info.value), (
        f"SchemaLoadError 消息应含版本信息，实际：{exc_info.value}"
    )


# ======================== TS-005: schema_version = "1.0.0"（多余 patch 段） ========================

def test_ts005_schema_version_with_patch_fails(tmp_path, monkeypatch):
    """TS-005：data schema_version='1.0.0' format 校验拒绝（不接受 patch 段）→ exit 1。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    data["schema_version"] = "1.0.0"

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors, "期望 format 校验拒绝 '1.0.0'"
    errors_text = " ".join(report.errors)
    assert "schema_version" in errors_text, (
        f"stderr 应含 'schema_version'，实际：{errors_text}"
    )


# ======================== 额外：合法 features.json 全字段通过 ========================

def test_valid_features_data_passes(tmp_path, monkeypatch):
    """given_valid_features_data_when_check_then_no_errors（pass fixture）。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(3)
    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert not report.has_errors, f"期望 0 error，实际：{report.errors}"


# ======================== 额外：缺 requirement_id → fail ========================

def test_missing_requirement_id_fails(tmp_path, monkeypatch):
    """given_features_missing_requirement_id_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    del data["requirement_id"]

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "requirement_id" in errors_text


# ======================== 额外：requirement_id 格式不对 → fail ========================

def test_invalid_requirement_id_format_fails(tmp_path, monkeypatch):
    """given_invalid_requirement_id_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    data["requirement_id"] = "REQ-2026-8"  # 应为 REQ-2026-008

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "requirement_id" in errors_text


# ======================== 额外：feature id 格式不对 → fail ========================

def test_invalid_feature_id_format_fails(tmp_path, monkeypatch):
    """given_feature_id_format_wrong_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    data["features"][0]["id"] = "F-1"  # 应为 F-001

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "id" in errors_text


# ======================== 额外：depends_on_features 元素格式不对 → fail ========================

def test_invalid_depends_on_features_item_fails(tmp_path, monkeypatch):
    """given_depends_on_features_item_format_wrong_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(2)
    data["features"][1]["depends_on_features"] = ["F-1"]  # 应为 F-001

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "depends_on_features" in errors_text


# ======================== 额外：features 不是列表 → fail ========================

def test_features_not_list_fails(tmp_path, monkeypatch):
    """given_features_is_not_list_when_check_then_fail。"""
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    data["features"] = "not a list"

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "features" in errors_text


# ======================== 额外：feature 缺多个字段（累积错误） ========================

def test_feature_missing_multiple_fields_accumulates_errors(tmp_path, monkeypatch):
    """given_feature_missing_multiple_required_fields_when_check_then_multiple_errors_reported。

    验证累积错误模式：不 fail-fast，全部必填缺失都报出来。
    """
    schema_file = _reload_with_schema(tmp_path, _valid_schema())
    monkeypatch.setattr(_cf_mod, "SCHEMA_PATH", schema_file)

    data = _valid_features_data(1)
    del data["features"][0]["title"]
    del data["features"][0]["description"]
    del data["features"][0]["acceptance"]

    report = _cf_mod.validate(data, _valid_schema(), "test_features.json")
    assert report.has_errors
    errors_text = " ".join(report.errors)
    assert "title" in errors_text
    assert "description" in errors_text
    assert "acceptance" in errors_text
    # 至少 3 条错误（3 个缺失字段）
    assert len(report.errors) >= 3, f"期望至少 3 条错误，实际：{len(report.errors)}"
