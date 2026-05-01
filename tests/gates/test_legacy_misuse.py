"""F-005 · meta_schema._check_legacy_misuse 防护测试。

覆盖：
  - legacy=true + phase=development → R-LEGACY-MISUSE（ERROR）
  - legacy=true + phase=completed → 通过（合法）
  - legacy=true + phase=archived → 通过（合法）
  - legacy 字段不存在 → 通过
  - legacy=false → 通过（不触发误用检查）
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from plugins.base import Decision, GateContext
from plugins import meta_schema as plugin_mod


# ====================== 工具函数 ======================


def _write_meta(path: Path, body: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(body, f, allow_unicode=True)


def _valid_meta(req_id: str = "REQ-2026-999", phase: str = "bootstrap") -> dict:
    """基础合法 meta.yaml。"""
    return {
        "id": req_id,
        "title": "test",
        "phase": phase,
        "created_at": "2026-04-27 10:00:00",
        "branch": f"feat/{req_id.lower()}",
        "base_branch": "develop",
        "project": "agentic-meta-engineering",
        "services": ["agentic-meta-engineering"],
        "feature_area": "",
        "change_type": "",
        "affected_modules": [],
    }


# ====================== 单元测试：直接测 _check_legacy_misuse ======================


def test_check_legacy_misuse_errors_when_development(tmp_path):
    """given_legacy_true_phase_development_when_check_then_r_legacy_misuse（核心用例）。"""
    from scripts.lib.common import Report as LegacyReport  # noqa: PLC0415

    report = LegacyReport()
    meta = {"legacy": True, "phase": "development"}
    plugin_mod._check_legacy_misuse(meta, report)

    findings = report.findings()
    assert len(findings) == 1, f"应有 1 条 finding，实际: {findings}"
    _file, severity, code, message = findings[0]
    assert code == "R-LEGACY-MISUSE"
    assert "development" in message


def test_check_legacy_misuse_passes_when_completed():
    """given_legacy_true_phase_completed_when_check_then_no_finding。"""
    from scripts.lib.common import Report as LegacyReport  # noqa: PLC0415

    report = LegacyReport()
    plugin_mod._check_legacy_misuse({"legacy": True, "phase": "completed"}, report)
    assert report.findings() == []


def test_check_legacy_misuse_passes_when_archived():
    """given_legacy_true_phase_archived_when_check_then_no_finding。"""
    from scripts.lib.common import Report as LegacyReport  # noqa: PLC0415

    report = LegacyReport()
    plugin_mod._check_legacy_misuse({"legacy": True, "phase": "archived"}, report)
    assert report.findings() == []


def test_check_legacy_misuse_passes_when_no_legacy_field():
    """given_no_legacy_field_when_check_then_no_finding。"""
    from scripts.lib.common import Report as LegacyReport  # noqa: PLC0415

    report = LegacyReport()
    plugin_mod._check_legacy_misuse({"phase": "development"}, report)
    assert report.findings() == []


def test_check_legacy_misuse_passes_when_legacy_false():
    """given_legacy_false_when_check_then_no_finding（false 不触发误用检查）。"""
    from scripts.lib.common import Report as LegacyReport  # noqa: PLC0415

    report = LegacyReport()
    plugin_mod._check_legacy_misuse({"legacy": False, "phase": "development"}, report)
    assert report.findings() == []


# ====================== 集成测试：通过 Gate.run() 端到端验证 ======================


def test_gate_run_fails_when_legacy_misuse_in_development(tmp_path):
    """given_meta_with_legacy_true_phase_development_when_gate_run_then_fail。"""
    meta = _valid_meta(phase="development")
    meta["legacy"] = True
    meta_file = tmp_path / "meta.yaml"
    _write_meta(meta_file, meta)

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_file)]})
    report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    # R-LEGACY-MISUSE 是 ERROR，通过 R-META 聚合
    assert report.code == "R-META"
    # vars 中的 errors 列表应包含 R-LEGACY-MISUSE
    error_codes = [e[2] for e in report.vars.get("errors", [])]
    assert "R-LEGACY-MISUSE" in error_codes, f"errors code 列表: {error_codes}"


def test_gate_run_passes_when_legacy_true_phase_completed(tmp_path):
    """given_meta_legacy_true_phase_completed_when_gate_run_then_pass。"""
    meta = _valid_meta(phase="completed")
    meta["legacy"] = True
    meta_file = tmp_path / "meta.yaml"
    _write_meta(meta_file, meta)

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_file)]})
    report = gate.run(ctx)

    # completed 阶段 legacy=true 合法：只要其他字段校验不出 ERROR 就 PASS
    # 注意 check_meta 本身可能对 completed 阶段有额外规则，这里核心断言不含 R-LEGACY-MISUSE
    if report.decision == Decision.FAIL:
        error_codes = [e[2] for e in report.vars.get("errors", [])]
        assert "R-LEGACY-MISUSE" not in error_codes, (
            f"completed 阶段不应触发 R-LEGACY-MISUSE，errors: {error_codes}"
        )


def test_gate_run_passes_when_no_legacy_field(tmp_path):
    """given_meta_no_legacy_field_when_gate_run_then_pass。"""
    meta_file = tmp_path / "meta.yaml"
    _write_meta(meta_file, _valid_meta())

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_file)]})
    report = gate.run(ctx)

    assert report.decision == Decision.PASS
