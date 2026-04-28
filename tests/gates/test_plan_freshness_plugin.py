"""plugins/plan_freshness.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（真实 requirements/）通过 monkeypatch 重定向到临时目录。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from plugins.base import Decision, GateContext
from plugins import plan_freshness as plugin_mod


# ====================== 工具函数 ======================


def _make_req_dir(tmp_path: Path, req_id: str = "REQ-2026-999") -> Path:
    """创建一个合法的需求目录（含 meta.yaml + plan.md）。"""
    req_dir = tmp_path / "requirements" / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    # meta.yaml
    (req_dir / "meta.yaml").write_text(
        yaml.dump({"id": req_id, "phase": "bootstrap"}),
        encoding="utf-8",
    )
    return req_dir


def _write_valid_plan(req_dir: Path) -> None:
    """写一个无占位符的 plan.md。"""
    (req_dir / "plan.md").write_text(
        "# 计划\n\n## 目标\n本次要实现 X 功能。\n\n## 范围\n- 不包含：\n  - 历史数据迁移\n\n## 风险\n无明显风险。\n",
        encoding="utf-8",
    )


# ====================== pass 用例 ======================


def test_plan_freshness_passes_on_valid_plan(tmp_path, monkeypatch):
    """given_valid_plan_when_run_then_pass（pass fixture）."""
    req_dir = _make_req_dir(tmp_path)
    _write_valid_plan(req_dir)

    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)
    import check_plan as cp_mod
    monkeypatch.setattr(cp_mod, "REQUIREMENTS_DIR", tmp_path / "requirements")

    gate = plugin_mod.PlanFreshnessGate()
    ctx = GateContext(trigger="ci", extra={"plan_req_dirs": [str(req_dir)]})
    report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-PLAN-FRESHNESS"


def test_plan_freshness_passes_on_no_requirements(tmp_path, monkeypatch):
    """given_no_requirements_when_run_then_pass（空目录兜底）."""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    gate = plugin_mod.PlanFreshnessGate()
    ctx = GateContext(trigger="ci")
    report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert "no requirements" in (report.message or "")


# ====================== fail 用例 ======================


def test_plan_freshness_fails_on_missing_plan(tmp_path, monkeypatch):
    """given_req_without_plan_md_when_run_then_fail（fail fixture, E001）."""
    req_dir = _make_req_dir(tmp_path)
    # 不创建 plan.md

    import check_plan as cp_mod
    monkeypatch.setattr(cp_mod, "REQUIREMENTS_DIR", tmp_path / "requirements")
    import common as common_mod
    monkeypatch.setattr(common_mod, "REPO_ROOT", tmp_path)

    gate = plugin_mod.PlanFreshnessGate()
    ctx = GateContext(trigger="ci", extra={"plan_req_dirs": [str(req_dir)]})
    report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "R-PLAN"
    assert "plan.md" in (report.message or "").lower()


# ====================== skip 用例 ======================


def test_plan_freshness_skips_on_pre_commit_without_plan_change():
    """given_pre_commit_without_plan_md_when_precheck_then_skip（skip fixture）."""
    gate = plugin_mod.PlanFreshnessGate()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["scripts/foo.py", "requirements/REQ-001/meta.yaml"],
    )
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "no plan.md" in skip.reason


def test_plan_freshness_does_not_skip_when_plan_in_changed():
    gate = plugin_mod.PlanFreshnessGate()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["requirements/REQ-001/plan.md"],
    )
    assert gate.precheck(ctx) is None


def test_plan_freshness_does_not_skip_on_ci_trigger():
    gate = plugin_mod.PlanFreshnessGate()
    ctx = GateContext(trigger="ci")
    assert gate.precheck(ctx) is None
