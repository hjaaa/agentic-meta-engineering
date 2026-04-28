"""门禁 audit log 写入与汇总。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §2.2。

职责：
  1. _build_audit：把 reports 列表转结构化 audit dict（含 passed / bypassed /
     failed / skipped / rollback_failed / exit_code 等字段）
  2. write_audit：把 audit dict 落盘到 audit/<YYYY-MM>/<trigger>-<timestamp>.json
  3. _calc_exit_code：基于 reports + 严格度计算最终 exit code

F-012 round-2 拆出：从 run.py 抽出，run.py 通过 re-export 保持向后兼容。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.base import Decision, Report

_PKG_ROOT = Path(__file__).resolve().parent
AUDIT_DIR = _PKG_ROOT / "audit"
SCHEMA_VERSION = "1.0"


def build_audit(ctx, reports: list[Report], rollback_failed: bool) -> dict[str, Any]:
    """构造 audit log dict。

    F-008 round-2：env-bypass 路径的 PASS 单独记到 bypassed 字段，记录 reason，
    保证 D-005「reason + audit 已足以追责」决策落地（普通 PASS 仍仅记 gate_id）。

    参数：
      ctx              — GateContext
      reports          — 各 plugin 的 Report 列表
      rollback_failed  — 是否有 rollback 失败（runner 计算）
    """
    passed: list[str] = []
    bypassed: list[dict[str, Any]] = []
    for r in reports:
        if r.decision != Decision.PASS:
            continue
        vars_ = r.vars or {}
        if vars_.get("whitelisted") == "env-bypass":
            bypassed.append({
                "gate_id": r.gate_id,
                "reason": vars_.get("reason", ""),
                "whitelisted": "env-bypass",
            })
        else:
            passed.append(r.gate_id)
    failed = [
        {"gate_id": r.gate_id, "code": r.code, "message": r.message, "fix_hint": r.fix_hint}
        for r in reports if r.decision == Decision.FAIL
    ]
    skipped = [{"gate_id": r.gate_id, "reason": r.message} for r in reports if r.decision == Decision.SKIP]
    return {
        "schema_version": SCHEMA_VERSION,
        "trigger": ctx.trigger,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "actor": ctx.actor,
        "requirement_id": ctx.requirement_id,
        "from_phase": ctx.from_phase,
        "to_phase": ctx.to_phase,
        "passed": passed,
        "bypassed": bypassed,
        "failed": failed,
        "skipped": skipped,
        "escape_used": None,
        "rollback_failed": rollback_failed,
        "exit_code": 1 if failed else 0,
    }


def write_audit(audit: dict[str, Any]) -> Path:
    """写 audit JSON 到 audit/<YYYY-MM>/<trigger>-<timestamp>.json。"""
    ts = datetime.now()
    sub = AUDIT_DIR / ts.strftime("%Y-%m")
    sub.mkdir(parents=True, exist_ok=True)
    fname = f"{audit['trigger']}-{ts.strftime('%Y%m%d-%H%M%S-%f')}.json"
    path = sub / fname
    with path.open("w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    return path


def calc_exit_code(reports: list[Report], plan: list[dict[str, Any]], strict: bool) -> int:
    """0 通过 / 1 存在 error 级 fail（或 strict 下含 warning fail）。"""
    sev_by_id = {e["id"]: e["severity"] for e in plan}
    has_error_fail = False
    has_warning_fail = False
    for r in reports:
        if r.decision != Decision.FAIL:
            continue
        sev = sev_by_id.get(r.gate_id, "error")
        if sev == "error":
            has_error_fail = True
        elif sev == "warning":
            has_warning_fail = True
    if has_error_fail:
        return 1
    if strict and has_warning_fail:
        return 1
    return 0
