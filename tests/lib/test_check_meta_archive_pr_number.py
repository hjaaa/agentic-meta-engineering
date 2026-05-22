"""check_meta._check_archive_pr_number_state_machine 单元测试。

覆盖 6 TC：TC-F4-1 ~ TC-F4-6
  - TC-F4-1: phase=testing + archive_pr_number=0 → PASS
  - TC-F4-2: phase=testing + archive_pr_number=42 → FAIL state-machine
  - TC-F4-3: phase=completed + archive_pr_number=0 → PASS（兼容历史）
  - TC-F4-4: phase=completed + archive_pr_number=42 → PASS
  - TC-F4-5: phase=development + 字段缺失 → PASS
  - TC-F4-6: phase=completed + archive_pr_number='abc'（非法类型）→ int() 转换失败 fallback 当 0 → PASS
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from check_meta import _check_archive_pr_number_state_machine  # noqa: E402
from common import Report  # noqa: E402


# ---------- helpers ----------


def _run_check(meta: dict[str, Any]) -> Report:
    """对给定 meta dict 跑状态机校验，返回 Report。"""
    report = Report()
    _check_archive_pr_number_state_machine(meta, report, "test/meta.yaml")
    return report


def _has_state_machine_error(report: Report) -> bool:
    """Report findings 中是否含 'state-machine' code 的 ERROR。"""
    return any(
        code == "state-machine"
        for _, sev, code, _ in report.findings()
        if sev == "error"  # Severity.ERROR == "error"
    )


# ---------- TC-F4-1 ----------


def test_phase_testing_archive_pr_number_zero_passes() -> None:
    """TC-F4-1: phase=testing + archive_pr_number=0 → PASS（report.errors == 0）。"""
    meta = {"phase": "testing", "archive_pr_number": 0}
    report = _run_check(meta)

    assert report.errors == 0, (
        f"phase=testing + archive_pr_number=0 should PASS, got {report.errors} error(s)"
    )


# ---------- TC-F4-2 ----------


def test_phase_testing_archive_pr_number_nonzero_fails() -> None:
    """TC-F4-2: phase=testing + archive_pr_number=42 → FAIL state-machine。"""
    meta = {"phase": "testing", "archive_pr_number": 42}
    report = _run_check(meta)

    assert report.errors > 0, (
        "phase=testing + archive_pr_number=42 should FAIL (errors > 0)"
    )
    assert _has_state_machine_error(report), (
        f"report.findings should contain 'state-machine' error, got: {report.findings()}"
    )


# ---------- TC-F4-3 ----------


def test_phase_completed_archive_pr_number_zero_passes() -> None:
    """TC-F4-3: phase=completed + archive_pr_number=0 → PASS（兼容历史 REQ，无归档 PR）。"""
    meta = {"phase": "completed", "archive_pr_number": 0}
    report = _run_check(meta)

    assert report.errors == 0, (
        f"phase=completed + archive_pr_number=0 should PASS (historical compat), "
        f"got {report.errors} error(s)"
    )


# ---------- TC-F4-4 ----------


def test_phase_completed_archive_pr_number_nonzero_passes() -> None:
    """TC-F4-4: phase=completed + archive_pr_number=42 → PASS（正常完成归档）。"""
    meta = {"phase": "completed", "archive_pr_number": 42}
    report = _run_check(meta)

    assert report.errors == 0, (
        f"phase=completed + archive_pr_number=42 should PASS, got {report.errors} error(s)"
    )


# ---------- TC-F4-5 ----------


def test_phase_development_field_missing_passes() -> None:
    """TC-F4-5: phase=development + archive_pr_number 字段缺失 → PASS（缺失视同 0）。"""
    meta = {"phase": "development"}  # archive_pr_number 字段不存在
    report = _run_check(meta)

    assert report.errors == 0, (
        f"phase=development + archive_pr_number missing should PASS, got {report.errors} error(s)"
    )


# ---------- TC-F4-6 ----------


def test_phase_completed_archive_pr_number_invalid_type_fallback_passes() -> None:
    """TC-F4-6: phase=completed + archive_pr_number='abc' → int() 转换失败 fallback 当 0 → PASS。

    fallback 行为与 _check_archived_at_state_machine 一致（宽松处理非法类型）。
    """
    meta = {"phase": "completed", "archive_pr_number": "abc"}
    report = _run_check(meta)

    assert report.errors == 0, (
        f"phase=completed + archive_pr_number='abc' should PASS (fallback to 0), "
        f"got {report.errors} error(s): {report.findings()}"
    )
