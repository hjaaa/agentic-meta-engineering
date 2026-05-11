"""plugins/phase_in_set.py 单测（F-004 / TC-FG4-1）。

覆盖：
  - PASS：phase=development / phase=testing
  - FAIL：phase 不在白名单（如 detail-design / outline-design / completed）
  - FAIL：phase 字段缺失
  - SKIP：非 submit trigger
"""
from __future__ import annotations

import pytest

from plugins.base import Decision, GateContext
from plugins import phase_in_set as plugin_mod


def _make_ctx(phase, trigger="submit"):
    return GateContext(trigger=trigger, meta={"phase": phase} if phase is not None else {})


# ====================== precheck SKIP ======================


def test_phase_in_set_skipped_for_non_submit_trigger():
    gate = plugin_mod.PhaseInSetGate()
    skip = gate.precheck(_make_ctx("development", trigger="ci"))
    assert skip is not None
    assert "非 submit" in skip.reason


# ====================== PASS ======================


@pytest.mark.parametrize("phase", ["development", "testing"])
def test_phase_in_set_passes_for_submittable_phases(phase):
    gate = plugin_mod.PhaseInSetGate()
    report = gate.run(_make_ctx(phase))
    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-BYPASS-PHASE-IN-SET"


# ====================== FAIL ======================


@pytest.mark.parametrize(
    "phase",
    ["bootstrap", "definition", "tech-research", "outline-design", "detail-design",
     "task-planning", "completed", "archived"],
)
def test_phase_in_set_fails_for_non_submittable_phases(phase):
    gate = plugin_mod.PhaseInSetGate()
    report = gate.run(_make_ctx(phase))
    assert report.decision == Decision.FAIL
    assert report.code == "R-PHASE-NOT-SUBMITTABLE"
    assert phase in report.message
    assert "/workflow:next" in report.fix_hint


def test_phase_in_set_fails_when_phase_missing():
    gate = plugin_mod.PhaseInSetGate()
    report = gate.run(_make_ctx(None))
    assert report.decision == Decision.FAIL
    assert report.code == "R-PHASE-NOT-SUBMITTABLE"
    assert "缺失" in report.message
