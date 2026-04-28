"""plugins/sourcing.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（真实 requirements/）通过 monkeypatch 重定向到临时目录。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from plugins.base import Decision, GateContext
from plugins import sourcing as plugin_mod


# ====================== 工具函数 ======================


def _write_md(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _valid_md() -> str:
    """合法的 artifacts.md：无 [待补充] 段落要素不足，无来源引用。"""
    return "# 合法文档\n\n正文内容，没有约束断言。\n"


def _invalid_md_e001() -> str:
    """触发 E001：[待补充] 段落缺假设四要素（内容/依据/风险/验证时机至少 3 个）。

    注意：E001 要求段落仅含 [待补充]，且"内容/依据/风险/验证时机"四关键词出现数 < 3。
    此处故意不包含任何要素关键词。
    """
    return "# 有问题的文档\n\n[待补充] 此段落没有说明任何事项。\n"


# ====================== pass 用例 ======================


def test_sourcing_passes_on_valid_md(tmp_path, monkeypatch):
    """given_valid_artifacts_md_when_run_then_pass（pass fixture）."""
    md_file = tmp_path / "requirement.md"
    _write_md(md_file, _valid_md())

    gate = plugin_mod.SourcingGate()
    ctx = GateContext(trigger="ci", extra={"sourcing_paths": [str(md_file)]})
    report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-SOURCING"


def test_sourcing_passes_on_no_targets(tmp_path, monkeypatch):
    """given_no_requirements_dir_when_run_then_pass（兜底扫全量时无目标）。"""
    # 重定向 _REPO_ROOT 使 requirements/ 不存在
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    gate = plugin_mod.SourcingGate()
    ctx = GateContext(trigger="ci")
    report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert "no artifacts" in (report.message or "")


# ====================== fail 用例 ======================


def test_sourcing_fails_on_e001_violation(tmp_path):
    """given_md_with_e001_violation_when_run_then_fail（fail fixture）."""
    md_file = tmp_path / "bad.md"
    _write_md(md_file, _invalid_md_e001())

    gate = plugin_mod.SourcingGate()
    ctx = GateContext(trigger="ci", extra={"sourcing_paths": [str(md_file)]})
    report = gate.run(ctx)

    # E001 是 ERROR → FAIL；W001 是 WARNING → 仍为 FAIL（因为 E001 先触发）
    assert report.decision == Decision.FAIL
    assert report.code == "R-SOURCING"
    # message 包含触发的 ERROR 规则前缀（E001）
    assert "E001" in (report.message or "") or "E001" in str(report.vars)


# ====================== skip 用例 ======================


def test_sourcing_skips_on_pre_commit_without_artifact_change():
    """given_pre_commit_without_artifacts_md_when_precheck_then_skip（skip fixture）."""
    gate = plugin_mod.SourcingGate()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["scripts/foo.py", "requirements/REQ-001/meta.yaml"],
    )
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "no artifacts" in skip.reason


def test_sourcing_does_not_skip_when_artifacts_in_changed():
    gate = plugin_mod.SourcingGate()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["requirements/REQ-001/artifacts/requirement.md"],
    )
    assert gate.precheck(ctx) is None


def test_sourcing_does_not_skip_on_ci_trigger():
    gate = plugin_mod.SourcingGate()
    ctx = GateContext(trigger="ci")
    assert gate.precheck(ctx) is None


# ====================== _has_artifact_md_change 边界 ======================


def test_has_artifact_md_change_true_for_nested():
    assert plugin_mod._has_artifact_md_change(["requirements/REQ-001/artifacts/tasks/F-001.md"])


def test_has_artifact_md_change_false_for_meta():
    assert not plugin_mod._has_artifact_md_change(["requirements/REQ-001/meta.yaml"])
