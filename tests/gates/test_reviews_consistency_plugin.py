"""plugins/reviews_consistency.py 单测：覆盖 pass / fail-only-json / fail-only-meta / skip 四态。

外部依赖（git diff --cached 命令）通过 monkeypatch 模拟，不依赖真实 git 状态。
"""
from __future__ import annotations

from unittest.mock import patch

from plugins.base import Decision, GateContext
from plugins import reviews_consistency as plugin_mod


# ====================== 工具函数 ======================


def _make_ctx(changed_files: list[str], trigger: str = "pre-commit") -> GateContext:
    """构造用于测试的 GateContext。"""
    return GateContext(trigger=trigger, changed_files=changed_files)


def _mock_staged(files: list[str]):
    """mock _get_staged_files 返回指定列表。"""
    return patch.object(plugin_mod, "_get_staged_files", return_value=files)


def _mock_reviews_diff(result: bool):
    """mock _has_reviews_diff 返回 True/False。"""
    return patch.object(plugin_mod, "_has_reviews_diff", return_value=result)


# ====================== pass 用例 ======================


def test_reviews_consistency_passes_when_both_staged_together():
    """given_meta_and_reviews_json_both_staged_when_run_then_pass（pass fixture）。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = [
        "requirements/REQ-2026-002/meta.yaml",
        "requirements/REQ-2026-002/reviews/code-F-001-001.json",
    ]
    ctx = _make_ctx(staged)
    with _mock_staged(staged), _mock_reviews_diff(True):
        report = gate.run(ctx)
    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-REVIEWS-CONSISTENCY"


def test_reviews_consistency_passes_when_meta_staged_without_reviews_section_diff():
    """given_meta_staged_but_reviews_section_unchanged_when_run_then_pass。

    meta.yaml 被 staged 但 reviews: 段无 diff，不需要同步 reviews/*.json。
    """
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = ["requirements/REQ-2026-002/meta.yaml"]
    ctx = _make_ctx(staged)
    with _mock_staged(staged), _mock_reviews_diff(False):
        report = gate.run(ctx)
    assert report.decision == Decision.PASS


def test_reviews_consistency_passes_when_no_relevant_staged_files():
    """given_only_code_files_staged_when_run_then_pass（无 meta/reviews 文件）。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = ["scripts/gates/run.py", "tests/gates/test_runner.py"]
    ctx = _make_ctx(staged)
    with _mock_staged(staged):
        report = gate.run(ctx)
    assert report.decision == Decision.PASS


# ====================== fail-only-meta 用例 ======================


def test_reviews_consistency_fails_when_only_meta_reviews_section_changed():
    """given_meta_reviews_section_staged_but_no_json_when_run_then_fail（fail-only-meta）。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = ["requirements/REQ-2026-002/meta.yaml"]
    ctx = _make_ctx(staged)
    with _mock_staged(staged), _mock_reviews_diff(True):
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "REVIEWS-META-ONLY"
    assert "meta.yaml" in (report.message or "").lower() or "reviews" in (report.message or "").lower()


def test_reviews_consistency_fails_meta_only_includes_fix_hint():
    """fail-only-meta 时 fix_hint 应包含 save-review.sh 的指引。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = ["requirements/REQ-2026-002/meta.yaml"]
    ctx = _make_ctx(staged)
    with _mock_staged(staged), _mock_reviews_diff(True):
        report = gate.run(ctx)
    assert "save-review.sh" in (report.fix_hint or "")


# ====================== fail-only-json 用例 ======================


def test_reviews_consistency_fails_when_only_reviews_json_staged():
    """given_reviews_json_staged_but_meta_not_staged_when_run_then_fail（fail-only-json）。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = ["requirements/REQ-2026-002/reviews/code-F-001-001.json"]
    ctx = _make_ctx(staged)
    with _mock_staged(staged):
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "REVIEWS-JSON-ONLY"
    assert "meta.yaml" in (report.message or "")


def test_reviews_consistency_fails_json_only_includes_fix_hint():
    """fail-only-json 时 fix_hint 应包含 save-review.sh 的指引。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = ["requirements/REQ-2026-002/reviews/code-F-001-001.json"]
    ctx = _make_ctx(staged)
    with _mock_staged(staged):
        report = gate.run(ctx)
    assert "save-review.sh" in (report.fix_hint or "")


# ====================== skip 用例 ======================


def test_reviews_consistency_skips_on_non_precommit_trigger():
    """given_trigger_ci_when_precheck_then_skip（skip fixture：非 pre-commit）。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    ctx = _make_ctx(
        changed_files=["requirements/REQ-2026-002/meta.yaml"],
        trigger="ci",
    )
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "pre-commit" in skip.reason


def test_reviews_consistency_skips_when_no_meta_or_reviews_in_staged():
    """given_no_relevant_staged_files_when_precheck_then_skip（skip fixture：无相关文件）。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    ctx = _make_ctx(
        changed_files=["scripts/gates/run.py"],
        trigger="pre-commit",
    )
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "跳过" in skip.reason


def test_reviews_consistency_does_not_skip_when_meta_staged():
    """given_meta_yaml_staged_when_precheck_then_no_skip。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    ctx = _make_ctx(
        changed_files=["requirements/REQ-2026-002/meta.yaml"],
        trigger="pre-commit",
    )
    skip = gate.precheck(ctx)
    assert skip is None


def test_reviews_consistency_does_not_skip_when_reviews_json_staged():
    """given_reviews_json_staged_when_precheck_then_no_skip。"""
    gate = plugin_mod.ReviewsConsistencyGate()
    ctx = _make_ctx(
        changed_files=["requirements/REQ-2026-002/reviews/code-F-001-001.json"],
        trigger="pre-commit",
    )
    skip = gate.precheck(ctx)
    assert skip is None


# ====================== 边界用例 ======================


def test_reviews_consistency_different_req_dirs_are_checked_independently():
    """given_two_different_reqs_staged_independently_when_run_then_fail_for_orphaned_one。

    REQ-A 的 reviews/*.json 与 REQ-B 的 meta.yaml 不构成互相满足。
    """
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = [
        "requirements/REQ-2026-001/meta.yaml",
        "requirements/REQ-2026-002/reviews/code-F-001-001.json",
    ]
    ctx = _make_ctx(staged)
    # REQ-001 meta 有 reviews diff，REQ-002 json 无对应 meta
    with _mock_staged(staged), _mock_reviews_diff(True):
        report = gate.run(ctx)
    # REQ-001 正向失败（无对应 reviews json）或 REQ-002 反向失败（无对应 meta）
    assert report.decision == Decision.FAIL
