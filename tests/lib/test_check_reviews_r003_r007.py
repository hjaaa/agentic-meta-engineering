"""R003 / R007 退化测试（F-002 remove human sign-off）。

新行为口径：
  - R003：仅判 conclusion ∈ {blocked, rejected} 即阻断；不再依赖 human_signoff
  - R007：仅判 done feature 有 latest code review 且 conclusion ∉ {blocked, rejected}
  - 缺 human_signoff 字段的 latest review 现在通过 R003 / R007

来源：spec docs/superpowers/specs/2026-05-19-remove-human-signoff-soft-confirmation-design.md:148-151
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
    """生成基础 verdict，不含 human_signoff（F-002 后字段不再被消费）。"""
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
    }


class TestR003BlockedOrUnsigned:
    """_r003_blocked_or_unsigned 退化测试套件（F-002 spec:148）。"""

    def test_should_pass_when_latest_review_missing_human_signoff_given_looks_clean(self, tmp_path: Path) -> None:
        """缺 human_signoff 字段的 latest review → R003 通过（F-002 新行为）。"""
        reviews_dir = tmp_path / "requirements" / _REQ / "reviews"
        verdict = _make_base_verdict(phase="definition", conclusion="looks_clean")
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
        assert len(errors) == 0, f"缺 human_signoff 的 looks_clean review 不应触发 R003，实际：{errors}"

    def test_should_error_when_conclusion_rejected_given_blocked_meta(self, tmp_path: Path) -> None:
        """旧 schema conclusion=rejected 直接触发 R003。"""
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

    def test_should_pass_when_conclusion_looks_clean_given_no_human_signoff_field(self, tmp_path: Path) -> None:
        """conclusion=looks_clean 且无 human_signoff → R003 通过（F-002 spec:148）。"""
        meta = {
            "reviews": {
                "definition": {
                    "latest": f"REV-{_REQ}-definition-001",
                    "conclusion": "looks_clean",
                }
            }
        }
        # 不写 verdict 文件——验证 R003 不再读取 verdict.human_signoff
        report = Report()
        _r003_blocked_or_unsigned(meta, ["definition"], report, _REQ, _REQ)

        errors = [f for f in report.findings() if f[1] == Severity.ERROR and f[2] == "R003"]
        assert len(errors) == 0, f"looks_clean 无 human_signoff 不应触发 R003，实际：{errors}"


class TestR007CodeByFeatureCoverage:
    """_r007_code_by_feature_coverage 退化测试套件（F-002 spec:151）。"""

    def _make_features_json(self, features_dir: Path, fid: str = "F-001") -> None:
        """构造 features.json，含一个 status=done 的 feature。"""
        features_dir.mkdir(parents=True, exist_ok=True)
        content = {
            "features": [
                {"id": fid, "status": "done", "title": "测试 feature"}
            ]
        }
        (features_dir / "features.json").write_text(json.dumps(content), encoding="utf-8")

    def test_should_pass_when_done_feature_has_looks_clean_latest_review(self, tmp_path: Path) -> None:
        """done feature 有 latest code review + conclusion=looks_clean → R007 通过（F-002 新行为）。"""
        fid = "F-001"
        req_dir = tmp_path / "requirements" / _REQ
        artifacts_dir = req_dir / "artifacts"

        self._make_features_json(artifacts_dir, fid)

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
        assert len(errors) == 0, f"looks_clean latest review 不应触发 R007，实际：{errors}"

    def test_should_error_when_code_review_conclusion_blocked(self, tmp_path: Path) -> None:
        """done feature 的 latest code review conclusion=blocked → R007 失败（F-002 spec:151）。"""
        fid = "F-001"
        req_dir = tmp_path / "requirements" / _REQ
        artifacts_dir = req_dir / "artifacts"

        self._make_features_json(artifacts_dir, fid)

        meta = {
            "reviews": {
                "code": {
                    "by_feature": {
                        fid: {
                            "latest": f"REV-{_REQ}-code-{fid}-001",
                            "conclusion": "blocked",
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
        assert len(errors) > 0, "conclusion=blocked 应触发 R007"

    def test_should_error_when_code_review_conclusion_rejected(self, tmp_path: Path) -> None:
        """done feature 的 latest code review conclusion=rejected（旧 schema）→ R007 失败。"""
        fid = "F-001"
        req_dir = tmp_path / "requirements" / _REQ
        artifacts_dir = req_dir / "artifacts"

        self._make_features_json(artifacts_dir, fid)

        meta = {
            "reviews": {
                "code": {
                    "by_feature": {
                        fid: {
                            "latest": f"REV-{_REQ}-code-{fid}-001",
                            "conclusion": "rejected",
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
        assert len(errors) > 0, "conclusion=rejected 应触发 R007"

    def test_should_error_when_done_feature_missing_latest(self, tmp_path: Path) -> None:
        """done feature 缺 latest code review → R007 失败。"""
        fid = "F-001"
        req_dir = tmp_path / "requirements" / _REQ
        artifacts_dir = req_dir / "artifacts"

        self._make_features_json(artifacts_dir, fid)

        meta = {
            "reviews": {
                "code": {
                    "by_feature": {
                        fid: {
                            # latest 缺失
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
        assert len(errors) > 0, "缺 latest 应触发 R007"
