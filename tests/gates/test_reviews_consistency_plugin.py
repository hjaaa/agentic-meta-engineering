"""plugins/reviews_consistency.py 单测：覆盖 pass / fail-only-json / fail-only-meta / skip 四态。

外部依赖（git diff --cached 命令）通过 monkeypatch 模拟，不依赖真实 git 状态。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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


# ====================== F-r2-01/02/06 补充用例 ======================


def test_run_returns_fail_when_get_staged_files_returns_none():
    """given_get_staged_files_returns_none_when_run_then_fail_with_git_fail_code。

    _get_staged_files 返回 None（git 命令失败）时，run() 应返回 REVIEWS-GIT-FAIL。
    ctx.changed_files 为空，迫使 run() 调用 _get_staged_files。
    """
    gate = plugin_mod.ReviewsConsistencyGate()
    # 包含相关文件，让 precheck 不 skip；ctx.changed_files 用于 precheck，run 内用 _get_staged_files
    ctx = _make_ctx(changed_files=["requirements/REQ-2026-002/meta.yaml"])
    # ctx.changed_files 非空时 run() 优先使用它，需清空以走 _get_staged_files 路径
    ctx_empty = _make_ctx(changed_files=[])
    with patch.object(plugin_mod, "_get_staged_files", return_value=None):
        report = gate.run(ctx_empty)
    assert report.decision == Decision.FAIL
    assert report.code == "REVIEWS-GIT-FAIL"
    assert "git" in (report.fix_hint or "").lower() or "git" in (report.message or "").lower()


def test_run_uses_ctx_changed_files_when_available():
    """given_ctx_changed_files_set_when_run_then_no_git_call。

    ctx.changed_files 非空时，run() 直接使用而不调 git，
    确保数据源与 precheck 统一（F-r2-02 修复验证）。
    """
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = [
        "requirements/REQ-2026-002/meta.yaml",
        "requirements/REQ-2026-002/reviews/code-F-001-001.json",
    ]
    ctx = _make_ctx(staged)
    # _get_staged_files 不应被调用
    with patch.object(plugin_mod, "_get_staged_files") as mock_git, \
         _mock_reviews_diff(True):
        report = gate.run(ctx)
    mock_git.assert_not_called()
    assert report.decision == Decision.PASS


def test_has_reviews_diff_returns_true_on_nonzero_returncode():
    """given_git_returns_nonzero_when_has_reviews_diff_then_return_true_conservatively。

    git diff 非零退出时，_has_reviews_diff 应保守返回 True 触发后续校验（F-r2-06 修复验证）。
    """
    mock_result = MagicMock()
    mock_result.returncode = 128  # git 错误码（如非 git 仓库）
    mock_result.stderr = "fatal: not a git repository"
    with patch("subprocess.run", return_value=mock_result):
        result = plugin_mod._has_reviews_diff("requirements/REQ-2026-002/meta.yaml")
    assert result is True


def test_fix_hint_does_not_claim_ci_will_intercept():
    """given_meta_reviews_only_staged_when_fail_then_fix_hint_no_ci_intercept_claim。

    fix_hint 不应声称'CI 仍会拦截'——本 gate 仅 pre-commit 触发，CI 不兜底（F-r2-01 修复验证）。
    """
    gate = plugin_mod.ReviewsConsistencyGate()
    staged = ["requirements/REQ-2026-002/meta.yaml"]
    ctx = _make_ctx(staged)
    with _mock_staged(staged), _mock_reviews_diff(True):
        report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    # 确认 fix_hint 不再包含"CI 仍会拦截"的矛盾承诺
    assert "CI 仍会拦截" not in (report.fix_hint or "")
