"""plugins/sourcing.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（真实 requirements/）通过 monkeypatch 重定向到临时目录。
"""
from __future__ import annotations

from pathlib import Path

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


# ====================== W002 衍生文档豁免 ======================


def _md_with_w002_trigger() -> str:
    """触发 W002：段落含强约束动词 + 30 字内出现数字、且无三态标记。"""
    return (
        "# 衍生文档\n\n"
        "本次 conclusion = blocked，**禁止 sign-off**。必须先修 4 critical → 重审 → 通过后才能 sign-off。\n"
    )


def test_sourcing_exempts_w002_for_review_files(tmp_path):
    """given_review_filename_when_run_then_w002_skipped。

    review-YYYYMMDD-HHMMSS.md 是评审报告（已 sign-off 的结论性叙述），
    数字断言来自评审上下文，不应受 W002 强制三态标记约束。
    """
    md_file = tmp_path / "review-20260501-101804.md"
    _write_md(md_file, _md_with_w002_trigger())

    gate = plugin_mod.SourcingGate()
    ctx = GateContext(trigger="ci", extra={"sourcing_paths": [str(md_file)]})
    report = gate.run(ctx)

    assert report.decision == Decision.PASS, (
        f"review-*.md 应豁免 W002，实际 decision={report.decision}, message={report.message}"
    )


def test_sourcing_exempts_w002_for_tasks_files(tmp_path):
    """given_tasks_subdir_when_run_then_w002_skipped。

    tasks/F-*.md 是任务清单，其数字断言通常复述 features.json 的 acceptance；
    源头追溯由 features.json 完成，tasks 文件不应再被 W002 卡住。
    """
    md_file = tmp_path / "tasks" / "F-001.md"
    _write_md(md_file, _md_with_w002_trigger())

    gate = plugin_mod.SourcingGate()
    ctx = GateContext(trigger="ci", extra={"sourcing_paths": [str(md_file)]})
    report = gate.run(ctx)

    assert report.decision == Decision.PASS, (
        f"tasks/*.md 应豁免 W002，实际 decision={report.decision}, message={report.message}"
    )


def test_sourcing_still_emits_w002_for_design_spec(tmp_path):
    """given_design_spec_filename_when_run_then_w002_warning_still_emitted。

    设计 spec 文档（detailed-design / requirement / outline-design / tech-feasibility）
    必须仍受 W002 约束——豁免范围不能扩大到 spec 文档。
    （strict 升级 warning→error 是 runner 层职责，本测试仅断言 plugin 仍发出 warning。）
    """
    md_file = tmp_path / "detailed-design.md"
    _write_md(md_file, _md_with_w002_trigger())

    gate = plugin_mod.SourcingGate()
    ctx = GateContext(trigger="ci", extra={"sourcing_paths": [str(md_file)]})
    report = gate.run(ctx)

    warnings = report.vars.get("warnings", []) if report.vars else []
    has_w002 = any("W002" in str(w) for w in warnings)
    assert has_w002, (
        f"detailed-design.md 应发出 W002 warning，实际 vars.warnings={warnings}"
    )


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


# ====================== skip 语义（F-003：搬到 runner filter_gates） ======================


def test_sourcing_filtered_on_pre_commit_without_artifact_change():
    """given_pre_commit_without_artifacts_md_when_filter_gates_then_excluded（skip fixture）."""
    import run as runner_mod
    data = runner_mod.load_registry()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["scripts/foo.py", "requirements/REQ-001/meta.yaml"],
    )
    ids = {e["id"] for e in runner_mod.filter_gates(data, ctx)}
    assert "GATE-SOURCING" not in ids


def test_sourcing_kept_when_artifacts_in_changed():
    """given_pre_commit_with_artifacts_change_when_filter_gates_then_included。"""
    import run as runner_mod
    data = runner_mod.load_registry()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["requirements/REQ-001/artifacts/requirement.md"],
    )
    ids = {e["id"] for e in runner_mod.filter_gates(data, ctx)}
    assert "GATE-SOURCING" in ids


def test_sourcing_precheck_returns_none_after_f003():
    """F-003 双轨清理后 precheck 不再过滤；保 None 返回行为契约。"""
    gate = plugin_mod.SourcingGate()
    ctx = GateContext(trigger="pre-commit", changed_files=["scripts/foo.py"])
    assert gate.precheck(ctx) is None
    ctx2 = GateContext(trigger="ci")
    assert gate.precheck(ctx2) is None


# ====================== _changed_artifact_paths 边界（IO 选路 helper） ======================
# F-003：原 _has_artifact_md_change 已删除（双轨清理）；保留 _changed_artifact_paths
# 测试，因为 run() 内 _resolve_targets 仍用它做 IO 选路。


def test_changed_artifact_paths_picks_nested():
    from plugins._helpers import _changed_artifact_paths
    paths = _changed_artifact_paths(["requirements/REQ-001/artifacts/tasks/F-001.md"])
    assert len(paths) == 1
    assert paths[0].name == "F-001.md"


def test_changed_artifact_paths_skips_meta_yaml():
    from plugins._helpers import _changed_artifact_paths
    assert _changed_artifact_paths(["requirements/REQ-001/meta.yaml"]) == []


# ====================== completed 需求 CI 豁免（REQ-2026-006/F-002 后续修复） ======================


def _make_req(req_root: Path, req_id: str, phase: str) -> Path:
    """在 tmp 下造一个最小需求骨架：meta.yaml + artifacts/requirement.md。"""
    req_dir = req_root / req_id
    artifacts = req_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (req_dir / "meta.yaml").write_text(
        f"id: {req_id}\nphase: {phase}\n", encoding="utf-8"
    )
    md = artifacts / "requirement.md"
    md.write_text(_valid_md(), encoding="utf-8")
    return md


def test_resolve_targets_skips_completed_reqs_in_ci(tmp_path, monkeypatch):
    """given_completed_req_when_ci_full_scan_then_excluded_from_targets（completed 档案豁免）。"""
    req_root = tmp_path / "requirements"
    req_root.mkdir()
    active_md = _make_req(req_root, "REQ-ACTIVE", "testing")
    completed_md = _make_req(req_root, "REQ-DONE", "completed")

    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    ctx = GateContext(trigger="ci")
    targets = plugin_mod._resolve_targets(ctx)

    assert active_md in targets
    assert completed_md not in targets


def test_resolve_targets_includes_completed_when_explicit(tmp_path, monkeypatch):
    """given_completed_req_when_explicit_sourcing_paths_then_kept（显式注入仍扫描）。"""
    req_root = tmp_path / "requirements"
    req_root.mkdir()
    completed_md = _make_req(req_root, "REQ-DONE", "completed")

    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    ctx = GateContext(trigger="ci", extra={"sourcing_paths": [str(completed_md)]})
    targets = plugin_mod._resolve_targets(ctx)

    assert targets == [Path(str(completed_md))]


def test_is_completed_req_handles_missing_meta(tmp_path):
    """given_artifact_without_meta_when_check_then_treated_as_active（保守策略）。"""
    req_root = tmp_path / "requirements"
    artifacts = req_root / "REQ-ORPHAN" / "artifacts"
    artifacts.mkdir(parents=True)
    md = artifacts / "requirement.md"
    md.write_text(_valid_md(), encoding="utf-8")

    assert plugin_mod._is_completed_req(md, req_root) is False
