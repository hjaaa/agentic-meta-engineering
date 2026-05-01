"""4 个 plugin 的 _legacy_to_report 纯 warning 升级为 FAIL 测试。

验收清单 TC-FG1-1：4 plugin × {error_only, warning_only, mixed, empty} = 16 case。
参数化覆盖所有场景，确保：
  - error_only  → Decision.FAIL，code 为各 plugin 的原始错误码（R-META/R-SOURCING/R-PLAN/R-INDEX）
  - warning_only → Decision.FAIL，code=R-WARNING-ONLY（新增分支）
  - mixed（error + warning）→ Decision.FAIL，code 为原始错误码（error 分支优先）
  - empty → Decision.PASS

外部依赖（LegacyReport）直接使用 common.Report 构造，不依赖真实文件系统。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 把 scripts/lib 加入 sys.path 以使用 common.Report
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import Report as LegacyReport  # noqa: E402
from common import Severity as LegacySeverity  # noqa: E402

from plugins.base import Decision  # noqa: E402
from plugins import meta_schema as meta_schema_mod  # noqa: E402
from plugins import sourcing as sourcing_mod  # noqa: E402
from plugins import plan_freshness as plan_freshness_mod  # noqa: E402
from plugins import index_integrity as index_integrity_mod  # noqa: E402


# ====================== 辅助函数 ======================


def _make_legacy_with_error() -> LegacyReport:
    """构造仅含一条 ERROR finding 的 LegacyReport。"""
    r = LegacyReport()
    r.add("requirements/REQ-TEST/meta.yaml", LegacySeverity.ERROR, "E001", "测试 error finding")
    return r


def _make_legacy_with_warning() -> LegacyReport:
    """构造仅含一条 WARNING finding 的 LegacyReport。"""
    r = LegacyReport()
    r.add("requirements/REQ-TEST/meta.yaml", LegacySeverity.WARNING, "W001", "测试 warning finding")
    return r


def _make_legacy_with_mixed() -> LegacyReport:
    """构造同时含 ERROR 和 WARNING finding 的 LegacyReport（error 分支应优先）。"""
    r = LegacyReport()
    r.add("requirements/REQ-TEST/meta.yaml", LegacySeverity.ERROR, "E001", "测试 error finding")
    r.add("requirements/REQ-TEST/meta.yaml", LegacySeverity.WARNING, "W001", "测试 warning finding")
    return r


def _make_legacy_empty() -> LegacyReport:
    """构造无 finding 的 LegacyReport。"""
    return LegacyReport()


# ====================== 参数化测试矩阵 ======================
# 格式：(plugin_fn, gate_id, legacy_factory, expected_decision, expected_code)

_PLUGIN_FUNCTIONS = [
    (meta_schema_mod._legacy_to_report, "GATE-META-SCHEMA", "R-META"),
    (sourcing_mod._legacy_to_report, "GATE-SOURCING", "R-SOURCING"),
    (plan_freshness_mod._legacy_to_report, "GATE-PLAN-FRESHNESS", "R-PLAN"),
    (index_integrity_mod._legacy_to_report, "GATE-INDEX-INTEGRITY", "R-INDEX"),
]

# 4 plugin × 4 场景 = 16 case 参数列表
_PARAMS = []
for _fn, _gate_id, _error_code in _PLUGIN_FUNCTIONS:
    # error_only → FAIL + 原始错误码
    _PARAMS.append(pytest.param(
        _fn, _gate_id, _make_legacy_with_error,
        Decision.FAIL, _error_code,
        id=f"{_gate_id}-error_only",
    ))
    # warning_only → FAIL + R-WARNING-ONLY
    _PARAMS.append(pytest.param(
        _fn, _gate_id, _make_legacy_with_warning,
        Decision.FAIL, "R-WARNING-ONLY",
        id=f"{_gate_id}-warning_only",
    ))
    # mixed（error + warning）→ FAIL + 原始错误码（error 优先）
    _PARAMS.append(pytest.param(
        _fn, _gate_id, _make_legacy_with_mixed,
        Decision.FAIL, _error_code,
        id=f"{_gate_id}-mixed",
    ))
    # empty → PASS + code=None
    _PARAMS.append(pytest.param(
        _fn, _gate_id, _make_legacy_empty,
        Decision.PASS, None,
        id=f"{_gate_id}-empty",
    ))


@pytest.mark.parametrize(
    "legacy_to_report_fn, gate_id, legacy_factory, expected_decision, expected_code",
    _PARAMS,
)
def test_legacy_to_report_decision_and_code(
    legacy_to_report_fn,
    gate_id,
    legacy_factory,
    expected_decision,
    expected_code,
):
    """参数化验证 _legacy_to_report 在 4 种场景下的决策与错误码。

    覆盖：error_only / warning_only / mixed / empty 四场景 × 4 plugin = 16 case。
    """
    legacy = legacy_factory()
    report = legacy_to_report_fn(gate_id, legacy)

    assert report.decision == expected_decision, (
        f"plugin={gate_id} legacy={legacy.findings()} "
        f"expected decision={expected_decision} but got {report.decision}"
    )
    assert report.code == expected_code, (
        f"plugin={gate_id} legacy={legacy.findings()} "
        f"expected code={expected_code!r} but got {report.code!r}"
    )


# ====================== 补充验证：warning_only 的字段语义 ======================


@pytest.mark.parametrize(
    "legacy_to_report_fn, gate_id",
    [(fn, gid) for fn, gid, _ in _PLUGIN_FUNCTIONS],
    ids=[gid for _, gid, _ in _PLUGIN_FUNCTIONS],
)
def test_warning_only_report_has_required_fields(legacy_to_report_fn, gate_id):
    """warning_only 分支必须携带 message / fix_hint / vars['warnings']。"""
    legacy = _make_legacy_with_warning()
    report = legacy_to_report_fn(gate_id, legacy)

    assert report.decision == Decision.FAIL
    assert report.code == "R-WARNING-ONLY"
    assert report.message is not None and len(report.message) > 0, "message 不能为空"
    assert report.fix_hint is not None and len(report.fix_hint) > 0, "fix_hint 不能为空"
    assert "warnings" in report.vars, "vars 必须含 'warnings' 键"
    assert len(report.vars["warnings"]) > 0, "vars['warnings'] 不能为空列表"


@pytest.mark.parametrize(
    "legacy_to_report_fn, gate_id",
    [(fn, gid) for fn, gid, _ in _PLUGIN_FUNCTIONS],
    ids=[gid for _, gid, _ in _PLUGIN_FUNCTIONS],
)
def test_empty_report_has_no_code(legacy_to_report_fn, gate_id):
    """empty（无 finding）时 code/message 均应为 None，decision=PASS。"""
    legacy = _make_legacy_empty()
    report = legacy_to_report_fn(gate_id, legacy)

    assert report.decision == Decision.PASS
    assert report.code is None
    assert report.message is None


@pytest.mark.parametrize(
    "legacy_to_report_fn, gate_id",
    [(fn, gid) for fn, gid, _ in _PLUGIN_FUNCTIONS],
    ids=[gid for _, gid, _ in _PLUGIN_FUNCTIONS],
)
def test_warning_only_gate_id_is_preserved(legacy_to_report_fn, gate_id):
    """返回的 Report.gate_id 必须与传入的 gate_id 一致（warning 分支不改 gate_id）。"""
    legacy = _make_legacy_with_warning()
    report = legacy_to_report_fn(gate_id, legacy)

    assert report.gate_id == gate_id
