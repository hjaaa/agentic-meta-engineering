"""R006 falsy supersedes 兼容单测（D-016）。

历史数据 bug：F-008-001.json 因 save_review 写入偏差出现 supersedes=""，
工具应把 None / "" / 0 等 falsy 值统一视为"无前序 round-001"，不进入悬挂引用检查。

覆盖：
  - TC-R006-FALSY-1：supersedes=None 不报 R006（基线）
  - TC-R006-FALSY-2：supersedes="" 不报 R006（D-016 修复点）
  - TC-R006-FALSY-3：supersedes 指向存在 review 不报 R006（链合法）
  - TC-R006-FALSY-4：supersedes 指向不存在 review 仍报 R006（真实悬挂引用）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from check_reviews import _r006_supersedes_chain  # noqa: E402
from common import Report, Severity  # noqa: E402

_REQ = "REQ-2099-R006"


def _write_verdict(reviews_dir: Path, filename: str, review_id: str, supersedes) -> None:
    reviews_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "1.0",
        "review_id": review_id,
        "requirement_id": _REQ,
        "phase": "code",
        "reviewer": "code-quality-reviewer",
        "reviewed_at": "2026-05-06 12:00:00",
        "reviewed_commit": "abc1234",
        "reviewed_artifacts": [],
        "conclusion": "looks_clean",
        "score": 90,
        "dimensions": {},
        "required_fixes": [],
        "suggestions": [],
        "scope": {"feature_id": "F-001"},
        "supersedes": supersedes,
    }
    (reviews_dir / filename).write_text(json.dumps(data), encoding="utf-8")


def _run_r006(tmp_path: Path) -> Report:
    """重定向 REQUIREMENTS_DIR 到 tmp_path 后跑 _r006_supersedes_chain。"""
    import check_reviews as cr
    original = cr.REQUIREMENTS_DIR
    cr.REQUIREMENTS_DIR = tmp_path / "requirements"
    try:
        report = Report()
        _r006_supersedes_chain({}, "testing", report, _REQ, _REQ)
        return report
    finally:
        cr.REQUIREMENTS_DIR = original


def _r006_codes(report: Report) -> list[str]:
    return [c for _f, _s, c, _m in report.findings() if c == "R006"]


def test_supersedes_none_does_not_trigger_r006(tmp_path):
    """given_supersedes_none_when_check_then_no_r006（TC-R006-FALSY-1 基线）。"""
    reviews_dir = tmp_path / "requirements" / _REQ / "reviews"
    _write_verdict(reviews_dir, "code-F-001-001.json", f"REV-{_REQ}-code-F-001-001", None)
    report = _run_r006(tmp_path)
    assert _r006_codes(report) == [], (
        f"None supersedes 不应触发 R006，实际 findings={report.findings()}"
    )


def test_supersedes_empty_string_does_not_trigger_r006(tmp_path):
    """given_supersedes_empty_string_when_check_then_no_r006（TC-R006-FALSY-2 D-016 修复点）。

    场景：F-008-001.json 历史数据 bug，supersedes 字段被写入空字符串。工具应接受
    falsy 值视为"无前序"，避免历史单点数据触发误报。
    """
    reviews_dir = tmp_path / "requirements" / _REQ / "reviews"
    _write_verdict(reviews_dir, "code-F-001-001.json", f"REV-{_REQ}-code-F-001-001", "")
    report = _run_r006(tmp_path)
    assert _r006_codes(report) == [], (
        f"空字符串 supersedes 不应触发 R006，实际 findings={report.findings()}"
    )


def test_supersedes_existing_review_no_r006(tmp_path):
    """given_supersedes_existing_when_check_then_no_r006（TC-R006-FALSY-3 链合法）。"""
    reviews_dir = tmp_path / "requirements" / _REQ / "reviews"
    _write_verdict(reviews_dir, "code-F-001-001.json", f"REV-{_REQ}-code-F-001-001", None)
    _write_verdict(
        reviews_dir, "code-F-001-002.json", f"REV-{_REQ}-code-F-001-002",
        f"REV-{_REQ}-code-F-001-001",
    )
    report = _run_r006(tmp_path)
    assert _r006_codes(report) == [], (
        f"合法 supersedes 链不应触发 R006，实际 findings={report.findings()}"
    )


def test_supersedes_dangling_still_triggers_r006(tmp_path):
    """given_supersedes_dangling_when_check_then_r006（TC-R006-FALSY-4 真悬挂保护）。"""
    reviews_dir = tmp_path / "requirements" / _REQ / "reviews"
    _write_verdict(
        reviews_dir, "code-F-001-002.json", f"REV-{_REQ}-code-F-001-002",
        f"REV-{_REQ}-code-F-001-001",  # 但 001 不存在
    )
    report = _run_r006(tmp_path)
    codes = _r006_codes(report)
    assert codes, f"真实悬挂引用应触发 R006，实际 findings={report.findings()}"
