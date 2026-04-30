"""CR-2/3/4/6 平移测试：在新枚举下的等价行为各 1 fixture。

验证 CR-1~6 在升级到 v2.0 枚举后行为符合预期：
  - CR-2: required_fixes 非空 → conclusion 必须 ∈ {needs_attention, blocked}
  - CR-3: dim.score < 60 → conclusion ≠ looks_clean
  - CR-4: score < 70 → conclusion ≠ looks_clean
  - CR-6: blocker issue → conclusion 必须 == blocked

来源：requirements/REQ-2026-003/artifacts/detailed-design.md §F-001.3
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import save_review as sr  # noqa: E402
from common import Report, Severity  # noqa: E402


def _get_error_codes(report: Report) -> list[str]:
    """提取 report 中所有 ERROR 级别的 code 列表。"""
    return [code for _, sev, code, _ in report.findings() if sev == Severity.ERROR]


# ---------- CR-2 ----------

def test_cr2_triggers_when_required_fixes_nonempty_and_conclusion_looks_clean():
    """given_required_fixes_nonempty_conclusion_looks_clean_when_check_then_cr2_error。"""
    verdict = {
        "conclusion": "looks_clean",
        "required_fixes": ["fix this issue"],
        "score": 80,
        "dimensions": {},
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-2" in codes, f"期望 CR-2，实际 codes={codes}"


def test_cr2_passes_when_required_fixes_nonempty_and_conclusion_needs_attention():
    """given_required_fixes_nonempty_conclusion_needs_attention_when_check_then_no_cr2_error。"""
    verdict = {
        "conclusion": "needs_attention",
        "required_fixes": ["fix this issue"],
        "score": 80,
        "dimensions": {},
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-2" not in codes, f"不期望 CR-2，实际 codes={codes}"


def test_cr2_passes_when_required_fixes_nonempty_and_conclusion_blocked():
    """given_required_fixes_nonempty_conclusion_blocked_when_check_then_no_cr2_error。"""
    verdict = {
        "conclusion": "blocked",
        "required_fixes": ["must fix"],
        "score": 80,
        "dimensions": {},
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-2" not in codes


# ---------- CR-3 ----------

def test_cr3_triggers_when_dim_score_below_60_and_conclusion_looks_clean():
    """given_dim_score_55_conclusion_looks_clean_when_check_then_cr3_error。"""
    verdict = {
        "conclusion": "looks_clean",
        "required_fixes": [],
        "score": 80,
        "dimensions": {
            "correctness": {"score": 55, "issues": []},
        },
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-3" in codes, f"期望 CR-3，实际 codes={codes}"


def test_cr3_passes_when_dim_score_below_60_and_conclusion_needs_attention():
    """given_dim_score_55_conclusion_needs_attention_when_check_then_no_cr3_error。"""
    verdict = {
        "conclusion": "needs_attention",
        "required_fixes": ["fix dim"],
        "score": 75,
        "dimensions": {
            "correctness": {"score": 55, "issues": []},
        },
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-3" not in codes


# ---------- CR-4 ----------

def test_cr4_triggers_when_score_below_70_and_conclusion_looks_clean():
    """given_score_65_conclusion_looks_clean_when_check_then_cr4_error。"""
    verdict = {
        "conclusion": "looks_clean",
        "required_fixes": [],
        "score": 65,
        "dimensions": {},
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-4" in codes, f"期望 CR-4，实际 codes={codes}"


def test_cr4_passes_when_score_below_70_and_conclusion_needs_attention():
    """given_score_65_conclusion_needs_attention_when_check_then_no_cr4_error。"""
    verdict = {
        "conclusion": "needs_attention",
        "required_fixes": ["something"],
        "score": 65,
        "dimensions": {},
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-4" not in codes


# ---------- CR-6 ----------

def test_cr6_triggers_when_blocker_issue_and_conclusion_not_blocked():
    """given_blocker_issue_conclusion_needs_attention_when_check_then_cr6_error。"""
    verdict = {
        "conclusion": "needs_attention",
        "required_fixes": ["critical"],
        "score": 70,
        "dimensions": {
            "security": {
                "score": 70,
                "issues": [{"severity": "blocker", "description": "SQL injection risk"}],
            }
        },
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-6" in codes, f"期望 CR-6，实际 codes={codes}"


def test_cr6_triggers_when_blocker_issue_and_conclusion_looks_clean():
    """given_blocker_issue_conclusion_looks_clean_when_check_then_cr6_error。"""
    verdict = {
        "conclusion": "looks_clean",
        "required_fixes": [],
        "score": 70,
        "dimensions": {
            "security": {
                "score": 70,
                "issues": [{"severity": "blocker", "description": "Critical bug"}],
            }
        },
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-6" in codes


def test_cr6_passes_when_blocker_issue_and_conclusion_blocked():
    """given_blocker_issue_conclusion_blocked_when_check_then_no_cr6_error。"""
    verdict = {
        "conclusion": "blocked",
        "required_fixes": ["critical must fix"],
        "score": 70,
        "dimensions": {
            "security": {
                "score": 70,
                "issues": [{"severity": "blocker", "description": "Critical bug"}],
            }
        },
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-6" not in codes, f"不期望 CR-6，实际 codes={codes}"


def test_cr6_passes_when_no_blocker_issues():
    """given_only_major_issues_when_check_then_no_cr6_error。"""
    verdict = {
        "conclusion": "needs_attention",
        "required_fixes": ["something"],
        "score": 75,
        "dimensions": {
            "correctness": {
                "score": 75,
                "issues": [{"severity": "major", "description": "Logic flaw"}],
            }
        },
    }
    report = Report()
    sr._check_cr_rules(verdict, report, "test")
    codes = _get_error_codes(report)
    assert "CR-6" not in codes
