"""GATE-BYPASS-PHASE-IN-SET：submit 时校验 meta.phase ∈ {development, testing}（F-004）。

设计来源：requirements/REQ-2026-005/artifacts/detailed-design.md §4.4

职责：
  - 在 /requirement:submit 触发时，确认 meta.phase 落在可提交的 phase 集合内；
    否则 FAIL，错误码 R-PHASE-NOT-SUBMITTABLE
  - 防止"在概要设计/详细设计阶段误开 PR"——这些阶段还没代码可推

可提交 phase 白名单：development（开发实施）/ testing（测试验收）
  - 来源：context/team/engineering-spec/iteration-sop.md 8 阶段定义
  - 其他阶段（bootstrap / requirement / tech-research / outline / detail / planning /
    completed / archived）禁止 submit；用户应走 /workflow:next 推进 phase（F-012 后）
"""
from __future__ import annotations

from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# 可 submit 的 phase 白名单
_SUBMITTABLE_PHASES = ("development", "testing")


class PhaseInSetGate(Gate):
    """submit 时检查 meta.phase 在可提交集合内的门禁。"""

    id = "GATE-BYPASS-PHASE-IN-SET"
    severity = Severity.ERROR
    triggers = {"submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """仅 submit trigger 生效；其他 trigger 直接跳过。"""
        if ctx.trigger != "submit":
            return Skip(f"trigger={ctx.trigger!r} 非 submit；跳过 phase-in-set")
        return None

    def run(self, ctx: GateContext) -> Report:
        """读取 meta.phase 与白名单比对，不在白名单 → FAIL。"""
        phase = ctx.meta.get("phase")
        if phase in _SUBMITTABLE_PHASES:
            return Report(gate_id=self.id, decision=Decision.PASS)

        # phase 缺失或不在白名单：统一报 R-PHASE-NOT-SUBMITTABLE
        if not phase:
            message = "meta.phase 字段缺失"
        else:
            message = (
                f"meta.phase={phase!r} 不在可提交集合 {list(_SUBMITTABLE_PHASES)} 内"
            )
        return Report(
            gate_id=self.id,
            decision=Decision.FAIL,
            code="R-PHASE-NOT-SUBMITTABLE",
            message=message,
            fix_hint=(
                "phase 必须为 development 或 testing 才能 submit；"
                "如还在设计阶段，先用 /workflow:next 推进 phase"
            ),
        )


# 模块级导出
GATE_CLASS = PhaseInSetGate
