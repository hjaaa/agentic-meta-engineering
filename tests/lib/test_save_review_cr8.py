"""CR-8 单测：F-002（remove human sign-off）已删除 CR-8 规则。

历史背景：CR-8 校验 human_signoff.source ∈ {cli-tty}；human_signoff 字段下线后
本测试文件整体不再适用。F-002 阶段先用 pytest.skip 整体跳过 collection，
配合 F-003 收尾时随 signoff 子系统一起删除。
"""
from __future__ import annotations

import pytest

pytest.skip(
    "F-002 已删除 CR-8 规则——human_signoff 字段下线；本测试文件随 F-003 收尾删除",
    allow_module_level=True,
)

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import save_review as sr  # noqa: E402
from common import Report, Severity  # noqa: E402


def _make_valid_verdict_with_signoff(source: str) -> dict:
    """返回含 human_signoff 的合法 verdict（conclusion 使用新枚举）。"""
    return {
        "conclusion": "looks_clean",
        "required_fixes": [],
        "score": 80,
        "dimensions": {},
        "human_signoff": {
            "decision": "approved",
            "signed_at": "2026-04-30T10:00:00Z",
            "signed_by": "user@example.com",
            "source": source,
        },
    }


def test_cr8_rejects_source_pr_review():
    """given_human_signoff_source_pr_review_when_check_then_cr8_error。"""
    verdict = _make_valid_verdict_with_signoff("pr-review")

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    assert report.errors > 0, "期望 report.errors > 0"
    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-8" in codes, f"期望 CR-8，实际 codes={codes}"


def test_cr8_error_message_contains_human_signoff_source():
    """CR-8 错误消息必须包含子串 'human_signoff.source'（验收硬约束）。"""
    verdict = _make_valid_verdict_with_signoff("pr-review")

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    cr8_msgs = [
        msg for _, sev, code, msg in report.findings()
        if sev == Severity.ERROR and code == "CR-8"
    ]
    assert cr8_msgs, "未找到 CR-8 finding"
    assert any("human_signoff.source" in msg for msg in cr8_msgs), (
        f"CR-8 消息不含 'human_signoff.source'，实际消息：{cr8_msgs}"
    )


def test_cr8_error_message_contains_illegal_source_repr():
    """CR-8 消息包含非法 source 的 repr 格式（如 \\'pr-review\\'）。"""
    verdict = _make_valid_verdict_with_signoff("pr-review")

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    cr8_msgs = [
        msg for _, sev, code, msg in report.findings()
        if sev == Severity.ERROR and code == "CR-8"
    ]
    assert any("'pr-review'" in msg for msg in cr8_msgs), (
        f"CR-8 消息不含 \\'pr-review\\'，实际：{cr8_msgs}"
    )


def test_cr8_passes_for_cli_tty_source():
    """given_human_signoff_source_cli_tty_when_check_then_no_cr8_error。"""
    verdict = _make_valid_verdict_with_signoff("cli-tty")

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-8" not in codes, f"不期望 CR-8，实际 codes={codes}"


def test_cr8_skipped_when_human_signoff_absent():
    """given_no_human_signoff_when_check_then_no_cr8_error（CR-8 仅在 sig 非空时触发）。"""
    verdict = {
        "conclusion": "looks_clean",
        "required_fixes": [],
        "score": 80,
        "dimensions": {},
        # human_signoff 不存在
    }

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-8" not in codes


def test_cr8_skipped_when_human_signoff_is_none():
    """given_human_signoff_null_when_check_then_no_cr8_error。"""
    verdict = {
        "conclusion": "looks_clean",
        "required_fixes": [],
        "score": 80,
        "dimensions": {},
        "human_signoff": None,
    }

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-8" not in codes


def test_cr8_rejects_empty_string_source():
    """given_human_signoff_source_empty_string_when_check_then_cr8_error（空字符串非 cli-tty）。"""
    verdict = _make_valid_verdict_with_signoff("")

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-8" in codes
