"""GATE-FEATURES-SCHEMA plugin 单测（F-002）。

覆盖：
  - TC-F2-2 case1: changed_files=[] → Skip（skip fixture）
  - TC-F2-2 case2: changed_files 命中 features.json + 文件字段非法 → fail（fail fixture）
  - TC-F2-4 case: trigger=ci 但 changed_files 不含 features.json → Skip（自然过滤回归）
  - pass fixture: changed_files 命中 features.json + 字段全合规 → pass
  - skip fixture: features.json 不存在（已被删除） → Skip
  - skip fixture: trigger 不在白名单 → Skip

隔离策略：
  - 使用 tmp_path 创建临时 features.json 文件
  - monkeypatch _REPO_ROOT 到 tmp_path，避免依赖真实 requirements/ 目录
  - features-schema.yaml 用真实文件（schema 已随 F-002 新建）
"""
from __future__ import annotations

import json
from pathlib import Path

from plugins.base import Decision, GateContext, Skip
from plugins import features_schema as plugin_mod

# ---------- 常量 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------- 工具函数 ----------

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _valid_feature(fid: str = "F-001") -> dict:
    """返回一条合法的 feature 数据。"""
    return {
        "id": fid,
        "title": f"Feature {fid} 标题",
        "description": f"Feature {fid} 描述",
        "modules": ["scripts/lib"],
        "depends_on": [],
        "depends_on_features": [],
        "complexity": "medium",
        "touches": [f"scripts/lib/check_{fid.lower()}.py"],
        "acceptance": ["单测全绿"],
    }


def _valid_features_json(req_id: str = "REQ-2099-001", num_features: int = 2) -> dict:
    """返回合法的 features.json 数据。"""
    return {
        "schema_version": "1.0",
        "requirement_id": req_id,
        "features": [_valid_feature(f"F-{i+1:03d}") for i in range(num_features)],
    }


def _make_ctx(
    trigger: str,
    changed_files: list[str],
) -> GateContext:
    """构造 GateContext。"""
    return GateContext(
        trigger=trigger,
        requirement_id="REQ-2099-001",
        changed_files=changed_files,
    )


def _setup_features_json(tmp_path: Path, rel_path: str, data: dict) -> None:
    """在 tmp_path 下写 features.json，路径为 tmp_path / rel_path。"""
    abs_path = tmp_path / rel_path
    _write_json(abs_path, data)


# ======================== TC-F2-2 case1: changed_files=[] → Skip ========================

def test_no_changed_files_is_skipped(tmp_path, monkeypatch):
    """TC-F2-2 case1：changed_files=[] → Skip（skip fixture）。

    没有任何 changed_files 时，features.json glob 不命中 → Skip。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    gate = plugin_mod.FeaturesSchemaGate()
    ctx = _make_ctx("pre-commit", [])

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（无 changed_files），实际：{result}"
    assert "changed_files" in result.reason.lower() or "features.json" in result.reason.lower(), (
        f"Skip.reason 应说明 changed_files 不含 features.json，实际：{result.reason}"
    )


# ======================== TC-F2-2 case2: changed_files 命中 + 字段非法 → fail ========================

def test_invalid_features_json_fails(tmp_path, monkeypatch):
    """TC-F2-2 case2：changed_files 命中 features.json + 文件字段非法 → fail（fail fixture）。

    complexity=giant 不在枚举 → 校验失败 → gate 返回 FAIL。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/features.json"
    data = _valid_features_json()
    data["features"][0]["complexity"] = "giant"  # 非法枚举值
    _setup_features_json(tmp_path, rel_path, data)

    gate = plugin_mod.FeaturesSchemaGate()
    ctx = _make_ctx("pre-commit", [rel_path])

    # precheck 应通过（不 skip）
    skip = gate.precheck(ctx)
    assert skip is None, f"期望 precheck 不 skip，实际：{skip}"

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL, f"期望 FAIL，实际：{report.decision}"
    assert report.code == "R-FEATURES-SCHEMA-INVALID"
    assert "features.json" in (report.message or "").lower() or rel_path in (report.message or "")


# ======================== TC-F2-4: trigger=ci 但 changed_files 不含 features.json → Skip ========================

def test_ci_trigger_without_features_json_is_skipped(tmp_path, monkeypatch):
    """TC-F2-4：trigger=ci 但 changed_files 不含 features.json → Skip（自然过滤回归）。

    即使 trigger=ci 在白名单，changed_files 不含 features.json glob 也 Skip。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    # changed_files 只包含 meta.yaml，不含 features.json
    changed = ["requirements/REQ-2099-001/meta.yaml"]

    gate = plugin_mod.FeaturesSchemaGate()
    ctx = _make_ctx("ci", changed)

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（ci 但不含 features.json），实际：{result}"


# ======================== pass fixture: 合法 features.json → PASS ========================

def test_valid_features_json_passes(tmp_path, monkeypatch):
    """given_valid_features_json_when_run_then_pass（pass fixture）。"""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/features.json"
    data = _valid_features_json()
    _setup_features_json(tmp_path, rel_path, data)

    gate = plugin_mod.FeaturesSchemaGate()
    ctx = _make_ctx("pre-commit", [rel_path])

    skip = gate.precheck(ctx)
    assert skip is None, f"期望 precheck 不 skip，实际：{skip}"

    report = gate.run(ctx)
    assert report.decision == Decision.PASS, (
        f"期望 PASS，实际：{report.decision}，消息：{report.message}"
    )


# ======================== skip fixture: features.json 不存在（已被删除）→ Skip ========================

def test_nonexistent_features_json_is_skipped(tmp_path, monkeypatch):
    """given_features_json_deleted_when_precheck_then_skip（skip fixture）。

    changed_files 中有 features.json 路径，但文件已被删除 → Skip。
    """
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/features.json"
    # 不创建实际文件（模拟删除场景）

    gate = plugin_mod.FeaturesSchemaGate()
    ctx = _make_ctx("pre-commit", [rel_path])

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（文件不存在），实际：{result}"
    assert "不存在" in result.reason or "删除" in result.reason or "absent" in result.reason.lower(), (
        f"Skip.reason 应说明文件不存在，实际：{result.reason}"
    )


# ======================== skip fixture: trigger 不在白名单 → Skip ========================

def test_unknown_trigger_is_skipped(tmp_path, monkeypatch):
    """given_unknown_trigger_when_precheck_then_skip（skip fixture）。"""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/features.json"
    data = _valid_features_json()
    _setup_features_json(tmp_path, rel_path, data)

    gate = plugin_mod.FeaturesSchemaGate()
    ctx = _make_ctx("post-dev", [rel_path])  # post-dev 不在白名单

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（post-dev 不在 trigger 白名单），实际：{result}"


# ======================== fail fixture: 缺 required 顶层字段 ========================

def test_missing_requirement_id_fails(tmp_path, monkeypatch):
    """given_features_json_missing_requirement_id_when_run_then_fail（fail fixture）。"""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path = "requirements/REQ-2099-001/artifacts/features.json"
    data = _valid_features_json()
    del data["requirement_id"]
    _setup_features_json(tmp_path, rel_path, data)

    gate = plugin_mod.FeaturesSchemaGate()
    ctx = _make_ctx("submit", [rel_path])

    skip = gate.precheck(ctx)
    assert skip is None

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    # fix_hint 应含修复指引
    assert report.fix_hint is not None and len(report.fix_hint) > 0


# ======================== 多文件：一个合法一个非法 ========================

def test_two_files_one_invalid_fails(tmp_path, monkeypatch):
    """given_two_features_json_one_invalid_when_run_then_fail。"""
    monkeypatch.setattr(plugin_mod, "_REPO_ROOT", tmp_path)

    rel_path_ok = "requirements/REQ-2099-001/artifacts/features.json"
    rel_path_bad = "requirements/REQ-2099-002/artifacts/features.json"

    _setup_features_json(tmp_path, rel_path_ok, _valid_features_json("REQ-2099-001"))

    bad_data = _valid_features_json("REQ-2099-002")
    del bad_data["features"][0]["title"]
    _setup_features_json(tmp_path, rel_path_bad, bad_data)

    gate = plugin_mod.FeaturesSchemaGate()
    ctx = _make_ctx("ci", [rel_path_ok, rel_path_bad])

    skip = gate.precheck(ctx)
    assert skip is None

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-FEATURES-SCHEMA-INVALID"
