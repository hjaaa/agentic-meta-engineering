"""R003 / R007 升级单测：旧 verdict 无 human_signoff 字段时必须被阻断。

验收要求：
  - 旧 verdict（有 latest 但无 human_signoff）→ R003 finding，report.errors > 0
  - conclusion=rejected（旧 schema）→ R003 finding
  - R007：code by_feature 中旧 verdict 无 human_signoff → R007 finding

来源：requirements/REQ-2026-003/artifacts/detailed-design.md §F-004.4 / TC-B13
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 注入 scripts/lib 到 path
_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from check_reviews import _r003_blocked_or_unsigned, _r007_code_by_feature_coverage  # noqa: E402
from common import Report, Severity  # noqa: E402

# 测试用 REQ ID
_REQ = "REQ-2099-TEST"


def _write_verdict(reviews_dir: Path, filename: str, verdict: dict) -> None:
    """向 reviews 目录写入 verdict JSON 文件。"""
    reviews_dir.mkdir(parents=True, exist_ok=True)
    (reviews_dir / filename).write_text(json.dumps(verdict), encoding="utf-8")


def _make_base_verdict(phase: str = "definition", conclusion: str = "looks_clean") -> dict:
    """生成基础 verdict，不含 human_signoff（模拟旧 schema）。"""
    return {
        "schema_version": "1.0",
        "review_id": f"REV-{_REQ}-{phase}-001",
        "requirement_id": _REQ,
        "phase": phase,
        "reviewer": "requirement-quality-reviewer",
        "reviewed_at": "2026-04-30 10:00:00",
        "reviewed_commit": "abc1234",
        "reviewed_artifacts": [],
        "conclusion": conclusion,
        "score": 85,
        "dimensions": {},
        "required_fixes": [],
        "suggestions": [],
        "scope": None,
        "supersedes": None,
        # 不含 human_signoff → 旧 verdict
    }


class TestR003BlockedOrUnsigned:
    """_r003_blocked_or_unsigned 测试套件。"""

    def test_should_error_when_old_verdict_without_human_signoff_given_old_verdict_schema(self, tmp_path: Path) -> None:
        """旧 verdict 无 human_signoff → R003 报错，禁止切阶段。"""
        # 构造临时仓库结构：requirements/<REQ>/reviews/definition-001.json
        reviews_dir = tmp_path / "requirements" / _REQ / "reviews"
        verdict = _make_base_verdict(phase="definition", conclusion="looks_clean")
        _write_verdict(reviews_dir, "definition-001.json", verdict)

        # meta.yaml 的 reviews 段
        meta = {
            "reviews": {
                "definition": {
                    "latest": f"REV-{_REQ}-definition-001",
                    "conclusion": "looks_clean",
                }
            }
        }

        # 临时覆盖 REQUIREMENTS_DIR
        import check_reviews as cr
        original_dir = cr.REQUIREMENTS_DIR
        cr.REQUIREMENTS_DIR = tmp_path / "requirements"
        try:
            report = Report()
            _r003_blocked_or_unsigned(meta, ["definition"], report, _REQ, _REQ)
        finally:
            cr.REQUIREMENTS_DIR = original_dir

        errors = [f for f in report.findings() if f[1] == Severity.ERROR and f[2] == "R003"]
        assert len(errors) > 0, "旧 verdict 无 human_signoff 应触发 R003"
        assert any("未签字" in f[3] or "human_signoff" in f[3] for f in errors)

    def test_should_error_when_conclusion_rejected_given_blocked_meta(self, tmp_path: Path) -> None:
        """旧 schema conclusion=rejected 直接触发 R003（无需读 verdict 文件）。"""
        meta = {
            "reviews": {
                "definition": {
                    "latest": f"REV-{_REQ}-definition-001",
                    "conclusion": "rejected",  # 旧 schema
                }
            }
        }
        report = Report()
        _r003_blocked_or_unsigned(meta, ["definition"], report, _REQ, _REQ)

        errors = [f for f in report.findings() if f[1] == Severity.ERROR and f[2] == "R003"]
        assert len(errors) > 0, "conclusion=rejected 应触发 R003"

    def test_should_error_when_conclusion_blocked_given_blocked_conclusion(self, tmp_path: Path) -> None:
        """新 schema conclusion=blocked 也触发 R003。"""
        meta = {
            "reviews": {
                "definition": {
                    "latest": f"REV-{_REQ}-definition-001",
                    "conclusion": "blocked",
                }
            }
        }
        report = Report()
        _r003_blocked_or_unsigned(meta, ["definition"], report, _REQ, _REQ)

        errors = [f for f in report.findings() if f[1] == Severity.ERROR and f[2] == "R003"]
        assert len(errors) > 0, "conclusion=blocked 应触发 R003"

    def test_should_pass_when_signed_verdict_given_valid_human_signoff(self, tmp_path: Path) -> None:
        """verdict 含合法 human_signoff.decision=approved → R003 通过。"""
        reviews_dir = tmp_path / "requirements" / _REQ / "reviews"
        verdict = _make_base_verdict(phase="definition", conclusion="looks_clean")
        verdict["human_signoff"] = {
            "decision": "approved",
            "signed_at": "2026-04-30T14:00:00+0800",
            "signed_by": "dev@example.com",
            "source": "cli-tty",
        }
        _write_verdict(reviews_dir, "definition-001.json", verdict)

        meta = {
            "reviews": {
                "definition": {
                    "latest": f"REV-{_REQ}-definition-001",
                    "conclusion": "looks_clean",
                }
            }
        }

        import check_reviews as cr
        original_dir = cr.REQUIREMENTS_DIR
        cr.REQUIREMENTS_DIR = tmp_path / "requirements"
        try:
            report = Report()
            _r003_blocked_or_unsigned(meta, ["definition"], report, _REQ, _REQ)
        finally:
            cr.REQUIREMENTS_DIR = original_dir

        errors = [f for f in report.findings() if f[1] == Severity.ERROR and f[2] == "R003"]
        assert len(errors) == 0, f"已签字 verdict 不应触发 R003，实际 findings: {errors}"


class TestR007CodeByFeatureCoverage:
    """_r007_code_by_feature_coverage 升级测试套件。"""

    def _make_features_json(self, features_dir: Path, fid: str = "F-001") -> None:
        """构造 features.json，含一个 status=done 的 feature。"""
        features_dir.mkdir(parents=True, exist_ok=True)
        content = {
            "features": [
                {"id": fid, "status": "done", "title": "测试 feature"}
            ]
        }
        (features_dir / "features.json").write_text(json.dumps(content), encoding="utf-8")

    def test_should_error_when_code_verdict_without_human_signoff_given_old_code_verdict(self, tmp_path: Path) -> None:
        """code by_feature verdict 无 human_signoff → R007 报错。"""
        fid = "F-001"
        req_dir = tmp_path / "requirements" / _REQ
        reviews_dir = req_dir / "reviews"
        artifacts_dir = req_dir / "artifacts"

        # 写 features.json
        self._make_features_json(artifacts_dir, fid)

        # 写 code verdict（无 human_signoff）
        verdict_fname = f"code-{fid}-001.json"
        verdict = {
            "schema_version": "1.0",
            "review_id": f"REV-{_REQ}-code-{fid}-001",
            "requirement_id": _REQ,
            "phase": "code",
            "conclusion": "looks_clean",
            "score": 90,
            "human_signoff": None,  # 旧 verdict 缺 human_signoff
        }
        reviews_dir.mkdir(parents=True, exist_ok=True)
        (reviews_dir / verdict_fname).write_text(json.dumps(verdict), encoding="utf-8")

        meta = {
            "reviews": {
                "code": {
                    "by_feature": {
                        fid: {
                            "latest": f"REV-{_REQ}-code-{fid}-001",
                            "conclusion": "looks_clean",
                        }
                    }
                }
            }
        }

        import check_reviews as cr
        original_dir = cr.REQUIREMENTS_DIR
        cr.REQUIREMENTS_DIR = tmp_path / "requirements"
        try:
            report = Report()
            _r007_code_by_feature_coverage(meta, "testing", report, _REQ, _REQ)
        finally:
            cr.REQUIREMENTS_DIR = original_dir

        errors = [f for f in report.findings() if f[1] == Severity.ERROR and f[2] == "R007"]
        assert len(errors) > 0, "code verdict 无 human_signoff 应触发 R007"
