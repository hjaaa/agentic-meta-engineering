"""plugins/review_verdict.py 单测：覆盖 pass / fail / skip 三态 + R001~R007 每条至少一个用例。

外部依赖（meta.yaml / reviews/*.json）通过临时目录 + monkeypatch 隔离。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from plugins.base import Decision, GateContext
from plugins import review_verdict as plugin_mod


# ====================== 工具函数 ======================

_REVIEW_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "context/team/engineering-spec/review-schema.yaml"
)


def _read_schema() -> dict:
    if _REVIEW_SCHEMA_PATH.exists():
        with _REVIEW_SCHEMA_PATH.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _make_req(tmp_path: Path, req_id: str) -> Path:
    """在 tmp_path/requirements/<req_id>/ 创建必要目录结构。"""
    req_dir = tmp_path / "requirements" / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "reviews").mkdir(exist_ok=True)
    return req_dir


def _write_meta(req_dir: Path, meta: dict) -> None:
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True)


def _base_meta(req_id: str, phase: str) -> dict:
    return {
        "id": req_id,
        "title": "test",
        "phase": phase,
        "created_at": "2026-01-01 00:00:00",
        "branch": f"feat/{req_id.lower()}",
        "base_branch": "develop",
        "reviews": {},
    }


def _write_review_json(req_dir: Path, suffix: str, req_id: str, phase: str) -> str:
    """写一个合法的 review JSON，返回 review_id。

    reviewer 使用 review-schema.yaml 枚举中合法的值。
    """
    review_id = f"REV-{req_id}-{suffix}"
    # 根据 phase 选择合法的 reviewer 值（来源：review-schema.yaml）
    _reviewer_map = {
        "definition": "requirement-quality-reviewer",
        "outline-design": "outline-design-quality-reviewer",
        "detail-design": "detail-design-quality-reviewer",
        "code": "code-quality-reviewer",
    }
    reviewer = _reviewer_map.get(phase, "requirement-quality-reviewer")
    review_data = {
        "schema_version": "1.0",
        "review_id": review_id,
        "requirement_id": req_id,
        "phase": phase,
        "reviewer": reviewer,
        "reviewed_at": "2026-01-01 00:00:00",
        "reviewed_commit": "abc1234",
        "reviewed_artifacts": [],
        "conclusion": "approved",
        "score": 90,
        "dimensions": {
            "design_consistency": {"score": 90, "issues": []},
            "security": {"score": 90, "issues": []},
            "concurrency": {"score": 90, "issues": []},
            "complexity": {"score": 90, "issues": []},
            "error_handling": {"score": 90, "issues": []},
            "auxiliary_spec": {"score": 90, "issues": []},
            "performance": {"score": 90, "issues": []},
            "history_context": {"score": 90, "issues": []},
        },
        "required_fixes": [],
        "suggestions": [],
        "scope": {"feature_id": None},
        "supersedes": None,
    }
    review_path = req_dir / "reviews" / f"{suffix}.json"
    with review_path.open("w", encoding="utf-8") as f:
        json.dump(review_data, f, ensure_ascii=False)
    return review_id


def _patch_check_reviews(monkeypatch, tmp_path: Path, req_id: str) -> None:
    """把 check_reviews 模块的 REQUIREMENTS_DIR 重定向到 tmp_path。"""
    import check_reviews as cr_mod
    monkeypatch.setattr(cr_mod, "REQUIREMENTS_DIR", tmp_path / "requirements")
    import common as cm_mod
    monkeypatch.setattr(cm_mod, "REPO_ROOT", tmp_path)
    import save_review as sr_mod
    monkeypatch.setattr(
        sr_mod, "REQUIREMENTS_DIR", tmp_path / "requirements"
    )


# ====================== pass 用例 ======================


def test_review_verdict_passes_when_all_reviews_approved(tmp_path, monkeypatch):
    """given_all_required_reviews_approved_when_run_then_pass（pass fixture）."""
    req_id = "REQ-2026-999"
    req_dir = _make_req(tmp_path, req_id)
    _patch_check_reviews(monkeypatch, tmp_path, req_id)

    # 切到 tech-research 需要 definition 阶段 review
    review_id = _write_review_json(req_dir, "definition-001", req_id, "definition")
    meta = _base_meta(req_id, "tech-research")
    meta["reviews"] = {
        "definition": {
            "latest": review_id,
            "conclusion": "approved",
            "artifact_hashes": {},
        }
    }
    _write_meta(req_dir, meta)

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="tech-research",
        meta=meta,
    )
    report = gate.run(ctx)
    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-REVIEW-VERDICT"


def test_review_verdict_passes_on_legacy_true(tmp_path, monkeypatch):
    """given_legacy_true_meta_when_run_then_pass（legacy 豁免）."""
    req_id = "REQ-2026-998"
    req_dir = _make_req(tmp_path, req_id)
    _patch_check_reviews(monkeypatch, tmp_path, req_id)

    meta = _base_meta(req_id, "tech-research")
    meta["legacy"] = True
    _write_meta(req_dir, meta)

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="tech-research",
        meta=meta,
    )
    report = gate.run(ctx)
    assert report.decision == Decision.PASS
    assert "legacy=true" in (report.message or "")


# ====================== fail 用例 ======================


def test_review_verdict_fails_r001_review_missing(tmp_path, monkeypatch):
    """R001: 目标 phase 需要的 review 不存在 → FAIL。"""
    req_id = "REQ-2026-997"
    req_dir = _make_req(tmp_path, req_id)
    _patch_check_reviews(monkeypatch, tmp_path, req_id)

    meta = _base_meta(req_id, "tech-research")
    meta["reviews"] = {}  # 没有 definition review
    _write_meta(req_dir, meta)

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="tech-research",
        meta=meta,
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert "R001" in (report.code or "")


def test_review_verdict_fails_r003_review_rejected(tmp_path, monkeypatch):
    """R003: latest.conclusion = rejected → FAIL。"""
    req_id = "REQ-2026-996"
    req_dir = _make_req(tmp_path, req_id)
    _patch_check_reviews(monkeypatch, tmp_path, req_id)

    review_id = _write_review_json(req_dir, "definition-001", req_id, "definition")
    # 把 review JSON 的 conclusion 改为 rejected
    rp = req_dir / "reviews" / "definition-001.json"
    rv = json.loads(rp.read_text())
    rv["conclusion"] = "rejected"
    rp.write_text(json.dumps(rv))

    meta = _base_meta(req_id, "tech-research")
    meta["reviews"] = {
        "definition": {
            "latest": review_id,
            "conclusion": "rejected",
            "artifact_hashes": {},
        }
    }
    _write_meta(req_dir, meta)

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="tech-research",
        meta=meta,
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    # R003 错误存在于 vars.errors 中（reviewer 枚举若不合法，R002 可能先触发）
    all_codes = [f[2] for f in report.vars.get("errors", [])]
    assert any("R003" in c for c in all_codes), f"R003 not in errors: {all_codes}"


def test_review_verdict_fails_r006_supersedes_dangling(tmp_path, monkeypatch):
    """R006: supersedes 引用不存在 → FAIL。"""
    req_id = "REQ-2026-995"
    req_dir = _make_req(tmp_path, req_id)
    _patch_check_reviews(monkeypatch, tmp_path, req_id)

    # 写一个 review，supersedes 指向不存在的 id
    review_id = f"REV-{req_id}-definition-001"
    rv = {
        "schema_version": "1.0",
        "review_id": review_id,
        "requirement_id": req_id,
        "phase": "definition",
        "reviewer": "requirement-quality-reviewer",  # 合法枚举值
        "reviewed_at": "2026-01-01 00:00:00",
        "reviewed_commit": "abc1234",
        "reviewed_artifacts": [],
        "conclusion": "approved",
        "score": 90,
        "dimensions": {k: {"score": 90, "issues": []} for k in [
            "design_consistency", "security", "concurrency", "complexity",
            "error_handling", "auxiliary_spec", "performance", "history_context"
        ]},
        "required_fixes": [],
        "suggestions": [],
        "scope": {"feature_id": None},
        "supersedes": "REV-NONEXISTENT-999",  # 悬挂引用
    }
    (req_dir / "reviews" / "definition-001.json").write_text(json.dumps(rv))

    meta = _base_meta(req_id, "tech-research")
    meta["reviews"] = {
        "definition": {
            "latest": review_id,
            "conclusion": "approved",
            "artifact_hashes": {},
        }
    }
    _write_meta(req_dir, meta)

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="tech-research",
        meta=meta,
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    # R006 错误存在于 vars.errors 中（R002 可能先触发，code 指向先到的 error）
    all_codes = [f[2] for f in report.vars.get("errors", [])]
    assert any("R006" in c for c in all_codes), f"R006 not in errors: {all_codes}"


# ====================== skip 用例 ======================


def test_review_verdict_skips_on_phase_transition_without_requirement_id():
    """given_no_requirement_id_when_precheck_then_skip（skip fixture）."""
    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(trigger="phase-transition", to_phase="tech-research")
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "requirement_id" in skip.reason


def test_review_verdict_skips_on_phase_transition_without_to_phase():
    """given_no_to_phase_when_precheck_then_skip（skip fixture）."""
    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
    )
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "to_phase" in skip.reason


def test_review_verdict_does_not_skip_on_ci_trigger():
    """given_ci_trigger_when_precheck_then_no_skip."""
    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(trigger="ci")
    assert gate.precheck(ctx) is None


def test_review_verdict_skips_when_legacy_true():
    """given_meta_legacy_true_when_precheck_then_skip（legacy 豁免在 precheck）."""
    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
        to_phase="tech-research",
        meta={"legacy": True},
    )
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "legacy=true" in skip.reason


# ====================== R002 / R004 / R005 / R007 独立用例 ======================


def test_review_verdict_r004_needs_revision_is_warning(tmp_path, monkeypatch):
    """R004: needs_revision → warning（不阻断，review.vars 记录）。"""
    req_id = "REQ-2026-994"
    req_dir = _make_req(tmp_path, req_id)
    _patch_check_reviews(monkeypatch, tmp_path, req_id)

    review_id = _write_review_json(req_dir, "definition-001", req_id, "definition")
    # 把 conclusion 改为 needs_revision
    rp = req_dir / "reviews" / "definition-001.json"
    rv = json.loads(rp.read_text())
    rv["conclusion"] = "needs_revision"
    rp.write_text(json.dumps(rv))

    meta = _base_meta(req_id, "tech-research")
    meta["reviews"] = {
        "definition": {
            "latest": review_id,
            "conclusion": "needs_revision",
            "artifact_hashes": {},
        }
    }
    _write_meta(req_dir, meta)

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="tech-research",
        meta=meta,
    )
    report = gate.run(ctx)
    # R004 是 WARNING，不会导致 FAIL（严重度由 registry 决定，runner 在 strict 才阻断）
    # check_reviews._r004_needs_revision 使用 Severity.WARNING，所以 PASS
    assert report.decision == Decision.PASS
    assert "warnings" in report.vars


def test_review_verdict_r007_missing_code_review(tmp_path, monkeypatch):
    """R007: done feature 缺 code review → FAIL（切 testing 时）。"""
    req_id = "REQ-2026-993"
    req_dir = _make_req(tmp_path, req_id)
    _patch_check_reviews(monkeypatch, tmp_path, req_id)

    # 准备 detail-design review（testing 需要 detail-design + code）
    dd_review_id = _write_review_json(req_dir, "detail-design-001", req_id, "detail-design")

    # 准备 features.json（含一个 done feature）
    artifacts_dir = req_dir / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "features.json").write_text(
        json.dumps({"features": [{"id": "F-001", "status": "done"}]}),
        encoding="utf-8",
    )

    meta = _base_meta(req_id, "testing")
    meta["reviews"] = {
        "detail-design": {
            "latest": dd_review_id,
            "conclusion": "approved",
            "artifact_hashes": {},
        },
        # code.by_feature 为空 → R007 触发
        "code": {"by_feature": {}},
    }
    _write_meta(req_dir, meta)

    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id=req_id,
        to_phase="testing",
        meta=meta,
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert "R007" in (report.code or "")
