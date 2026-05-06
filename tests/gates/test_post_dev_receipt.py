"""GATE-POST-DEV-RECEIPT plugin 单测（F-001）。

覆盖：
  - TC-F1-2 case1: tasks/F-001.md status=done + receipt.json 缺失 → fail（fail fixture）
  - TC-F1-2 case2: receipt.json status=BLOCKED → fail（fail fixture）
  - TC-F1-2 case3: receipt.json status=DONE_WITH_CONCERNS → pass（pass fixture）
  - TC-F1-4 case: trigger=ci → Skip（自然过滤 / skip fixture）

隔离策略：
  - 使用 tmp_path 创建临时需求目录结构
  - 用 ctx.extra["req_dir"] 注入需求路径（避免依赖真实 requirements/ 目录）
  - receipt-schema.yaml 用真实文件（schema 已随 F-001 新建）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from plugins.base import Decision, GateContext, Skip
from plugins import post_dev_receipt as plugin_mod

# ---------- 工具函数 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_task_md(path: Path, status: str, title: str = "测试 feature") -> None:
    """写带 frontmatter 的 task markdown 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""---
status: {status}
title: {title}
---

# {title}

这是测试用的 task md。
"""
    path.write_text(content, encoding="utf-8")


def _make_features_json(features_dir: Path, feature_ids: list[str]) -> None:
    """在 artifacts/ 下写最小化 features.json。"""
    features_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "features": [{"id": fid, "title": f"Feature {fid}"} for fid in feature_ids]
    }
    _write_json(features_dir / "features.json", data)


def _valid_receipt(status: str = "DONE") -> dict:
    """返回合法 receipt.json 数据。"""
    concerns = [] if status == "DONE" else ["有一个已知疑虑"]
    return {
        "schema_version": "1.0",
        "feature_id": "F-001",
        "status": status,
        "commit_sha": "abc1234",
        "files_changed": [],
        "test_summary": "所有测试通过",
        "touches_violations": [],
        "concerns": concerns,
        "missing_context": "",
        "block_reason": "",
        "timestamp": "2026-05-01T12:00:00+08:00",
    }


def _make_ctx(trigger: str, req_dir: Path) -> GateContext:
    """构造 GateContext，通过 extra["req_dir"] 注入需求路径。"""
    ctx_kwargs: dict = {
        "trigger": trigger,
        "requirement_id": "REQ-2026-999",
        "extra": {"req_dir": str(req_dir)},
    }
    if trigger == "phase-transition":
        ctx_kwargs["to_phase"] = "testing"
        ctx_kwargs["from_phase"] = "development"
        ctx_kwargs["extra"]["target_phase"] = "testing"
    return GateContext(**ctx_kwargs)


# ======================== TC-F1-2 case1: fail fixture ========================

def test_receipt_missing_when_done_fails(tmp_path):
    """given_feature_done_but_receipt_json_absent_when_run_then_fail（fail fixture）。

    详细设计 §5.4 TC-F1-2 case1。
    """
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    tasks_dir = req_dir / "artifacts" / "tasks"

    # 写 features.json
    _make_features_json(req_dir / "artifacts", ["F-001"])

    # 写 task md：status=done
    _write_task_md(tasks_dir / "F-001.md", status="done")

    # 不写 F-001.receipt.json（故意缺失）

    gate = plugin_mod.PostDevReceiptGate()
    ctx = _make_ctx("phase-transition", req_dir)

    # precheck 应通过（不 skip）
    skip = gate.precheck(ctx)
    assert skip is None, f"期望 precheck 不 skip，实际：{skip}"

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL, f"期望 FAIL，实际：{report.decision}"
    assert report.code == "R-RECEIPT-MISSING-OR-INVALID"
    assert "F-001" in (report.message or "")
    assert "receipt.json" in (report.message or "").lower() or "receipt" in (report.message or "")


# ======================== TC-F1-2 case2: fail fixture（BLOCKED status） ========================

def test_receipt_blocked_status_fails(tmp_path):
    """given_receipt_status_BLOCKED_when_run_then_fail（fail fixture）。

    详细设计 §5.4 TC-F1-2 case2。
    """
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    tasks_dir = req_dir / "artifacts" / "tasks"

    _make_features_json(req_dir / "artifacts", ["F-001"])
    _write_task_md(tasks_dir / "F-001.md", status="done")

    # 写 status=BLOCKED 的 receipt.json
    receipt_data = _valid_receipt("BLOCKED")
    receipt_data["block_reason"] = "依赖外部服务不可用"
    _write_json(tasks_dir / "F-001.receipt.json", receipt_data)

    gate = plugin_mod.PostDevReceiptGate()
    ctx = _make_ctx("phase-transition", req_dir)

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL, f"期望 FAIL（BLOCKED），实际：{report.decision}"
    assert "F-001" in (report.message or "")


# ======================== TC-F1-2 case3: pass fixture（DONE_WITH_CONCERNS） ========================

def test_receipt_done_with_concerns_passes(tmp_path):
    """given_receipt_status_DONE_WITH_CONCERNS_when_run_then_pass（pass fixture）。

    详细设计 §5.4 TC-F1-2 case3。
    """
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    tasks_dir = req_dir / "artifacts" / "tasks"

    _make_features_json(req_dir / "artifacts", ["F-001"])
    _write_task_md(tasks_dir / "F-001.md", status="done")

    receipt_data = _valid_receipt("DONE_WITH_CONCERNS")
    _write_json(tasks_dir / "F-001.receipt.json", receipt_data)

    gate = plugin_mod.PostDevReceiptGate()
    ctx = _make_ctx("phase-transition", req_dir)

    report = gate.run(ctx)
    assert report.decision == Decision.PASS, f"期望 PASS，实际：{report.decision}，消息：{report.message}"


# ======================== pass fixture：status=DONE ========================

def test_receipt_done_status_passes(tmp_path):
    """given_receipt_status_DONE_when_run_then_pass（pass fixture 补充）。"""
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    tasks_dir = req_dir / "artifacts" / "tasks"

    _make_features_json(req_dir / "artifacts", ["F-001"])
    _write_task_md(tasks_dir / "F-001.md", status="done")

    _write_json(tasks_dir / "F-001.receipt.json", _valid_receipt("DONE"))

    gate = plugin_mod.PostDevReceiptGate()
    ctx = _make_ctx("phase-transition", req_dir)

    report = gate.run(ctx)
    assert report.decision == Decision.PASS, f"期望 PASS，实际：{report.decision}，消息：{report.message}"


# ======================== TC-F1-4: skip fixture（trigger=ci）========================

def test_trigger_ci_is_skipped(tmp_path):
    """given_trigger_ci_when_precheck_then_skip（skip fixture / V-07 自然过滤）。

    详细设计 §5.2 V-07 三重保证第 1 层：registry.yaml 不含 ci trigger，
    run.py 在 filter_gates 阶段已过滤，plugin precheck 是第二道防御性确认。
    TC-F1-4：trigger=ci → precheck 返回 Skip。
    """
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    _make_features_json(req_dir / "artifacts", ["F-001"])

    gate = plugin_mod.PostDevReceiptGate()
    # trigger=ci，非 phase-transition / submit
    ctx = GateContext(
        trigger="ci",
        requirement_id="REQ-2026-999",
        extra={"req_dir": str(req_dir)},
    )

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip，实际：{result}"
    assert "trigger" in result.reason.lower() or "ci" in result.reason.lower(), (
        f"Skip.reason 应说明 trigger 不命中，实际：{result.reason}"
    )


# ======================== skip fixture：无 req_dir ========================

def test_no_req_dir_is_skipped(tmp_path):
    """given_no_req_dir_when_precheck_then_skip（skip fixture 补充）。"""
    gate = plugin_mod.PostDevReceiptGate()
    ctx = GateContext(
        trigger="phase-transition",
        to_phase="testing",
        extra={"req_dir": str(tmp_path / "non_existent"), "target_phase": "testing"},
    )

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（req_dir 不存在），实际：{result}"


# ======================== skip fixture：features.json 不存在 ========================

def test_no_features_json_is_skipped(tmp_path):
    """given_features_json_absent_when_precheck_then_skip（skip fixture 补充）。"""
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    req_dir.mkdir(parents=True)

    gate = plugin_mod.PostDevReceiptGate()
    ctx = GateContext(
        trigger="phase-transition",
        to_phase="testing",
        extra={"req_dir": str(req_dir), "target_phase": "testing"},
    )

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（features.json 不存在），实际：{result}"


# ======================== skip fixture：target_phase != testing ========================

def test_non_testing_target_phase_is_skipped(tmp_path):
    """given_target_phase_not_testing_when_precheck_then_skip（skip fixture 补充）。"""
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    _make_features_json(req_dir / "artifacts", ["F-001"])

    gate = plugin_mod.PostDevReceiptGate()
    ctx = GateContext(
        trigger="phase-transition",
        to_phase="definition",
        extra={"req_dir": str(req_dir), "target_phase": "definition"},
    )

    result = gate.precheck(ctx)
    assert isinstance(result, Skip), f"期望 Skip（target_phase=definition），实际：{result}"


# ======================== 多 feature 混合场景 ========================

def test_multiple_features_one_missing_receipt_fails(tmp_path):
    """given_two_done_features_one_without_receipt_when_run_then_fail。"""
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    tasks_dir = req_dir / "artifacts" / "tasks"

    _make_features_json(req_dir / "artifacts", ["F-001", "F-002"])

    # F-001：done + receipt 存在
    _write_task_md(tasks_dir / "F-001.md", status="done")
    _write_json(tasks_dir / "F-001.receipt.json", _valid_receipt("DONE"))

    # F-002：done 但 receipt 缺失
    _write_task_md(tasks_dir / "F-002.md", status="done")

    gate = plugin_mod.PostDevReceiptGate()
    ctx = _make_ctx("phase-transition", req_dir)

    report = gate.run(ctx)
    assert report.decision == Decision.FAIL
    assert "F-002" in (report.message or "")


def test_pending_feature_skipped_in_check(tmp_path):
    """given_feature_status_pending_when_run_then_skip_that_feature（pass）。"""
    req_dir = tmp_path / "requirements" / "REQ-2026-999"
    tasks_dir = req_dir / "artifacts" / "tasks"

    _make_features_json(req_dir / "artifacts", ["F-001"])
    # status=pending，不需要 receipt
    _write_task_md(tasks_dir / "F-001.md", status="pending")

    gate = plugin_mod.PostDevReceiptGate()
    ctx = _make_ctx("phase-transition", req_dir)

    report = gate.run(ctx)
    assert report.decision == Decision.PASS, f"pending feature 不需要 receipt，应 PASS，实际：{report.decision}"
