"""scripts/gates/run.py 的单元测试。

覆盖：
  - registry.yaml 加载 + S1~S10 schema 校验（pass / fail / skip 三类）
  - 过滤 + 拓扑排序
  - audit JSON 输出格式
  - dry-run / validate-registry 退出码

外部依赖（文件 IO）通过 tmp_path 与 monkeypatch 隔离，不动真实 registry。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import run as runner_mod
from plugins.base import Decision, GateContext, Report


# ====================== fixture ======================


def _minimal_registry() -> dict:
    """合法 registry 模板：单 gate，含 fixture pass 用例。"""
    return {
        "schema_version": "1.0",
        "gates": [
            {
                "id": "GATE-META-SCHEMA",
                "plugin": "meta_schema",
                "severity": "error",
                "triggers": ["ci", "phase-transition"],
                "applies_when": {"requires": []},
                "dependencies": [],
                "side_effects": "none",
                "failure_message": "fail msg",
                "tests": {"fixtures": ["pass", "fail", "skip"]},
            }
        ],
        "escape_hatches": [],
    }


@pytest.fixture
def tmp_registry(tmp_path: Path, monkeypatch):
    """生成一个临时 registry.yaml 并把 runner 的全局指针指过去。"""

    def _factory(data: dict) -> Path:
        path = tmp_path / "registry.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
        monkeypatch.setattr(runner_mod, "REGISTRY_PATH", path)
        return path

    return _factory


# ====================== S1 (id 唯一/正则) ======================


def test_load_registry_passes_for_valid_minimal(tmp_registry):
    """given_minimal_valid_registry_when_load_then_returns_dict（pass）."""
    tmp_registry(_minimal_registry())
    data = runner_mod.load_registry()
    assert data["schema_version"] == "1.0"
    assert len(data["gates"]) == 1


def test_load_registry_rejects_bad_id_format(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["id"] = "lower-case-id"
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S1"):
        runner_mod.load_registry()


def test_load_registry_rejects_duplicate_id(tmp_registry):
    reg = _minimal_registry()
    reg["gates"].append(dict(reg["gates"][0]))
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S1"):
        runner_mod.load_registry()


# ====================== S2/S3/S4/S6/S8/S9/S10 ======================


def test_load_registry_rejects_unknown_plugin(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["plugin"] = "no_such_plugin"
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S2"):
        runner_mod.load_registry()


def test_load_registry_rejects_unknown_trigger(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["triggers"] = ["adapter"]   # adapter 不在 S3 白名单
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S3"):
        runner_mod.load_registry()


def test_load_registry_rejects_invalid_severity(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["severity"] = "critical"
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S4"):
        runner_mod.load_registry()


def test_load_registry_rejects_dangling_dependency(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["dependencies"] = ["GATE-DOES-NOT-EXIST"]
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S5"):
        runner_mod.load_registry()


def test_load_registry_rejects_cycle(tmp_registry):
    reg = _minimal_registry()
    reg["gates"].append({
        "id": "GATE-INDEX-INTEGRITY",
        "plugin": "index_integrity",
        "severity": "error",
        "triggers": ["ci"],
        "applies_when": {"requires": []},
        "dependencies": ["GATE-META-SCHEMA"],
        "side_effects": "none",
        "failure_message": "x",
        "tests": {"fixtures": ["pass", "fail", "skip"]},
    })
    # 制造环：META-SCHEMA -> INDEX-INTEGRITY -> META-SCHEMA
    reg["gates"][0]["dependencies"] = ["GATE-INDEX-INTEGRITY"]
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S6"):
        runner_mod.load_registry()


def test_load_registry_rejects_missing_fixtures(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["tests"]["fixtures"] = ["pass"]
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S8"):
        runner_mod.load_registry()


def test_load_registry_rejects_requires_without_meta_prefix(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["applies_when"]["requires"] = ["pr_number"]
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S9"):
        runner_mod.load_registry()


def test_load_registry_rejects_cli_flag_on_ci_only_gate(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["triggers"] = ["ci"]                  # 不含 submit / phase-transition
    reg["gates"][0]["escape_hatch"] = {"cli_flag": "--skip-x"}
    tmp_registry(reg)
    with pytest.raises(runner_mod.RegistryError, match="S10"):
        runner_mod.load_registry()


# ====================== filter + topo ======================


def test_filter_gates_picks_only_matching_trigger(tmp_registry):
    reg = _minimal_registry()
    reg["gates"][0]["triggers"] = ["ci"]
    tmp_registry(reg)
    data = runner_mod.load_registry()

    ctx = GateContext(trigger="ci")
    out = runner_mod.filter_gates(data, ctx)
    assert [e["id"] for e in out] == ["GATE-META-SCHEMA"]

    ctx2 = GateContext(trigger="submit")
    assert runner_mod.filter_gates(data, ctx2) == []


def test_topological_sort_respects_dependencies(tmp_registry):
    reg = _minimal_registry()
    reg["gates"].append({
        "id": "GATE-INDEX-INTEGRITY",
        "plugin": "index_integrity",
        "severity": "error",
        "triggers": ["ci"],
        "applies_when": {"requires": []},
        "dependencies": ["GATE-META-SCHEMA"],
        "side_effects": "none",
        "failure_message": "x",
        "tests": {"fixtures": ["pass", "fail", "skip"]},
    })
    tmp_registry(reg)
    data = runner_mod.load_registry()
    ctx = GateContext(trigger="ci")
    plan = runner_mod.topological_sort(runner_mod.filter_gates(data, ctx))
    ids = [e["id"] for e in plan]
    assert ids.index("GATE-META-SCHEMA") < ids.index("GATE-INDEX-INTEGRITY")


# ====================== audit log ======================


def test_write_audit_creates_file_with_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "AUDIT_DIR", tmp_path / "audit")
    audit = {
        "schema_version": "1.0",
        "trigger": "ci",
        "timestamp": "2026-04-27 21:35:00",
        "actor": "claude-code",
        "requirement_id": "REQ-2026-002",
        "from_phase": None,
        "to_phase": None,
        "passed": ["GATE-META-SCHEMA"],
        "failed": [],
        "skipped": [],
        "escape_used": None,
        "rollback_failed": False,
        "exit_code": 0,
    }
    path = runner_mod.write_audit(audit)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["trigger"] == "ci"
    assert data["passed"] == ["GATE-META-SCHEMA"]


# ====================== exit code（pass / fail / skip 三态） ======================


def test_exit_code_pass_when_all_reports_pass():
    plan = [{"id": "GATE-X", "severity": "error"}]
    reports = [Report(gate_id="GATE-X", decision=Decision.PASS)]
    assert runner_mod._calc_exit_code(reports, plan, strict=False) == 0


def test_exit_code_one_when_error_severity_fails():
    plan = [{"id": "GATE-X", "severity": "error"}]
    reports = [Report(gate_id="GATE-X", decision=Decision.FAIL, message="boom")]
    assert runner_mod._calc_exit_code(reports, plan, strict=False) == 1


def test_exit_code_zero_when_warning_severity_fails_non_strict():
    plan = [{"id": "GATE-X", "severity": "warning"}]
    reports = [Report(gate_id="GATE-X", decision=Decision.FAIL, message="warn")]
    assert runner_mod._calc_exit_code(reports, plan, strict=False) == 0
    assert runner_mod._calc_exit_code(reports, plan, strict=True) == 1


def test_exit_code_skip_does_not_fail():
    plan = [{"id": "GATE-X", "severity": "error"}]
    reports = [Report(gate_id="GATE-X", decision=Decision.SKIP, message="not in scope")]
    assert runner_mod._calc_exit_code(reports, plan, strict=False) == 0


# ====================== CLI 行为 ======================


def test_validate_registry_cli_returns_zero_on_real_registry():
    """对真实 registry.yaml 跑 --validate-registry，应 0 退出。"""
    rc = runner_mod.main(["--validate-registry"])
    assert rc == 0


def test_dry_run_returns_zero(monkeypatch, capsys):
    rc = runner_mod.main(["--trigger=ci", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "GATE-META-SCHEMA" in out
    assert "GATE-INDEX-INTEGRITY" in out


def test_main_returns_two_when_no_trigger_and_no_validate(capsys):
    rc = runner_mod.main([])
    assert rc == 2
