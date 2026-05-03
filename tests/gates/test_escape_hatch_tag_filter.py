"""F-004 / TC-FG4-2 / FG-004 _handle_escape_hatch tag 限定测试。

覆盖：
  - 命中：失败 gate.tags ∩ escape.skips_gates_with_tag ≠ ∅ → force_used=True
  - 未命中：失败 gate 无 tag / tag 不交集 → 走 rollback（force_used=False）
  - safe default：registry_data=None → 视为空集 → 不命中
  - registry 中 escape_hatch 缺 skips_gates_with_tag 字段 → 视为空集 → 不命中
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# 复用 test_run_force_with_blockers 的 sys.path 注入
import tests.gates.test_run_force_with_blockers as _bootstrap  # noqa: F401

from plugins.base import GateContext
import run as runner_mod


def _make_ctx(reason="临时绕过：F-004 测试"):
    return GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2099-001",
        cli_flags={"force_with_blockers": reason},
        meta={},
        extra={},
        changed_files=[],
        env={},
    )


def _make_gate_fail(gate_id):
    gate_fail = MagicMock()
    gate_fail.report.gate_id = gate_id
    return gate_fail


def _make_registry(failed_gate_id, gate_tags, skips_tags):
    return {
        "gates": [{"id": failed_gate_id, "tags": gate_tags}],
        "escape_hatches": [
            {"id": "force-with-blockers", "skips_gates_with_tag": skips_tags},
        ],
    }


# ====================== 命中 ======================


def test_escape_hatch_hits_when_tag_intersection_nonempty():
    """review-verdict ∈ gate.tags ∩ escape.skips → 放行。"""
    ctx = _make_ctx()
    gate_fail = _make_gate_fail("GATE-REVIEW-VERDICT")
    registry = _make_registry("GATE-REVIEW-VERDICT", ["review-verdict"], ["review-verdict"])

    force_used, rollback_failed = runner_mod._handle_escape_hatch(
        ctx, gate_fail, executed=[], snapshots={}, registry_data=registry,
    )
    assert force_used is True
    assert rollback_failed is False


# ====================== 未命中 ======================


def test_escape_hatch_misses_when_failed_gate_has_no_tag():
    """workspace_clean fail（无 tag）+ force-with-blockers → 不放行（TC-FG4-2 核心）。"""
    ctx = _make_ctx()
    gate_fail = _make_gate_fail("GATE-WORKSPACE-CLEAN")
    registry = _make_registry("GATE-WORKSPACE-CLEAN", [], ["review-verdict"])

    force_used, _ = runner_mod._handle_escape_hatch(
        ctx, gate_fail, executed=[], snapshots={}, registry_data=registry,
    )
    assert force_used is False, "无 tag 的 gate 不应被 force-with-blockers 放行"


def test_escape_hatch_misses_when_tags_disjoint():
    """gate.tags=[other-tag]，与 skips_gates_with_tag=[review-verdict] 不交集 → 不放行。"""
    ctx = _make_ctx()
    gate_fail = _make_gate_fail("GATE-WHATEVER")
    registry = _make_registry("GATE-WHATEVER", ["other-tag"], ["review-verdict"])

    force_used, _ = runner_mod._handle_escape_hatch(
        ctx, gate_fail, executed=[], snapshots={}, registry_data=registry,
    )
    assert force_used is False


def test_escape_hatch_safe_default_when_registry_data_is_none():
    """registry_data=None → tag 集合空 → 必然不命中（safe default）。"""
    ctx = _make_ctx()
    gate_fail = _make_gate_fail("GATE-REVIEW-VERDICT")

    force_used, _ = runner_mod._handle_escape_hatch(
        ctx, gate_fail, executed=[], snapshots={}, registry_data=None,
    )
    assert force_used is False, "registry_data=None 时必须 safe default = 不放行"


def test_escape_hatch_misses_when_escape_lacks_skips_field():
    """registry 中 escape_hatch 没写 skips_gates_with_tag → 视为空集 → 不放行。"""
    ctx = _make_ctx()
    gate_fail = _make_gate_fail("GATE-REVIEW-VERDICT")
    registry = {
        "gates": [{"id": "GATE-REVIEW-VERDICT", "tags": ["review-verdict"]}],
        "escape_hatches": [{"id": "force-with-blockers"}],  # 无 skips_gates_with_tag
    }

    force_used, _ = runner_mod._handle_escape_hatch(
        ctx, gate_fail, executed=[], snapshots={}, registry_data=registry,
    )
    assert force_used is False


# ====================== trigger 限制 ======================


@pytest.mark.parametrize("trigger", ["ci", "post-dev", "pre-commit", "pre-tool-use"])
def test_escape_hatch_only_active_on_phase_transition_or_submit(trigger):
    """非 phase-transition/submit trigger 时，即便 reason + tag 命中也不放行。"""
    ctx = _make_ctx()
    ctx.trigger = trigger
    gate_fail = _make_gate_fail("GATE-REVIEW-VERDICT")
    registry = _make_registry("GATE-REVIEW-VERDICT", ["review-verdict"], ["review-verdict"])

    force_used, _ = runner_mod._handle_escape_hatch(
        ctx, gate_fail, executed=[], snapshots={}, registry_data=registry,
    )
    assert force_used is False
