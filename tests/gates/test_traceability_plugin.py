"""plugins/traceability.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（真实 requirements/）通过临时目录 + monkeypatch 隔离。
"""
from __future__ import annotations

import json
from pathlib import Path

from plugins.base import Decision, GateContext
from plugins import traceability as plugin_mod


# ====================== 工具函数 ======================


def _write_features_json(req_dir: Path, features: list[dict]) -> None:
    artifacts_dir = req_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "features.json").write_text(
        json.dumps({"features": features}),
        encoding="utf-8",
    )


def _write_design(req_dir: Path, content: str) -> None:
    artifacts_dir = req_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "detailed-design.md").write_text(content, encoding="utf-8")


# ====================== pass 用例 ======================


def test_traceability_passes_when_all_done_features_in_design(tmp_path, monkeypatch):
    """given_done_features_in_design_when_run_then_pass（pass fixture）."""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    _write_features_json(req_dir, [{"id": "F-001", "status": "done"}])
    _write_design(req_dir, "# 设计\n\n## F-001 实现详情\n\n内容\n")

    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
        to_phase="testing",
    )
    report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-TRACEABILITY"


def test_traceability_passes_when_no_done_features(tmp_path, monkeypatch):
    """given_no_done_features_when_run_then_pass（没有 done feature，不阻断）."""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    _write_features_json(req_dir, [{"id": "F-001", "status": "in-progress"}])

    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
        to_phase="testing",
    )
    report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert "no done" in (report.message or "")


# ====================== fail 用例 ======================


def test_traceability_fails_when_features_json_missing(tmp_path, monkeypatch):
    """given_no_features_json_when_run_then_fail（fail fixture, T001）."""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    req_dir.mkdir(parents=True, exist_ok=True)

    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
        to_phase="testing",
    )
    report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "T001"


def test_traceability_fails_when_done_feature_not_in_design(tmp_path, monkeypatch):
    """given_done_feature_not_in_design_when_run_then_fail（fail fixture, T002）."""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    _write_features_json(req_dir, [{"id": "F-001", "status": "done"}])
    # detailed-design.md 不包含 F-001
    _write_design(req_dir, "# 设计\n\n## 其他章节\n\n内容\n")

    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
        to_phase="testing",
    )
    report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "T002"
    assert "F-001" in (report.message or "")


# ====================== skip 用例 ======================


def test_traceability_skips_when_to_phase_not_testing():
    """given_to_phase_ne_testing_when_precheck_then_skip（skip fixture）."""
    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
        to_phase="development",
    )
    skip = gate.precheck(ctx)

    assert skip is not None
    assert "testing" in skip.reason


def test_traceability_skips_when_no_requirement_id():
    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(trigger="phase-transition", to_phase="testing")
    skip = gate.precheck(ctx)
    assert skip is not None


def test_traceability_does_not_skip_when_to_testing():
    gate = plugin_mod.TraceabilityGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
        to_phase="testing",
    )
    assert gate.precheck(ctx) is None
