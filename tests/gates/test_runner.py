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
from audit import build_audit
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
    """F-004：write_audit 改为异步 subprocess 调 audit_async.sh（best-effort）。

    不再同步写文件；验证 subprocess.run 被调用（audit 数据已提交给异步管道），
    且返回值为 Path 类型（向后兼容签名）。
    """
    from unittest.mock import patch, MagicMock
    audit_dict = {
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
    import audit as _audit_mod
    with patch.object(_audit_mod, "subprocess") as mock_subprocess:
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        path = runner_mod.write_audit(audit_dict)
        assert mock_subprocess.run.call_count == 1, "write_audit 应通过 subprocess 调 audit_async.sh"
    from pathlib import Path as _Path
    assert isinstance(path, _Path), f"write_audit 应返回 Path 类型，got {type(path)}"


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


# ====================== F-019 / F-020 round-3：基础设施健壮性边界 ======================


def _make_plan_ctx(side_effects: str = "none"):
    """构造最小 plan + ctx，供基础设施异常测试复用。"""
    plan = [{
        "id": "GATE-META-SCHEMA",
        "plugin": "meta_schema",
        "severity": "error",
        "triggers": ["ci"],
        "applies_when": {"requires": []},
        "dependencies": [],
        "side_effects": side_effects,
        "tests": {"fixtures": ["pass", "fail", "skip"]},
    }]
    ctx = GateContext(trigger="ci", requirement_id="REQ-2099-001")
    return plan, ctx


def test_should_not_crash_when_stash_state_raises_oserror(monkeypatch, capsys):
    """given_stash_state_raises_permissionerror_when_execute_then_continue_no_crash（F-020 round-3）。

    PermissionError / 磁盘满等 OSError 时降级为 snapshots={} 跳过事务化保护，
    runner 继续跑 gate；绝不冒泡 traceback 触发 exit 2 阻断 Claude。
    """

    def _raise_perm(*args, **kwargs):
        raise PermissionError("Read-only file system")

    # write_state plugin 才会触发 needs_stash=True；用 review_verdict 的 plan 模拟
    plan = [{
        "id": "GATE-REVIEW-VERDICT",
        "plugin": "review_verdict",
        "severity": "error",
        "triggers": ["ci"],
        "applies_when": {"requires": []},
        "dependencies": [],
        "side_effects": "write_state",
        "tests": {"fixtures": ["pass", "fail", "skip"]},
    }]
    ctx = GateContext(trigger="ci", requirement_id="REQ-2099-001")

    monkeypatch.setattr(runner_mod, "_stash_state", _raise_perm)
    # mock _run_gates 避免真跑 review_verdict；也 mock write_audit 隔离落盘
    monkeypatch.setattr(runner_mod, "_run_gates", lambda *a, **kw: None)
    monkeypatch.setattr(runner_mod, "_commit_write_state", lambda *a, **kw: None)
    monkeypatch.setattr(runner_mod, "_cleanup_snapshots", lambda *a, **kw: None)
    monkeypatch.setattr(runner_mod, "write_audit", lambda *a, **kw: None)

    # 不应抛异常
    rc = runner_mod._execute_plan(ctx, plan, strict=False)
    assert rc == 0, "stash 失败时应降级为 snapshots={} 继续，最终 exit 0"
    err = capsys.readouterr().err
    assert "ERROR stash_state" in err
    assert "PermissionError" in err or "Read-only" in err


def test_should_not_crash_when_write_audit_raises_oserror(monkeypatch, capsys):
    """given_write_audit_raises_oserror_when_execute_then_return_calc_exit_code（F-019 round-3）。

    audit 落盘异常（OSError 系：磁盘满 / 目录无写权限 / fsync 失败）必须打 ERROR 后继续，
    不能让 audit 故障升级为 gate 全崩。
    """
    plan, ctx = _make_plan_ctx(side_effects="none")

    def _raise_disk_full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(runner_mod, "_run_gates", lambda *a, **kw: None)
    monkeypatch.setattr(runner_mod, "_commit_write_state", lambda *a, **kw: None)
    monkeypatch.setattr(runner_mod, "_cleanup_snapshots", lambda *a, **kw: None)
    monkeypatch.setattr(runner_mod, "write_audit", _raise_disk_full)

    rc = runner_mod._execute_plan(ctx, plan, strict=False)
    # 0：因为 reports 为空（_run_gates 被 mock），无任何 fail
    assert rc == 0, "audit 失败时应继续走 _calc_exit_code，不冒泡 OSError"
    err = capsys.readouterr().err
    assert "ERROR audit 落盘失败" in err
    assert "No space left" in err


# ====================== F-004 round-5：audit.exit_code 与 calc_exit_code 一致性（Codex P3） ======================


def _make_warn_plan_and_report(gate_id: str = "GATE-PLAN-FRESHNESS"):
    """构造 warning 级 gate 的 plan + FAIL Report，用于 P3 测试。"""
    plan = [{"id": gate_id, "severity": "warning"}]
    report = Report(
        gate_id=gate_id,
        decision=Decision.FAIL,
        code="W001",
        message="warning fail（如 plan-freshness 过期）",
    )
    return plan, report


def _make_error_plan_and_report(gate_id: str = "GATE-META-SCHEMA"):
    plan = [{"id": gate_id, "severity": "error"}]
    report = Report(
        gate_id=gate_id,
        decision=Decision.FAIL,
        code="E001",
        message="error fail",
    )
    return plan, report


def test_build_audit_exit_code_zero_for_warning_fail_in_non_strict():
    """given_warning_fail_non_strict_when_build_audit_then_exit_code_0（Codex P3 修复）.

    runner _calc_exit_code 在非 strict 模式下 warning fail 返回 0；
    audit 必须与之一致，否则下游消费者收到错误信号。
    """
    plan, report = _make_warn_plan_and_report()
    ctx = GateContext(trigger="post-dev", requirement_id="REQ-2099-006")
    audit = build_audit(ctx, [report], rollback_failed=False, plan=plan, strict=False)
    assert audit["exit_code"] == 0, (
        "warning-level fail 在非 strict 下 audit.exit_code 应 = 0（与 runner 一致）"
    )
    assert len(audit["failed"]) == 1  # 但 failed 列表仍记录此 fail 供审计


def test_build_audit_exit_code_one_for_warning_fail_in_strict():
    """given_warning_fail_strict_when_build_audit_then_exit_code_1（strict 下应升 1）."""
    plan, report = _make_warn_plan_and_report()
    ctx = GateContext(trigger="post-dev", requirement_id="REQ-2099-007")
    audit = build_audit(ctx, [report], rollback_failed=False, plan=plan, strict=True)
    assert audit["exit_code"] == 1, "warning fail 在 strict 下 audit.exit_code 应升 1"


def test_build_audit_exit_code_one_for_error_fail_regardless_of_strict():
    """given_error_fail_when_build_audit_then_exit_code_1_either_strict_or_not。"""
    plan, report = _make_error_plan_and_report()
    ctx = GateContext(trigger="phase-transition", requirement_id="REQ-2099-008")
    audit_loose = build_audit(ctx, [report], rollback_failed=False, plan=plan, strict=False)
    audit_strict = build_audit(ctx, [report], rollback_failed=False, plan=plan, strict=True)
    assert audit_loose["exit_code"] == 1
    assert audit_strict["exit_code"] == 1


def test_build_audit_falls_back_to_legacy_exit_code_when_plan_omitted():
    """given_no_plan_when_build_audit_then_exit_code_falls_back_to_any_fail_one。

    向后兼容：旧调用方未传 plan 时维持"任何 fail = 1"老行为，避免破坏未升级的调用路径。
    """
    plan, report = _make_warn_plan_and_report()
    ctx = GateContext(trigger="post-dev", requirement_id="REQ-2099-009")
    audit = build_audit(ctx, [report], rollback_failed=False)  # 未传 plan / strict
    assert audit["exit_code"] == 1, "无 plan 时 fall back 到老行为（任何 fail = 1）"


def test_build_audit_exit_code_zero_when_no_failures_with_plan():
    """given_no_failures_when_build_audit_then_exit_code_0_with_plan。"""
    pass_report = Report(gate_id="GATE-META-SCHEMA", decision=Decision.PASS)
    plan = [{"id": "GATE-META-SCHEMA", "severity": "error"}]
    ctx = GateContext(trigger="ci", requirement_id="REQ-2099-010")
    audit = build_audit(ctx, [pass_report], rollback_failed=False, plan=plan, strict=False)
    assert audit["exit_code"] == 0


# ====================== canonical phase 枚举校验（REQ-2026-003 工程债修复） ======================
# 历史 bug：meta.yaml.phase 写成 'technical-research'（非 canonical）后，phase-transition
# 门禁链路上的 R001 / ReviewVerdictGate 都因旧 PHASE_REQUIREMENTS dict 取空 list
# 而 vacuous pass。修复：runner 入口 + check_reviews + review_verdict plugin 三层 fail-closed。
# F-012：PHASE_REQUIREMENTS dict 已删；plugin 本地化为 _PHASE_REVIEW_DEPS；R 函数改 required_phases 显式入参。


def test_main_returns_two_when_to_phase_not_in_canonical_enum(capsys):
    """given_invalid_to_phase_when_main_then_exit_2（typo 拦在最早一关）。"""
    rc = runner_mod.main([
        "--trigger=phase-transition",
        "--req=REQ-2099-001",
        "--from=tech-research",
        "--to=technical-research",  # 非 canonical（应为 tech-research）
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--to='technical-research'" in err
    assert "canonical phase 枚举内" in err


def test_main_returns_two_when_from_phase_not_in_canonical_enum(capsys):
    """given_invalid_from_phase_when_main_then_exit_2。"""
    rc = runner_mod.main([
        "--trigger=phase-transition",
        "--req=REQ-2099-001",
        "--from=technical-research",  # 非 canonical
        "--to=outline-design",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--from='technical-research'" in err
    assert "meta-schema.yaml" in err  # 错误消息指向事实源文档


def test_validate_phase_args_returns_none_when_both_empty():
    """given_no_phase_args_when_validate_then_none（CI 模式不传 --from/--to 是合法用法）。"""
    import argparse
    args = argparse.Namespace(from_phase=None, to_phase=None)
    assert runner_mod._validate_phase_args(args) is None


def test_validate_phase_args_returns_none_for_canonical_phases():
    """given_canonical_phases_when_validate_then_none。"""
    import argparse
    args = argparse.Namespace(from_phase="tech-research", to_phase="outline-design")
    assert runner_mod._validate_phase_args(args) is None


# ====================== F-005 carryover-2：V-07 BaseException 兜底 ======================
# F-004 §4.1 引入 main() 包装：拦截 _real_main 抛出的非 SystemExit BaseException →
# 写 /tmp/run-py-error.log → return 2（让 trigger 层把 2 视为 fail-open，不锁死 Claude）。


def test_main_wraps_basexception_returns_2(monkeypatch):
    """given_real_main_raises_baseexception_when_main_then_return_2_and_log。

    F-005 carryover-2（F-4 minor）：BaseException 兜底分支无回归；本用例锁死。
    实现把 traceback 写到 /tmp/run-py-error.log（hard-coded path），测试前清理。
    """
    err_log_path = Path("/tmp/run-py-error.log")
    if err_log_path.exists():
        err_log_path.unlink()

    sentinel = "F-005-test-sentinel-d3e8f7"

    def _boom(_argv):
        raise RuntimeError(f"simulated failure {sentinel}")

    monkeypatch.setattr(runner_mod, "_real_main", _boom)
    try:
        rc = runner_mod.main([])
        assert rc == 2, f"BaseException 兜底必须 return 2（fail-open 协议），got {rc}"
        assert err_log_path.exists(), "/tmp/run-py-error.log 应被写入"
        content = err_log_path.read_text(encoding="utf-8")
        assert "RuntimeError" in content
        assert sentinel in content, "sentinel 必须在 traceback 中（确认是本测试写的）"
    finally:
        if err_log_path.exists():
            err_log_path.unlink()


def test_main_does_not_swallow_systemexit(monkeypatch):
    """given_real_main_raises_systemexit_when_main_then_propagates。

    SystemExit 是 argparse 正常退出路径，main 包装必须放行不拦截。
    """
    def _argparse_exit(_argv):
        raise SystemExit(42)

    monkeypatch.setattr(runner_mod, "_real_main", _argparse_exit)
    with pytest.raises(SystemExit) as exc:
        runner_mod.main([])
    assert exc.value.code == 42, "SystemExit code 必须穿透不被改写"


def test_main_basexception_with_log_write_failure_still_returns_2(monkeypatch):
    """given_log_write_fails_when_main_baseexception_then_still_return_2。

    最外层 except Exception: pass 兜底——/tmp/run-py-error.log 不可写也不该
    把 main 自身搞崩；契约是「永远 return 2，永不 raise」。
    """
    def _boom(_argv):
        raise RuntimeError("inner failure")

    def _open_fails(*_a, **_kw):
        raise OSError("disk full simulated")

    monkeypatch.setattr(runner_mod, "_real_main", _boom)
    monkeypatch.setattr("builtins.open", _open_fails)
    rc = runner_mod.main([])
    assert rc == 2, "log 写失败时 main 仍必须 return 2，不能 raise"


# ====================== F-005 carryover-2：write_audit shlex.quote 注入回归 ======================
# F-004 §4.2：audit dict 经 json.dumps 后被 shlex.quote 包成 bash $1 参数；
# 防御目标：audit dict 中的特殊字符（' " ` $ \n 等）不能逃逸出参数边界注入命令。


def test_write_audit_quotes_single_quote_in_payload(monkeypatch):
    """given_audit_dict_with_single_quote_when_write_audit_then_subprocess_arg_is_quoted。

    最易攻击的字符：单引号。shlex.quote 必须把它转义为 '\\''（结束 + escape + 重启）。
    """
    import audit as audit_mod
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()

    monkeypatch.setattr(audit_mod.subprocess, "run", _fake_run)
    payload = {"trigger": "ci", "evil": "x'; rm -rf / #"}
    audit_mod.write_audit(payload)

    assert "cmd" in captured, "subprocess.run 应被调用"
    bash_cmd = captured["cmd"][2]  # ['bash', '-c', '<cmd>']
    # 攻击载荷不应作为裸字符串出现——必须被 shlex.quote 包裹（含单引号转义序列）
    assert "rm -rf /" in bash_cmd  # 字面量在
    # shlex.quote 对包含单引号的字符串会把它包在外层单引号里并将内部 ' 转成 '"'"' 或 '\''
    # 用更严格的检验：bash 解析这段 cmd 后第一个参数等于 payload JSON
    import shlex as _shlex
    # 解析 audit_append_async <payload-arg> 'runner' 部分
    # bash_cmd 形如：source <path> && audit_append_async '<json>' 'runner'
    parts = _shlex.split(bash_cmd)
    # 找到 audit_append_async，下一个 token 必须是完整 JSON（被 shlex 还原）
    idx = parts.index("audit_append_async")
    restored = parts[idx + 1]
    import json as _json
    assert _json.loads(restored) == payload, (
        "shlex.quote 必须保证 payload 在 bash 解析后能完整还原"
    )


def test_write_audit_quotes_dollar_and_backtick(monkeypatch):
    """given_audit_dict_with_command_substitution_chars_when_write_audit_then_no_eval。

    `$( )` 和反引号是命令替换字符；shlex.quote 必须把它们当字面量。
    """
    import audit as audit_mod
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()

    monkeypatch.setattr(audit_mod.subprocess, "run", _fake_run)
    payload = {"evil": "$(touch /tmp/pwned-$$)", "evil2": "`id`"}
    audit_mod.write_audit(payload)

    bash_cmd = captured["cmd"][2]
    import shlex as _shlex
    parts = _shlex.split(bash_cmd)
    idx = parts.index("audit_append_async")
    restored = parts[idx + 1]
    import json as _json
    parsed = _json.loads(restored)
    assert parsed == payload, "命令替换字符必须被字面化保留"
