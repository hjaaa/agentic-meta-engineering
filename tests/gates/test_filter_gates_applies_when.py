"""F-003 · TC-FG3-1：filter_gates 一次性消费 applies_when 5 字段矩阵。

来源：requirements/REQ-2026-005/artifacts/detailed-design.md §3.1（行 100-160）
       requirements/REQ-2026-005/artifacts/features.json TC-FG3-1

矩阵覆盖（5 字段 × 命中 / 不命中 / 空列表 / 缺失 = 5 × 4 = ≥ 20 case）：
  - changed_files：pathspec 模式 vs ctx.changed_files
  - target_phase：与 ctx.to_phase 比对
  - current_phase_in：与 ctx.meta.phase 比对
  - transition：与 ctx.from_phase->ctx.to_phase 比对
  - requires：meta.<field> 必须非空（dot key 支持）

legacy grandfather（≥ 3 case）：
  - meta.legacy=true 命中 legacy-bypass tag → 跳过
  - meta.legacy=true 但 gate 无 legacy-bypass tag → 不跳过
  - meta.legacy=false → 不跳过（即使 gate 有 legacy-bypass tag）
"""
from __future__ import annotations

import pytest

import run as runner_mod
from plugins.base import GateContext


def _entry(
    *,
    gate_id: str = "GATE-TEST",
    triggers: list[str] | None = None,
    applies_when: dict | None = None,
    tags: list[str] | None = None,
) -> dict:
    """构造单条 gate entry（仅含 filter_gates 关心的字段）。"""
    out: dict = {
        "id": gate_id,
        "plugin": "meta_schema",  # 任选一个真实 plugin（不会被 import）
        "severity": "error",
        "triggers": triggers or ["ci"],
        "applies_when": applies_when or {},
        "dependencies": [],
        "side_effects": "none",
        "tests": {"fixtures": ["pass", "fail", "skip"]},
    }
    if tags is not None:
        out["tags"] = tags
    return out


def _wrap(entries: list[dict]) -> dict:
    """把 entries 包成 registry_data dict 供 filter_gates 消费。"""
    return {"schema_version": "1.0", "gates": entries, "escape_hatches": []}


# ====================== changed_files 字段（5 case） ======================
# 注意：changed_files 仅在 trigger=pre-commit 时生效（与 4 plugin 旧 precheck 等价语义）


def test_changed_files_hit_pattern_keeps_gate():
    """given_pattern_matches_changed_file_when_filter_then_kept。"""
    e = _entry(
        triggers=["pre-commit"],
        applies_when={"changed_files": ["requirements/*/meta.yaml"]},
    )
    ctx = GateContext(trigger="pre-commit", changed_files=["requirements/REQ-001/meta.yaml"])
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_changed_files_miss_pattern_drops_gate():
    """given_pattern_no_match_when_filter_then_dropped。"""
    e = _entry(
        triggers=["pre-commit"],
        applies_when={"changed_files": ["requirements/*/meta.yaml"]},
    )
    ctx = GateContext(trigger="pre-commit", changed_files=["scripts/foo.py"])
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []


def test_changed_files_empty_list_means_no_constraint():
    """given_empty_pattern_list_when_filter_then_pass_through（不限制）。"""
    e = _entry(
        triggers=["pre-commit"],
        applies_when={"changed_files": []},
    )
    ctx = GateContext(trigger="pre-commit", changed_files=["scripts/foo.py"])
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_changed_files_missing_field_means_no_constraint():
    """given_no_changed_files_field_when_filter_then_pass_through（缺失 = 不限制）。"""
    e = _entry(triggers=["pre-commit"], applies_when={})
    ctx = GateContext(trigger="pre-commit", changed_files=["scripts/foo.py"])
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_changed_files_only_filters_on_pre_commit_trigger():
    """given_non_pre_commit_trigger_when_filter_then_changed_files_ignored。

    对 ci/phase-transition/submit 等 trigger，changed_files 字段应 pass-through，
    保持与 4 plugin 旧 precheck 'if trigger == pre-commit' 一致语义。
    """
    e = _entry(
        triggers=["ci"],
        applies_when={"changed_files": ["requirements/*/meta.yaml"]},
    )
    # ci 触发 + changed_files=[]：本应 changed_files miss，但 ci 不消费此字段
    ctx = GateContext(trigger="ci", changed_files=[])
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_changed_files_pattern_double_star_works():
    """given_double_star_pattern_when_filter_then_matches_nested。"""
    e = _entry(
        triggers=["pre-commit"],
        applies_when={"changed_files": ["requirements/*/artifacts/**/*.md"]},
    )
    ctx = GateContext(
        trigger="pre-commit",
        changed_files=["requirements/REQ-001/artifacts/tasks/F-001.md"],
    )
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


# ====================== target_phase 字段（3 case） ======================


def test_target_phase_hit_keeps_gate():
    e = _entry(applies_when={"target_phase": "testing"})
    ctx = GateContext(trigger="ci", to_phase="testing")
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_target_phase_miss_drops_gate():
    e = _entry(applies_when={"target_phase": "testing"})
    ctx = GateContext(trigger="ci", to_phase="development")
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []


def test_target_phase_null_means_no_constraint():
    e = _entry(applies_when={"target_phase": None})
    ctx = GateContext(trigger="ci", to_phase=None)
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


# ====================== current_phase_in 字段（3 case） ======================


def test_current_phase_in_hit_keeps_gate():
    e = _entry(applies_when={"current_phase_in": ["development", "testing"]})
    ctx = GateContext(trigger="ci", meta={"phase": "development"})
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_current_phase_in_miss_drops_gate():
    e = _entry(applies_when={"current_phase_in": ["development", "testing"]})
    ctx = GateContext(trigger="ci", meta={"phase": "bootstrap"})
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []


def test_current_phase_in_empty_list_means_no_constraint():
    e = _entry(applies_when={"current_phase_in": []})
    ctx = GateContext(trigger="ci", meta={})
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


# ====================== transition 字段（3 case） ======================


def test_transition_hit_keeps_gate():
    e = _entry(triggers=["phase-transition"], applies_when={"transition": "development->testing"})
    ctx = GateContext(trigger="phase-transition", from_phase="development", to_phase="testing")
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_transition_miss_drops_gate():
    e = _entry(triggers=["phase-transition"], applies_when={"transition": "development->testing"})
    ctx = GateContext(trigger="phase-transition", from_phase="bootstrap", to_phase="definition")
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []


def test_transition_null_means_no_constraint():
    e = _entry(applies_when={"transition": None})
    ctx = GateContext(trigger="ci")
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_transition_drops_gate_when_ctx_lacks_phases():
    """transition 非空但 ctx.from_phase / to_phase 缺失 → 不命中。"""
    e = _entry(applies_when={"transition": "development->testing"})
    ctx = GateContext(trigger="ci")
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []


# ====================== requires 字段（4 case） ======================


def test_requires_hit_keeps_gate():
    e = _entry(triggers=["submit"], applies_when={"requires": ["meta.pr_number"]})
    ctx = GateContext(trigger="submit", meta={"pr_number": 42})
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_requires_miss_field_absent_drops_gate():
    e = _entry(triggers=["submit"], applies_when={"requires": ["meta.pr_number"]})
    ctx = GateContext(trigger="submit", meta={})
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []


def test_requires_miss_field_empty_drops_gate():
    """空字符串 / None / 0 / [] 均视为 '没值'。"""
    e = _entry(triggers=["submit"], applies_when={"requires": ["meta.pr_number"]})
    ctx = GateContext(trigger="submit", meta={"pr_number": None})
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []
    ctx2 = GateContext(trigger="submit", meta={"pr_number": ""})
    assert runner_mod.filter_gates(_wrap([e]), ctx2) == []


def test_requires_empty_list_means_no_constraint():
    e = _entry(applies_when={"requires": []})
    ctx = GateContext(trigger="ci", meta={})
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_requires_dot_key_nested():
    """支持 'meta.foo.bar' 嵌套 dot key（虽然 S9 当前未启用嵌套，留前向兼容）。"""
    e = _entry(applies_when={"requires": ["meta.foo.bar"]})
    ctx = GateContext(trigger="ci", meta={"foo": {"bar": "value"}})
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]
    ctx2 = GateContext(trigger="ci", meta={"foo": {}})
    assert runner_mod.filter_gates(_wrap([e]), ctx2) == []


# ====================== AND 组合（任一字段不命中即过滤） ======================


def test_all_five_fields_hit_keeps_gate():
    """5 字段全命中 → 保留。"""
    e = _entry(
        triggers=["pre-commit"],
        applies_when={
            "changed_files": ["requirements/*/meta.yaml"],
            "target_phase": "testing",
            "current_phase_in": ["development"],
            "transition": "development->testing",
            "requires": ["meta.pr_number"],
        },
    )
    ctx = GateContext(
        trigger="pre-commit",
        from_phase="development",
        to_phase="testing",
        changed_files=["requirements/REQ-001/meta.yaml"],
        meta={"phase": "development", "pr_number": 42},
    )
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TEST"]


def test_one_field_miss_drops_gate():
    """4 字段命中 + 1 字段不命中（target_phase）→ 过滤。"""
    e = _entry(
        triggers=["pre-commit"],
        applies_when={
            "changed_files": ["requirements/*/meta.yaml"],
            "target_phase": "testing",   # 故意要求 testing
            "current_phase_in": ["development"],
            "transition": "development->testing",
            "requires": ["meta.pr_number"],
        },
    )
    ctx = GateContext(
        trigger="pre-commit",
        from_phase="development",
        to_phase="completed",   # ← 不命中 target_phase=testing
        changed_files=["requirements/REQ-001/meta.yaml"],
        meta={"phase": "development", "pr_number": 42},
    )
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []


# ====================== legacy grandfather（4 case） ======================


def test_legacy_meta_skips_legacy_bypass_tagged_gate():
    """given_meta_legacy_true_when_filter_then_legacy_bypass_gate_dropped。"""
    e = _entry(
        gate_id="GATE-TRACEABILITY",
        triggers=["phase-transition"],
        tags=["legacy-bypass"],
    )
    ctx = GateContext(
        trigger="phase-transition",
        from_phase="testing",
        to_phase="completed",
        meta={"legacy": True, "phase": "testing"},
    )
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []


def test_legacy_meta_does_not_skip_untagged_gate():
    """given_meta_legacy_true_but_gate_untagged_when_filter_then_kept。"""
    e = _entry(
        gate_id="GATE-META-SCHEMA",
        triggers=["phase-transition"],
        # 无 tags 字段
    )
    ctx = GateContext(
        trigger="phase-transition",
        meta={"legacy": True},
    )
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-META-SCHEMA"]


def test_non_legacy_meta_does_not_skip_legacy_bypass_gate():
    """given_meta_legacy_false_when_filter_then_legacy_bypass_gate_kept。"""
    e = _entry(
        gate_id="GATE-TRACEABILITY",
        triggers=["phase-transition"],
        tags=["legacy-bypass"],
    )
    ctx = GateContext(
        trigger="phase-transition",
        meta={"legacy": False},
    )
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TRACEABILITY"]


def test_meta_legacy_missing_treated_as_non_legacy():
    """meta 无 legacy 字段时按 legacy=false 处理（最常见路径）。"""
    e = _entry(
        gate_id="GATE-TRACEABILITY",
        triggers=["phase-transition"],
        tags=["legacy-bypass"],
    )
    ctx = GateContext(trigger="phase-transition", meta={})
    assert [g["id"] for g in runner_mod.filter_gates(_wrap([e]), ctx)] == ["GATE-TRACEABILITY"]


# ====================== ignore_changed_files kwarg ======================


def test_ignore_changed_files_bypass_for_test_scenario():
    """ignore_changed_files=True 时跳过 changed_files 过滤（测试场景）。"""
    e = _entry(
        triggers=["pre-commit"],
        applies_when={"changed_files": ["requirements/*/meta.yaml"]},
    )
    ctx = GateContext(trigger="pre-commit", changed_files=["scripts/foo.py"])
    # 默认：被过滤
    assert runner_mod.filter_gates(_wrap([e]), ctx) == []
    # 旁路：保留
    out = runner_mod.filter_gates(_wrap([e]), ctx, ignore_changed_files=True)
    assert [g["id"] for g in out] == ["GATE-TEST"]


# ====================== 异常路径 ======================


def test_changed_files_invalid_pattern_raises_runtime_error(monkeypatch):
    """pathspec 解析失败 → RuntimeError，不静默放行。

    pathspec 对大多数字符串都能宽松解析；这里用 monkeypatch 模拟解析时抛 ValueError，
    验证 _match_changed_files 把 ValueError/TypeError 包装为 RuntimeError 上浮。
    """
    import pathspec as _pathspec

    def _bad_from_lines(*a, **kw):
        raise ValueError("bad pattern")

    monkeypatch.setattr(_pathspec.GitIgnoreSpec, "from_lines", staticmethod(_bad_from_lines))

    e = _entry(
        triggers=["pre-commit"],
        applies_when={"changed_files": ["requirements/*/meta.yaml"]},
    )
    ctx = GateContext(trigger="pre-commit", changed_files=["x.md"])
    with pytest.raises(RuntimeError, match="changed_files"):
        runner_mod.filter_gates(_wrap([e]), ctx)
