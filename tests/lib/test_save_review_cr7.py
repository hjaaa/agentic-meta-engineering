"""CR-7 单测：conclusion 使用旧枚举值（如 approved）时必须被拒收。

验收要求：
  - conclusion=approved 的 verdict → report.errors > 0
  - 发现项中必须有 code='CR-7'
  - 错误消息必须包含子串 'not in enum'
  - _check_cr_rules 签名仍是 (verdict, report, label) -> None

来源：requirements/REQ-2026-003/artifacts/detailed-design.md §F-001.3 CR-7
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

# 注入 scripts/lib 到 path
_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import save_review as sr  # noqa: E402
from common import Report, Severity  # noqa: E402


def _make_valid_verdict_base() -> dict:
    """返回一个仅 conclusion 需调整的最简 verdict 骨架（其余字段不影响 CR-7 判断）。"""
    return {
        "conclusion": "looks_clean",     # 默认合法值，由各用例覆盖
        "required_fixes": [],
        "score": 80,
        "dimensions": {},
        "human_signoff": None,
    }


def test_cr7_rejects_old_conclusion_approved():
    """given_conclusion_approved_when_check_cr_rules_then_cr7_error。"""
    verdict = _make_valid_verdict_base()
    verdict["conclusion"] = "approved"

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    assert report.errors > 0, "期望 report.errors > 0，但无错误"
    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-7" in codes, f"期望 findings 中含 CR-7，实际 codes={codes}"


def test_cr7_error_message_contains_not_in_enum():
    """CR-7 错误消息必须包含 'not in enum' 子串（验收硬约束）。"""
    verdict = _make_valid_verdict_base()
    verdict["conclusion"] = "approved"

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    cr7_msgs = [
        msg for _, sev, code, msg in report.findings()
        if sev == Severity.ERROR and code == "CR-7"
    ]
    assert cr7_msgs, "未找到 CR-7 finding"
    assert any("not in enum" in msg for msg in cr7_msgs), (
        f"CR-7 消息不含 'not in enum'，实际消息：{cr7_msgs}"
    )


def test_cr7_error_message_contains_old_value_repr():
    """CR-7 错误消息必须包含旧枚举值（带单引号的 repr 格式，如 \\'approved\\'）。"""
    verdict = _make_valid_verdict_base()
    verdict["conclusion"] = "approved"

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    cr7_msgs = [
        msg for _, sev, code, msg in report.findings()
        if sev == Severity.ERROR and code == "CR-7"
    ]
    assert any("'approved'" in msg for msg in cr7_msgs), (
        f"CR-7 消息不含 \\'approved\\'，实际消息：{cr7_msgs}"
    )


def test_cr7_rejects_old_conclusion_needs_revision():
    """given_conclusion_needs_revision_when_check_then_cr7_error。"""
    verdict = _make_valid_verdict_base()
    verdict["conclusion"] = "needs_revision"
    verdict["required_fixes"] = ["fix something"]  # 避免触发 CR-2

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-7" in codes


def test_cr7_passes_for_new_enum_looks_clean():
    """given_conclusion_looks_clean_when_check_then_no_cr7_error。"""
    verdict = _make_valid_verdict_base()
    verdict["conclusion"] = "looks_clean"

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-7" not in codes, f"不期望 CR-7，实际 codes={codes}"


def test_cr7_passes_for_new_enum_needs_attention():
    """given_conclusion_needs_attention_when_check_then_no_cr7_error。"""
    verdict = _make_valid_verdict_base()
    verdict["conclusion"] = "needs_attention"
    verdict["required_fixes"] = ["must fix this"]

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-7" not in codes


def test_cr7_passes_for_new_enum_blocked():
    """given_conclusion_blocked_when_check_then_no_cr7_error。"""
    verdict = _make_valid_verdict_base()
    verdict["conclusion"] = "blocked"
    verdict["required_fixes"] = ["critical issue"]

    report = Report()
    sr._check_cr_rules(verdict, report, "test")

    codes = [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]
    assert "CR-7" not in codes


def test_check_cr_rules_signature():
    """_check_cr_rules 签名必须是 (verdict, report, label) -> None（接口契约）。"""
    sig = inspect.signature(sr._check_cr_rules)
    params = list(sig.parameters.keys())
    assert params == ["verdict", "report", "label"], (
        f"签名不符预期，实际参数：{params}"
    )
    # Python 3.14 + PEP 563 (from __future__ import annotations) 下返回注解是字符串 'None'；
    # 同时兼容无注解（inspect.Parameter.empty）和老式 None / NoneType
    ret = sig.return_annotation
    assert ret in (None, inspect.Parameter.empty, type(None), "None"), (
        f"返回值注解应为 None，实际：{ret!r}"
    )
