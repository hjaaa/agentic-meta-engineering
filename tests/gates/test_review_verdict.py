"""plugins/review_verdict.py 新增测试（F-001 B 案：--draft 模式跳过 review-verdict）。

与既有 test_review_verdict_plugin.py 并存；不改既有文件，保留其回归基线。

覆盖：
  - test_skip_on_draft_submit：trigger=submit + draft=True → precheck 返回 Skip
  - test_no_skip_on_phase_transition_with_draft：trigger=phase-transition + draft=True → 不 skip
  - test_no_skip_when_draft_unset：cli_flags={} → 不 skip（走原路径）
"""
from __future__ import annotations

import pytest

from plugins.base import GateContext, Skip
from plugins import review_verdict as plugin_mod


# ====================== draft skip 场景 ======================


def test_skip_on_draft_submit():
    """given_submit_draft_true_when_precheck_then_skip。

    submit + cli_flags.draft=True → B 案放宽：返回 Skip，不再跑 review-verdict 校验。
    """
    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="submit",
        requirement_id="REQ-2026-999",
        cli_flags={"draft": True},
    )
    result = gate.precheck(ctx)
    assert result is not None
    assert isinstance(result, Skip)
    assert "--draft" in result.reason


def test_no_skip_on_phase_transition_with_draft():
    """given_phase_transition_draft_true_when_precheck_then_not_skip_by_draft。

    draft flag 仅对 submit trigger 有效；phase-transition 继续走原校验路径（返回 None 或
    其他 Skip，但不是因 draft 导致的 Skip）。
    本测试只断言 draft 分支不触发，不断言后续 precheck 分支的具体行为。
    """
    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-999",
        to_phase="tech-research",
        cli_flags={"draft": True},
        meta={},
    )
    result = gate.precheck(ctx)
    # draft 分支不应触发：若有 Skip，reason 不应包含 "--draft"
    if result is not None:
        assert "--draft" not in result.reason, (
            f"phase-transition + draft=True 不应触发 draft Skip，但 reason={result.reason!r}"
        )


def test_no_skip_when_draft_unset():
    """given_cli_flags_empty_when_precheck_submit_then_not_draft_skip。

    cli_flags={} → draft 默认 False → 不走 B 案 skip 路径。
    需要 requirement_id（避免被 requirement_id 缺失的 skip 提前截断，掩盖 draft 路径）。
    """
    gate = plugin_mod.ReviewVerdictGate()
    ctx = GateContext(
        trigger="submit",
        requirement_id="REQ-2026-999",
        cli_flags={},
    )
    result = gate.precheck(ctx)
    # draft 分支不触发；但 precheck 可能返回其他 Skip（如 legacy），此处仅断言 draft 原因不出现
    if result is not None:
        assert "--draft" not in result.reason, (
            f"draft=False 不应触发 draft Skip，但 reason={result.reason!r}"
        )
