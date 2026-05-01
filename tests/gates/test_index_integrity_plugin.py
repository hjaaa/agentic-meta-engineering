"""plugins/index_integrity.py 单测：覆盖 pass / fail / skip 三态。

外部依赖（context/ / requirements/ 真实 INDEX.md）通过 monkeypatch 重定向到
临时目录后再 import；不动真实 repo。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from plugins.base import Decision, GateContext
from plugins import index_integrity as plugin_mod


# ====================== fixture：临时 INDEX.md 与 scan_roots ======================


@pytest.fixture
def tmp_scan_root(tmp_path: Path, monkeypatch):
    """造一个完整的 scan root（含 INDEX.md），并把 check_index 全局指针指过去。"""
    # 复用 plugin 内部已 import 的 check_index 模块（避免重复 import 冲突）
    import check_index as ci_mod

    root = tmp_path / "ctx"
    root.mkdir()

    monkeypatch.setattr(ci_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ci_mod, "_load_config", lambda: {
        "scan_roots": ["ctx"],
        "ignore": ["**/INDEX.md"],
        "warn_line_limit": 10000,
        "sibling_scan_depth": 1,
    })
    # common.REPO_ROOT 也得跟着改（rel() 会用）
    import common as common_mod
    monkeypatch.setattr(common_mod, "REPO_ROOT", tmp_path)
    return root


# ====================== pass 用例 ======================


def test_index_integrity_passes_on_well_formed_index(tmp_scan_root: Path):
    """given_index_with_existing_links_when_run_then_pass（pass fixture）."""
    target = tmp_scan_root / "real.md"
    target.write_text("# real\n\n内容\n", encoding="utf-8")

    index = tmp_scan_root / "INDEX.md"
    index.write_text(
        "# Index\n\n- [real](real.md)\n",
        encoding="utf-8",
    )

    gate = plugin_mod.IndexIntegrityGate()
    ctx = GateContext(trigger="ci")
    report = gate.run(ctx)
    assert report.decision == Decision.PASS


# ====================== fail 用例 ======================


def test_index_integrity_fails_on_broken_link(tmp_scan_root: Path):
    """given_index_with_dangling_link_when_run_then_fail（fail fixture）."""
    index = tmp_scan_root / "INDEX.md"
    index.write_text(
        "# Index\n\n- [missing](does-not-exist.md)\n",
        encoding="utf-8",
    )

    gate = plugin_mod.IndexIntegrityGate()
    ctx = GateContext(trigger="ci")
    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-INDEX"
    assert "does-not-exist" in (report.message or "")


# ====================== skip 语义（F-003：搬到 runner filter_gates） ======================
# 旧实现：plugin.precheck 在 pre-commit + 无 md 改动时返回 Skip
# 新实现：runner filter_gates 通过 applies_when.changed_files 过滤掉该 gate
# 测试断言对象从 plugin.precheck 变为 runner.filter_gates


def test_index_integrity_filtered_on_pre_commit_without_md_changes():
    """given_pre_commit_without_md_change_when_filter_gates_then_excluded（skip fixture）."""
    import run as runner_mod
    data = runner_mod.load_registry()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["scripts/foo.sh", "Makefile"],
    )
    ids = {e["id"] for e in runner_mod.filter_gates(data, ctx)}
    assert "GATE-INDEX-INTEGRITY" not in ids


def test_index_integrity_kept_when_md_in_changed():
    """given_pre_commit_with_index_md_change_when_filter_gates_then_included。"""
    import run as runner_mod
    data = runner_mod.load_registry()
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["context/team/INDEX.md"],
    )
    ids = {e["id"] for e in runner_mod.filter_gates(data, ctx)}
    assert "GATE-INDEX-INTEGRITY" in ids


def test_index_integrity_precheck_returns_none_after_f003():
    """F-003 双轨清理后 precheck 不再过滤；保 None 返回行为契约。"""
    gate = plugin_mod.IndexIntegrityGate()
    ctx = GateContext(trigger="pre-commit", changed_files=["scripts/foo.sh"])
    assert gate.precheck(ctx) is None
    ctx2 = GateContext(trigger="ci")
    assert gate.precheck(ctx2) is None
