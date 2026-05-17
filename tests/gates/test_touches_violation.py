"""GATE-TOUCHES-VIOLATION plugin 单测（F-005）。

覆盖：
  - TC-F5-2 case1: 所有 receipt.touches_violations[] 为空 → pass（pass fixture）
  - TC-F5-2 case2: 某个 receipt.touches_violations[] 非空 → fail（fail fixture）
  - TC-F5-2 case3: trigger=ci → Skip（skip fixture，trigger 不命中）
  - TC-F5-2 case4: phase-transition 但 target_phase=development（非 testing）→ Skip
  - TC-F5-4: TOCTOU 回归 — 扫 touches_guard.py 源码，assert 无 write_state / flock_state_file 调用

隔离策略：
  - 使用 tmp_path 创建临时需求目录结构
  - ctx.extra["req_dir"] 注入需求路径
  - receipt.json 手工写入（不依赖真实需求）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


# 确保 scripts/gates 在 sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATES_DIR = _REPO_ROOT / "scripts" / "gates"
if str(_GATES_DIR) not in sys.path:
    sys.path.insert(0, str(_GATES_DIR))

from plugins.base import Decision, GateContext, Skip
from plugins import touches_violation as plugin_mod


# ---------- 工具函数 ----------

def _write_json(path: Path, data: dict) -> None:
    """写 JSON 文件，自动建父目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _make_features_json(artifacts_dir: Path, feature_ids: list[str]) -> None:
    """写最小化 features.json。"""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "features": [{"id": fid, "title": f"Feature {fid}"} for fid in feature_ids]
    }
    _write_json(artifacts_dir / "features.json", data)


def _make_receipt(
    tasks_dir: Path,
    fid: str,
    violations: list[dict] | None = None,
    status: str = "DONE",
) -> None:
    """写 receipt.json，默认 touches_violations=[]。"""
    data = {
        "schema_version": "1.0",
        "feature_id": fid,
        "status": status,
        "commit_sha": "abc1234",
        "files_changed": [],
        "test_summary": "测试通过",
        "touches_violations": violations if violations is not None else [],
        "concerns": [],
        "missing_context": "",
        "block_reason": "",
        "timestamp": "2026-05-06T00:00:00+00:00",
    }
    _write_json(tasks_dir / f"{fid}.receipt.json", data)


def _make_ctx(trigger: str, req_dir: Path, extra_kwargs: dict | None = None) -> GateContext:
    """构造 GateContext，通过 extra["req_dir"] 注入需求路径。"""
    kwargs: dict = {
        "trigger": trigger,
        "requirement_id": "REQ-2026-TEST",
        "extra": {"req_dir": str(req_dir)},
    }
    if trigger == "phase-transition":
        kwargs["to_phase"] = "testing"
        kwargs["from_phase"] = "development"
        kwargs["extra"]["target_phase"] = "testing"
    if extra_kwargs:
        kwargs.update(extra_kwargs)
    return GateContext(**kwargs)


# ======================== TC-F5-2 case1: pass fixture ========================

def test_no_violations_passes(tmp_path):
    """given_all_receipts_empty_violations_when_run_then_pass（pass fixture）。

    TC-F5-2 case1：所有 receipt.touches_violations[] 为空 → pass。
    """
    req_dir = tmp_path / "REQ-TEST"
    tasks_dir = req_dir / "artifacts" / "tasks"

    _make_features_json(req_dir / "artifacts", ["F-001", "F-002"])
    _make_receipt(tasks_dir, "F-001", violations=[])
    _make_receipt(tasks_dir, "F-002", violations=[])

    gate = plugin_mod.TouchesViolationGate()
    ctx = _make_ctx("phase-transition", req_dir)

    skip = gate.precheck(ctx)
    assert skip is None, f"期望 precheck 不 skip，实际：{skip}"

    report = gate.run(ctx)
    assert report.decision == Decision.PASS, f"期望 PASS，实际：{report.decision}，消息：{report.message}"


# ======================== TC-F5-2 case2: fail fixture ========================

def test_violation_present_fails(tmp_path):
    """given_receipt_has_touches_violations_when_run_then_fail（fail fixture）。

    TC-F5-2 case2：某 receipt.touches_violations[] 非空 → fail，消息包含 path/tool。
    """
    req_dir = tmp_path / "REQ-TEST"
    tasks_dir = req_dir / "artifacts" / "tasks"

    _make_features_json(req_dir / "artifacts", ["F-001", "F-002"])
    _make_receipt(tasks_dir, "F-001", violations=[])
    _make_receipt(tasks_dir, "F-002", violations=[
        {
            "path": "context/some_doc.md",
            "ts": "2026-05-06T10:00:00+00:00",
            "tool": "Edit",
        }
    ])

    gate = plugin_mod.TouchesViolationGate()
    ctx = _make_ctx("phase-transition", req_dir)

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL, f"期望 FAIL，实际：{report.decision}"
    assert report.code == "R-TOUCHES-VIOLATION-PRESENT"
    # 消息应包含 feature_id 和路径
    assert "F-002" in (report.message or "")
    assert "context/some_doc.md" in (report.message or "")
    # fix_hint 应指引用户审视 receipt.json
    assert report.fix_hint is not None
    assert "receipt.json" in (report.fix_hint or "")


# ======================== TC-F5-2 case3: skip fixture（trigger=ci）========================

def test_trigger_ci_skips(tmp_path):
    """given_trigger_ci_when_precheck_then_skip（skip fixture）。

    TC-F5-2 case3a：trigger=ci → GATE 不触发。
    """
    req_dir = tmp_path / "REQ-TEST"
    _make_features_json(req_dir / "artifacts", ["F-001"])
    _make_receipt(req_dir / "artifacts" / "tasks", "F-001")

    gate = plugin_mod.TouchesViolationGate()
    ctx = GateContext(
        trigger="ci",
        requirement_id="REQ-2026-TEST",
        extra={"req_dir": str(req_dir)},
    )

    skip = gate.precheck(ctx)
    assert skip is not None, "期望 precheck 返回 Skip，实际 None"
    assert isinstance(skip, Skip)
    assert "ci" in skip.reason or "trigger" in skip.reason


# ======================== TC-F5-2 case4: skip fixture（非 testing 切换）========================

def test_phase_transition_non_testing_skips(tmp_path):
    """given_phase_transition_not_to_testing_when_precheck_then_skip（skip fixture）。

    TC-F5-2 case3b：phase-transition 但 target_phase != "testing" → Skip。
    """
    req_dir = tmp_path / "REQ-TEST"
    _make_features_json(req_dir / "artifacts", ["F-001"])
    _make_receipt(req_dir / "artifacts" / "tasks", "F-001")

    gate = plugin_mod.TouchesViolationGate()
    ctx = GateContext(
        trigger="phase-transition",
        requirement_id="REQ-2026-TEST",
        from_phase="requirement",
        to_phase="design",
        extra={"req_dir": str(req_dir), "target_phase": "design"},
    )

    skip = gate.precheck(ctx)
    assert skip is not None, "期望 precheck 返回 Skip，实际 None"
    assert isinstance(skip, Skip)


# ======================== TC-F5-2 补充：receipt 缺失时跳过 ========================

def test_receipt_absent_skipped_not_failed(tmp_path):
    """given_receipt_absent_when_run_then_feature_skipped（不重复 post_dev_receipt 的 fail）。

    GATE-POST-DEV-RECEIPT 负责缺失报错；本 gate 仅跳过缺失 feature。
    """
    req_dir = tmp_path / "REQ-TEST"

    _make_features_json(req_dir / "artifacts", ["F-001"])
    # 故意不写 F-001.receipt.json

    gate = plugin_mod.TouchesViolationGate()
    ctx = _make_ctx("phase-transition", req_dir)

    report = gate.run(ctx)
    # receipt 缺失 → 本 gate 跳过 → pass（不 fail）
    assert report.decision == Decision.PASS, (
        f"receipt 缺失时应 pass（由 post_dev_receipt 负责 fail），实际：{report.decision}"
    )


# ======================== TC-F5-2 补充：submit 触发器 ========================

def test_submit_trigger_works(tmp_path):
    """given_trigger_submit_with_violations_when_run_then_fail（submit 触发器覆盖）。"""
    req_dir = tmp_path / "REQ-TEST"
    tasks_dir = req_dir / "artifacts" / "tasks"

    _make_features_json(req_dir / "artifacts", ["F-001"])
    _make_receipt(tasks_dir, "F-001", violations=[
        {"path": "scripts/out_of_scope.py", "ts": "2026-05-06T00:00:00+00:00", "tool": "Write"}
    ])

    gate = plugin_mod.TouchesViolationGate()
    ctx = GateContext(
        trigger="submit",
        requirement_id="REQ-2026-TEST",
        extra={"req_dir": str(req_dir)},
    )

    skip = gate.precheck(ctx)
    assert skip is None, "submit 触发器不应被 skip"

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert report.code == "R-TOUCHES-VIOLATION-PRESENT"


# ======================== TC-F5-4: TOCTOU 回归 ========================

def test_touches_guard_no_write_state_calls():
    """TC-F5-4: touches_guard.py 源码不含 write_state / flock_state_file 调用。

    强制验证 L2 单读约束（detail-design §3.4）。
    touches_guard.py 只允许调用 read_state，不允许写状态文件或持有文件锁。
    """
    guard_path = _REPO_ROOT / ".claude" / "hooks" / "touches_guard.py"
    assert guard_path.exists(), f"touches_guard.py 不存在：{guard_path}"

    src = guard_path.read_text(encoding="utf-8")
    assert "write_state(" not in src, (
        "touches_guard.py 不应调用 write_state()（TOCTOU 风险，detail-design §3.4）"
    )
    assert "flock_state_file(" not in src, (
        "touches_guard.py 不应调用 flock_state_file()（必须用 L2 read_state，detail-design §3.4）"
    )
