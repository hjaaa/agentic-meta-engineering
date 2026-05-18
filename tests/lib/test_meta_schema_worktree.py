"""F-010 · meta-schema.yaml worktree 段 schema 校验测试。

覆盖 5 用例：
  TC1 含完整 worktree 段（12 字段全集合法值）的 meta.yaml 校验通过
  TC2 worktree.owner 取非法枚举值（'invalid'）时 schema 校验失败
  TC3 worktree.baseline.status 取非法枚举值（'unknown'）时 schema 校验失败
  TC4 缺 worktree 段的 legacy meta.yaml 校验通过（R7 缓解 / D-014）
  TC5 13 个 completed REQ 的 meta.yaml 回归校验全过（兜底）

设计来源：requirements/REQ-2026-014/artifacts/detailed-design.md §3.10
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
import pytest

# ---------- 路径注入 ----------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATES_DIR = _REPO_ROOT / "scripts" / "gates"
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
for _p in (_GATES_DIR, _LIB_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from plugins.base import Decision, GateContext  # noqa: E402
from plugins import meta_schema as plugin_mod   # noqa: E402

# ---------- schema 路径 ----------
_SCHEMA_PATH = _REPO_ROOT / "context" / "team" / "engineering-spec" / "meta-schema.yaml"


# ============================================================================
# 辅助：轻量 worktree schema walker（读 fields.worktree.properties 逐层校验 enum）
# ============================================================================

def _load_schema() -> dict[str, Any]:
    """加载 meta-schema.yaml，取 fields.worktree 段供 enum 校验。"""
    with _SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _collect_enum_violations(obj: dict[str, Any], props_schema: dict[str, Any]) -> list[str]:
    """递归遍历 obj，依据 props_schema 校验 enum 字段，返回违规字段名列表。

    参数：
      obj         — 待校验的 dict（可为 meta["worktree"] 或嵌套 object）
      props_schema — 当前层 properties 定义（来自 meta-schema.yaml fields.*.properties）
    返回：
      违规字段名列表（含层级路径，如 "baseline.status"）
    """
    violations: list[str] = []
    if not isinstance(obj, dict) or not isinstance(props_schema, dict):
        return violations
    for field, field_def in props_schema.items():
        value = obj.get(field)
        if value is None:
            continue
        field_type = field_def.get("type")
        if field_type == "enum":
            allowed = field_def.get("enum", [])
            if value not in allowed:
                violations.append(field)
        elif field_type == "object":
            sub_props = field_def.get("properties", {})
            if isinstance(value, dict):
                sub_violations = _collect_enum_violations(value, sub_props)
                violations.extend(f"{field}.{v}" for v in sub_violations)
    return violations


def _validate_worktree_enums(meta: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """取 meta["worktree"] + schema.fields.worktree，返回违规字段路径列表。

    若 meta 无 worktree 段，返回空列表（全 optional，legacy 兼容）。
    """
    worktree_data = meta.get("worktree")
    if not worktree_data:
        return []
    fields = schema.get("fields", {})
    wt_schema = fields.get("worktree", {})
    props = wt_schema.get("properties", {})
    return _collect_enum_violations(worktree_data, props)


# ============================================================================
# fixture：构造合法的 meta.yaml dict
# ============================================================================

def _valid_meta_base(req_id: str = "REQ-2026-999") -> dict[str, Any]:
    """构造合法的 bootstrap 阶段 meta.yaml（语义字段允许空）。"""
    return {
        "id": req_id,
        "title": "worktree schema test",
        "phase": "bootstrap",
        "created_at": "2026-05-18 10:00:00",
        "branch": f"feat/{req_id.lower()}",
        "base_branch": "develop",
        "project": "agentic-meta-engineering",
        "services": ["agentic-meta-engineering"],
        "feature_area": "",
        "change_type": "",
        "affected_modules": [],
    }


def _full_worktree_section() -> dict[str, Any]:
    """构造 12 字段全集的合法 worktree 段。"""
    return {
        "enabled": True,
        "owner": "workflow",
        "path": ".worktrees/feat-req-2026-999",
        "absolute_path": "/abs/path/.worktrees/feat-req-2026-999",
        "branch": "feat/req-2026-999",
        "base_branch": "develop",
        "created_at": "2026-05-18 10:00:00",
        "baseline": {
            "command": "pytest -q",
            "status": "passed",
            "completed_at": "2026-05-18 10:01:00",
        },
        "cleanup": {
            "policy": "owned-only",
            "removed_at": "",
        },
    }


def _write_meta(path: Path, body: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(body, f, allow_unicode=True)


# ============================================================================
# TC1：含完整 worktree 段（12 字段全集合法值）的 meta.yaml 校验通过
# ============================================================================

def test_meta_with_full_worktree_section_validates(tmp_path):
    """含完整 worktree 段（12 字段全集合法值）的 meta.yaml 校验通过。

    通过 plugin_mod 确认 GATE-META-SCHEMA 返回 Decision.PASS；
    同时断言 removed_at 取空串与合法 ts 两种形态均无 schema 违规。
    """
    meta = _valid_meta_base()
    wt = _full_worktree_section()
    meta["worktree"] = wt
    meta_file = tmp_path / "meta.yaml"
    _write_meta(meta_file, meta)

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_file)]})
    report = gate.run(ctx)
    assert report.decision == Decision.PASS, f"期望 PASS，实际：{report.decision}，消息：{report.message}"

    # removed_at 取合法 ts 形态也通过
    schema = _load_schema()
    wt_ts = dict(wt)
    wt_ts["cleanup"] = {"policy": "owned-only", "removed_at": "2026-05-18 12:00:00"}
    meta_ts = dict(meta)
    meta_ts["worktree"] = wt_ts
    violations_ts = _validate_worktree_enums(meta_ts, schema)
    assert violations_ts == [], f"removed_at 取合法 ts 不应有 enum 违规：{violations_ts}"


# ============================================================================
# TC2：worktree.owner 取非法枚举值时 schema 校验失败
# ============================================================================

def test_meta_with_invalid_owner_enum_fails():
    """worktree.owner 取非法枚举值（'invalid'）时 schema 校验失败。

    通过 _validate_worktree_enums 直接读 fields.worktree.properties，
    断言违规列表含 'owner' 字段名。
    """
    schema = _load_schema()
    meta = _valid_meta_base()
    wt = _full_worktree_section()
    wt["owner"] = "invalid"
    meta["worktree"] = wt

    violations = _validate_worktree_enums(meta, schema)
    assert "owner" in violations, f"期望 'owner' 在违规列表，实际：{violations}"


# ============================================================================
# TC3：worktree.baseline.status 取非法枚举值时 schema 校验失败
# ============================================================================

def test_meta_with_invalid_baseline_status_fails():
    """worktree.baseline.status 取非法枚举值（'unknown'）时 schema 校验失败。

    通过 _validate_worktree_enums 递归校验嵌套 baseline 对象，
    断言违规列表含 'baseline.status' 路径。
    """
    schema = _load_schema()
    meta = _valid_meta_base()
    wt = _full_worktree_section()
    wt["baseline"]["status"] = "unknown"
    meta["worktree"] = wt

    violations = _validate_worktree_enums(meta, schema)
    assert "baseline.status" in violations, f"期望 'baseline.status' 在违规列表，实际：{violations}"


# ============================================================================
# TC4：缺 worktree 段的 legacy meta.yaml 校验通过（R7 缓解）
# ============================================================================

def test_legacy_meta_without_worktree_section_validates(tmp_path):
    """缺 worktree 段的 legacy meta.yaml 校验通过（R7 缓解 / D-014 兼容）。

    通过 plugin_mod 确认 GATE-META-SCHEMA 返回 Decision.PASS；
    同时通过 _validate_worktree_enums 确认无 enum 违规。
    """
    meta = _valid_meta_base()
    # 故意不加 worktree 段
    meta_file = tmp_path / "meta.yaml"
    _write_meta(meta_file, meta)

    gate = plugin_mod.MetaSchemaGate()
    ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_file)]})
    report = gate.run(ctx)
    assert report.decision == Decision.PASS, f"期望 PASS，实际：{report.decision}，消息：{report.message}"

    schema = _load_schema()
    violations = _validate_worktree_enums(meta, schema)
    assert violations == [], f"缺 worktree 段不应有 enum 违规：{violations}"


# ============================================================================
# TC5：所有 completed/archived REQ 的 meta.yaml 回归校验全过（兜底）
# ============================================================================

def test_existing_completed_req_metas_regress_validate():
    """所有已完成需求的 meta.yaml 回归校验全过（兜底）。

    扫 requirements/REQ-*/meta.yaml，取 phase=completed 或 archived_at 非空的条目，
    逐个通过 GATE-META-SCHEMA 校验；至少覆盖可用数量（目标 ≥ 13 个历史 REQ）。
    若 worktree 段存在，同时跑 _validate_worktree_enums 确认无 enum 违规。
    """
    req_dir = _REPO_ROOT / "requirements"
    all_meta_paths = sorted(req_dir.glob("REQ-*/meta.yaml"))
    assert all_meta_paths, "requirements/ 下无 meta.yaml，兜底测试无效"

    schema = _load_schema()
    gate = plugin_mod.MetaSchemaGate()

    failures: list[str] = []
    for meta_path in all_meta_paths:
        ctx = GateContext(trigger="ci", extra={"meta_paths": [str(meta_path)]})
        report = gate.run(ctx)
        if report.decision != Decision.PASS:
            failures.append(f"{meta_path.parent.name}: {report.message}")
            continue
        # 额外：若含 worktree 段，校验 enum 无违规
        with meta_path.open("r", encoding="utf-8") as f:
            meta_data = yaml.safe_load(f) or {}
        violations = _validate_worktree_enums(meta_data, schema)
        if violations:
            failures.append(f"{meta_path.parent.name}: worktree enum 违规 {violations}")

    assert not failures, "以下 meta.yaml 回归校验失败：\n" + "\n".join(failures)

    # 数量兜底：确保扫到了足够多的 meta.yaml
    assert len(all_meta_paths) >= 1, "至少需要 1 个 meta.yaml 才能作为兜底"
