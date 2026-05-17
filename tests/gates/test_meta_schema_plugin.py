"""plugins/meta_schema.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（meta-schema.yaml / areas.yaml / 真实 requirements/）必须 mock。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from plugins.base import Decision, GateContext
from plugins import meta_schema as plugin_mod


# ====================== fixture：临时 meta.yaml ======================


def _write_meta(path: Path, body: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(body, f, allow_unicode=True)


def _valid_meta(req_id: str = "REQ-2026-999") -> dict:
    """合法的 bootstrap 阶段 meta.yaml（语义字段允许空）。"""
    return {
        "id": req_id,
        "title": "test",
        "phase": "bootstrap",
        "created_at": "2026-04-27 10:00:00",
        "branch": f"feat/{req_id.lower()}",
        "base_branch": "develop",
        "project": "agentic-meta-engineering",
        "services": ["agentic-meta-engineering"],
        "feature_area": "",
        "change_type": "",
        "affected_modules": [],
    }


# ====================== pass 用例 ======================


def test_meta_schema_passes_on_valid_meta(tmp_path):
    """given_valid_meta_when_run_then_pass（pass fixture）."""
    meta_file = tmp_path / "meta.yaml"
    _write_meta(meta_file, _valid_meta())

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_file)]})
    report = gate.run(ctx)

    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-META-SCHEMA"


# ====================== fail 用例 ======================


def test_meta_schema_fails_on_missing_required_field(tmp_path):
    """given_meta_missing_required_field_when_run_then_fail（fail fixture）."""
    meta = _valid_meta()
    del meta["title"]   # 故意去掉流程组必填字段
    meta_file = tmp_path / "meta.yaml"
    _write_meta(meta_file, meta)

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_file)]})
    report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "R-META"
    assert "title" in (report.message or "")


def test_meta_schema_fails_on_bad_id_format(tmp_path):
    meta = _valid_meta()
    meta["id"] = "not-a-req-id"
    meta_file = tmp_path / "meta.yaml"
    _write_meta(meta_file, meta)

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_file)]})
    report = gate.run(ctx)

    assert report.decision == Decision.FAIL
    assert report.code == "R-META"


# ====================== skip 语义（F-003：搬到 runner filter_gates） ======================
# 旧实现：plugin.precheck 在 pre-commit + 无 meta.yaml 改动时返回 Skip
# 新实现：runner filter_gates 通过 applies_when.changed_files=[requirements/*/meta.yaml] 过滤


def test_meta_schema_filtered_on_pre_commit_without_meta_change(tmp_path):
    """given_pre_commit_without_meta_change_when_filter_gates_then_excluded（skip fixture）."""
    import run as runner_mod
    data = runner_mod.load_registry()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["scripts/foo.py", "context/team/INDEX.md"],
    )
    ids = {e["id"] for e in runner_mod.filter_gates(data, ctx)}
    assert "GATE-META-SCHEMA" not in ids


def test_meta_schema_kept_when_meta_in_changed(tmp_path):
    """given_pre_commit_with_meta_change_when_filter_gates_then_included。"""
    import run as runner_mod
    data = runner_mod.load_registry()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["requirements/REQ-2026-002/meta.yaml"],
    )
    ids = {e["id"] for e in runner_mod.filter_gates(data, ctx)}
    assert "GATE-META-SCHEMA" in ids


def test_meta_schema_precheck_returns_none_after_f003():
    """F-003 双轨清理后 precheck 不再过滤；保 None 返回行为契约。"""
    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="pre-commit", changed_files=["scripts/foo.py"])
    assert gate.precheck(ctx) is None
    ctx2 = GateContext(trigger="ci")
    assert gate.precheck(ctx2) is None


# ====================== adapter 入参透传 ======================


def test_meta_schema_uses_extra_meta_paths(tmp_path):
    """ctx.extra['meta_paths'] 必须优先于 requirement_id / 兜底扫描。"""
    valid_file = tmp_path / "ok.yaml"
    _write_meta(valid_file, _valid_meta("REQ-2026-998"))

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(valid_file)]})
    report = gate.run(ctx)
    assert report.decision == Decision.PASS
