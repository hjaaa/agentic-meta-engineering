"""requirement_naming.py 单元测试，≥ 11 用例。

约定：验证冲突场景必须用 existing_keys 集合注入，禁止用 tmp_path mkdir。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.lib.requirement_naming import (
    SlugError,
    branch_for_requirement_key,
    derive_slug_from_title,
    directory_for_requirement_key,
    generate_requirement_key,
    is_legacy_requirement_key,
    normalize_slug,
)


# ─────────────────────── normalize_slug ───────────────────────


def test_normalize_slug_lowercase_and_hyphenate():
    assert normalize_slug("Hello World") == "hello-world"


def test_normalize_slug_underscore_to_hyphen():
    assert normalize_slug("foo_bar_baz") == "foo-bar-baz"


def test_normalize_slug_mixed_whitespace_and_underscore():
    assert normalize_slug("My Cool_Feature") == "my-cool-feature"


def test_normalize_slug_rejects_non_ascii():
    with pytest.raises(SlugError):
        normalize_slug("中文slug")


def test_normalize_slug_rejects_empty():
    with pytest.raises(SlugError):
        normalize_slug("")


def test_normalize_slug_rejects_all_hyphens():
    with pytest.raises(SlugError):
        normalize_slug("---")


def test_normalize_slug_rejects_length_over_64():
    with pytest.raises(SlugError):
        normalize_slug("a" * 65)


def test_normalize_slug_valid_max_length():
    result = normalize_slug("a" * 64)
    assert result == "a" * 64


# ─────────────────────── derive_slug_from_title ───────────────────────


def test_derive_slug_from_title_chinese_returns_none():
    assert derive_slug_from_title("新增需求管理功能") is None


def test_derive_slug_from_title_ascii_lowercased():
    result = derive_slug_from_title("Add New Feature")
    assert result == "add-new-feature"


def test_derive_slug_from_title_with_special_chars():
    result = derive_slug_from_title("Hello, World! 2025")
    assert result == "hello-world-2025"


def test_derive_slug_from_title_non_ascii_returns_none():
    # 包含 ASCII 范围之外的字符（如带重音的字母）
    assert derive_slug_from_title("Café au lait") is None


# ─────────────────────── generate_requirement_key ───────────────────────


def test_generate_requirement_key_basic_no_io():
    """基础场景：无冲突，返回首选 candidate key。"""
    d = date(2026, 5, 18)
    key = generate_requirement_key(d, "my-feature")
    assert key == "20260518-my-feature"


def test_generate_requirement_key_no_collision_returns_primary():
    """空 existing_keys 时直接返回首选，不加后缀。"""
    d = date(2026, 5, 18)
    key = generate_requirement_key(d, "foo", existing_keys=[])
    assert key == "20260518-foo"


def test_generate_requirement_key_collision_via_existing_keys_appends_02():
    """existing_keys 注入冲突：首选已占用 → 返回 -02 后缀。"""
    d = date(2026, 5, 18)
    existing = {"20260518-foo"}
    key = generate_requirement_key(d, "foo", existing_keys=existing)
    assert key == "20260518-foo-02"


def test_generate_requirement_key_collision_skips_to_03():
    """02 和首选均已占用 → 返回 -03 后缀。"""
    d = date(2026, 5, 18)
    existing = {"20260518-bar", "20260518-bar-02"}
    key = generate_requirement_key(d, "bar", existing_keys=existing)
    assert key == "20260518-bar-03"


def test_generate_requirement_key_overflow_after_99_raises():
    """02~99 全部占用 → 抛 SlugError。"""
    d = date(2026, 5, 18)
    existing = {"20260518-x"} | {f"20260518-x-{i:02d}" for i in range(2, 100)}
    with pytest.raises(SlugError):
        generate_requirement_key(d, "x", existing_keys=existing)


# ─────────────────────── is_legacy_requirement_key ───────────────────────


def test_is_legacy_requirement_key_recognizes_req_2026_014():
    assert is_legacy_requirement_key("REQ-2026-014") is True


def test_is_legacy_requirement_key_rejects_new_format():
    assert is_legacy_requirement_key("20260518-foo") is False


def test_is_legacy_requirement_key_rejects_partial_match():
    assert is_legacy_requirement_key("REQ-2026-14") is False  # NNN 只有 2 位


# ─────────────────────── branch_for_requirement_key ───────────────────────


def test_branch_for_requirement_key_legacy_and_new():
    """legacy 和新 key 都生成 feat/req-* 前缀。"""
    assert branch_for_requirement_key("REQ-2026-014") == "feat/req-2026-014"
    assert branch_for_requirement_key("20260518-foo") == "feat/req-20260518-foo"


def test_branch_for_requirement_key_legacy_lowercase():
    """legacy key 年份/序号保持小写（数字本就无大小写之分，fmt 不变）。"""
    branch = branch_for_requirement_key("REQ-2025-001")
    assert branch == "feat/req-2025-001"


# ─────────────────────── directory_for_requirement_key ───────────────────────


def test_directory_for_requirement_key_returns_path():
    p = directory_for_requirement_key("20260518-my-feature")
    assert p == Path("requirements/20260518-my-feature")


def test_directory_for_requirement_key_legacy():
    p = directory_for_requirement_key("REQ-2026-014")
    assert p == Path("requirements/REQ-2026-014")
