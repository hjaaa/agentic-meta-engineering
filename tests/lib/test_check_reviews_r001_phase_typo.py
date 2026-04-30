"""R001 fail-closed 修复回归测试（REQ-2026-003 工程债）。

历史 bug：
  scripts/lib/check_reviews.py:_r001_review_exists 用 PHASE_REQUIREMENTS.get(..., [])
  默认空 list 兜底，导致 target_phase 写错（如 'technical-research'）时 for-loop
  不进入 → 静默 vacuous pass。

修复：
  在 _r001_review_exists 头部用 phase_enum.load_canonical_phases() 校验 target_phase
  是否在 meta-schema.yaml.enums.phase 内；不在则直接报 R001 错误。

来源：requirements/REQ-2026-003 阶段切换排查（2026-04-30）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 注入 scripts/lib 到 path（与 test_check_reviews_r003_r007 一致）
_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from check_reviews import _r001_review_exists  # noqa: E402
from common import Report  # noqa: E402

_LABEL = "REQ-2099-TEST"


def test_r001_fails_on_typo_target_phase():
    """given_invalid_target_phase_when_r001_then_error。

    历史 bug：'technical-research'（应为 'tech-research'）会因 PHASE_REQUIREMENTS.get
    默认空 list 而静默通过；修复后必须报 R001 错误。

    findings 元组结构：(file, severity, code, message)
    """
    report = Report()
    meta = {"reviews": {}}
    _r001_review_exists(meta, "technical-research", report, _LABEL)

    findings = report.findings()
    assert len(findings) == 1
    _, severity, code, message = findings[0]
    assert code == "R001"
    assert "technical-research" in message
    assert "canonical phase 枚举" in message


def test_r001_fails_on_random_typo():
    """given_random_invalid_phase_when_r001_then_error（防御任何非 canonical 值）。"""
    report = Report()
    meta = {"reviews": {"definition": {"latest": "REV-001"}}}
    _r001_review_exists(meta, "DEV", report, _LABEL)

    findings = report.findings()
    assert any(code == "R001" and "DEV" in message for _, _, code, message in findings)


def test_r001_passes_for_canonical_phase_with_review():
    """given_canonical_phase_with_review_when_r001_then_no_error。

    canonical phase 名 + reviews.definition.latest 非空 → R001 不报错。
    """
    report = Report()
    meta = {"reviews": {"definition": {"latest": "REV-001"}}}
    _r001_review_exists(meta, "tech-research", report, _LABEL)
    assert report.findings() == []


def test_r001_passes_for_phase_without_review_requirement():
    """given_canonical_phase_without_review_requirement_when_r001_then_no_error。

    'bootstrap' / 'definition' 不在 PHASE_REQUIREMENTS 中（无前置 review 要求）但
    在 canonical 枚举内 → R001 不报错（保留原 vacuous-pass 在合法路径下的语义）。
    """
    report = Report()
    meta = {"reviews": {}}
    _r001_review_exists(meta, "bootstrap", report, _LABEL)
    _r001_review_exists(meta, "definition", report, _LABEL)
    assert report.findings() == []


def test_r001_fails_when_canonical_phase_missing_required_review():
    """given_canonical_phase_without_required_review_when_r001_then_error（原行为不变）。"""
    report = Report()
    meta = {"reviews": {}}  # 缺 definition review
    _r001_review_exists(meta, "tech-research", report, _LABEL)

    findings = report.findings()
    assert len(findings) == 1
    _, _, code, message = findings[0]
    assert code == "R001"
    assert "definition" in message
