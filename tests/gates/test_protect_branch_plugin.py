"""plugins/protect_branch.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（git branch 命令）通过 monkeypatch 模拟。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from plugins.base import Decision, GateContext
from plugins import protect_branch as plugin_mod


# ====================== pass 用例 ======================


def test_protect_branch_passes_on_feature_branch_non_review_file():
    """given_edit_on_feature_branch_non_review_file_when_run_then_pass（pass fixture）."""
    gate = plugin_mod.ProtectBranchGate()
    ctx = GateContext(
        trigger="pre-tool-use",
        extra={"tool_name": "Edit", "file_path": "scripts/foo.py"},
        env={"CLAUDE_HOOK_BRANCH": "feat/req-2026-002"},
    )
    report = gate.run(ctx)
    assert report.decision == Decision.PASS
    assert report.gate_id == "GATE-PROTECT-BRANCH"


def test_protect_branch_passes_on_custom_protected_branches_not_matching():
    """given_custom_protected_branches_not_matching_current_when_run_then_pass。"""
    gate = plugin_mod.ProtectBranchGate()
    ctx = GateContext(
        trigger="pre-tool-use",
        extra={"tool_name": "Write", "file_path": "context/INDEX.md"},
        env={"CLAUDE_HOOK_BRANCH": "feature-x", "CLAUDE_PROTECTED_BRANCHES": "main,develop"},
    )
    report = gate.run(ctx)
    assert report.decision == Decision.PASS


# ====================== fail 用例 ======================


def test_protect_branch_fails_on_protected_branch_edit():
    """given_edit_on_protected_branch_when_run_then_fail（fail fixture, PROTECT-BRANCH）."""
    gate = plugin_mod.ProtectBranchGate()
    ctx = GateContext(
        trigger="pre-tool-use",
        extra={"tool_name": "Edit", "file_path": "context/INDEX.md"},
        env={"CLAUDE_HOOK_BRANCH": "develop"},
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "PROTECT-BRANCH"
    assert "develop" in (report.message or "")


def test_protect_branch_fails_on_reviews_json_write():
    """given_write_to_reviews_json_any_branch_when_run_then_fail（fail fixture, PROTECT-REVIEWS）."""
    gate = plugin_mod.ProtectBranchGate()
    ctx = GateContext(
        trigger="pre-tool-use",
        extra={
            "tool_name": "Edit",
            "file_path": "requirements/REQ-2026-002/reviews/code-001.json",
        },
        env={"CLAUDE_HOOK_BRANCH": "feat/something"},
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "PROTECT-REVIEWS"
    assert "reviews" in (report.message or "").lower()


def test_protect_branch_fails_write_on_main():
    gate = plugin_mod.ProtectBranchGate()
    ctx = GateContext(
        trigger="pre-tool-use",
        extra={"tool_name": "Write", "file_path": "scripts/new_file.py"},
        env={"CLAUDE_HOOK_BRANCH": "main"},
    )
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "PROTECT-BRANCH"


# ====================== skip 用例 ======================


def test_protect_branch_skips_on_non_write_tool():
    """given_read_tool_when_precheck_then_skip（skip fixture）."""
    gate = plugin_mod.ProtectBranchGate()
    ctx = GateContext(
        trigger="pre-tool-use",
        extra={"tool_name": "Read", "file_path": "context/INDEX.md"},
    )
    skip = gate.precheck(ctx)
    assert skip is not None
    assert "not a write tool" in skip.reason


def test_protect_branch_skips_on_bash_tool():
    gate = plugin_mod.ProtectBranchGate()
    ctx = GateContext(
        trigger="pre-tool-use",
        extra={"tool_name": "Bash", "command": "echo hello"},
    )
    skip = gate.precheck(ctx)
    assert skip is not None


def test_protect_branch_does_not_skip_on_edit_tool():
    gate = plugin_mod.ProtectBranchGate()
    ctx = GateContext(
        trigger="pre-tool-use",
        extra={"tool_name": "Edit", "file_path": "context/INDEX.md"},
    )
    assert gate.precheck(ctx) is None


# ====================== _is_reviews_json 边界 ======================


def test_is_reviews_json_true():
    assert plugin_mod._is_reviews_json("requirements/REQ-001/reviews/foo.json")


def test_is_reviews_json_true_with_abs_path():
    assert plugin_mod._is_reviews_json("/Users/foo/repo/requirements/REQ-001/reviews/bar.json")


def test_is_reviews_json_false_for_meta():
    assert not plugin_mod._is_reviews_json("requirements/REQ-001/meta.yaml")


def test_is_reviews_json_false_empty():
    assert not plugin_mod._is_reviews_json("")
