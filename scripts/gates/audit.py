"""门禁 audit log 写入与汇总。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §2.2。

职责：
  1. _build_audit：把 reports 列表转结构化 audit dict（含 passed / bypassed /
     failed / skipped / rollback_failed / exit_code 等字段）
  2. write_audit：把 audit dict 通过 subprocess 异步写入 audit/.queue（F-004 §4.2）
  3. _calc_exit_code：基于 reports + 严格度计算最终 exit code

F-012 round-2 拆出：从 run.py 抽出，run.py 通过 re-export 保持向后兼容。
F-004：write_audit 改为调 audit_async.sh audit_append_async（best-effort，失败静默）。
"""
from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.base import Decision, Report


def _validate_bypass_reason(raw: str | None) -> str | None:
    """校验并清洗 bypass reason 环境变量。

    返回 None 表示不 bypass（reason 不合法）；返回处理后的 reason 表示可 bypass。
    合法条件：非 None、trim 后 >= 8 字符。同时转义换行符防止 audit log 行污染。
    """
    if raw is None:
        return None
    # 转义控制字符，防止 audit log 行被注入换行
    cleaned = raw.replace("\n", " ").replace("\r", " ")
    if len(cleaned.strip()) < 8:
        return None
    return cleaned


_PKG_ROOT = Path(__file__).resolve().parent
AUDIT_DIR = _PKG_ROOT / "audit"
SCHEMA_VERSION = "1.0"


def build_audit(
    ctx,
    reports: list[Report],
    rollback_failed: bool,
    plan: list[dict[str, Any]] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """构造 audit log dict。

    F-008 round-2：env-bypass 路径的 PASS 单独记到 bypassed 字段，记录 reason，
    保证 D-005「reason + audit 已足以追责」决策落地（普通 PASS 仍仅记 gate_id）。

    F-004 round-5（Codex P3 修复）：
      原实现 `exit_code = 1 if failed else 0` —— 任何 fail 都给 1，但 runner 在非 strict
      模式下 warning-level fail 实际返回 0（见 calc_exit_code）。两者不一致让 audit 给
      下游消费者错误信号（如 plan-freshness warning fail 被误标为阻断）。
      修为：传入 plan + strict 时调 calc_exit_code 与 runner 退出码语义一致；
      不传时 fall back 到老行为（向后兼容尚未升级的调用方）。

    参数：
      ctx              — GateContext
      reports          — 各 plugin 的 Report 列表
      rollback_failed  — 是否有 rollback 失败（runner 计算）
      plan             — 执行计划（含每 gate 的 severity）；提供时 audit exit_code 走精确路径
      strict           — strict 模式标记；提供 plan 时按此判 warning-level fail 是否升 1
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
    if plan is not None:
        exit_code = calc_exit_code(reports, plan, strict)
    else:
        # 兼容尚未升级的调用方（无 plan 上下文）：保留老的"any fail = 1"行为。
        # 新调用必须传 plan + strict 以获得与 runner 一致的退出码。
        exit_code = 1 if failed else 0
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
        "exit_code": exit_code,
    }


def write_audit(audit: dict[str, Any]) -> Path:
    """异步写 audit：通过 subprocess 调 audit_async.sh audit_append_async（best-effort）。

    F-004 §4.2：把 audit dict 序列化为 JSON 单行，追加到 audit/.queue/<日期>.log。
    entry 名 hard-code 为 'runner'（ENTRY_RUNNER 是 bash readonly 常量，
    Python 跨语言无法引用；spec §4.3 D-006 规定 audit_async.sh 是单一事实源）。
    失败完全静默（D-005 best-effort）；timeout=2 防止 audit 写入卡住整个 gate 流程。
    返回默认 Path 保持签名向后兼容（callers 处 write_audit 返回值不被使用）。
    """
    try:
        # 序列化为紧凑 JSON（不换行）
        audit_line = json.dumps(audit, ensure_ascii=False, separators=(",", ":"))
        # shlex.quote 防注入（R2 修订）
        event_line = f"audit {shlex.quote(audit_line)}"
        # 定位 audit_async.sh 相对路径（相对于仓库根）
        audit_async_sh = Path(__file__).resolve().parent.parent / "lib" / "audit_async.sh"
        subprocess.run(
            ["bash", "-c",
             f"source {shlex.quote(str(audit_async_sh))} && audit_append_async {event_line} runner"],
            timeout=2,
            capture_output=True,
        )
    except Exception:  # noqa: BLE001
        # best-effort：失败静默，不阻断 gate 流程
        pass
    return Path("/dev/null")


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
