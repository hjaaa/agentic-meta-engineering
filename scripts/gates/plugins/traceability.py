"""GATE-TRACEABILITY：追溯链完整性检查（封装 traceability-gate-checker Skill）。

设计说明（来源：detailed-design.md §3.4）：
  traceability plugin 封装对 traceability-gate-checker Skill 的调用，
  检查需求→设计→代码→测试的链完整性。

  由于 traceability-gate-checker Skill 依赖 Claude Code 的 Task tool（需要 Agent 上下文），
  本 plugin 在纯 Python 进程中无法真实调用 Skill；此处实现以下降级策略：
    1. 检查 features.json 是否存在（硬门禁：E001）
    2. 检查每个 status=done 的 feature 是否在 detailed-design.md 中有对应章节（结构化可验证部分）
    3. 若 CLAUDE_SKIP_TRACEABILITY_SKILL=1 环境变量存在（CI 轻量模式），只做结构检查
    4. 完整语义校验由 managing-requirement-lifecycle 在切 testing 阶段时通过
       traceability-gate-checker Skill 调用（在 Agent 上下文中）

precheck：
  - 只在 trigger=phase-transition 且 to_phase=testing 时真跑
  - 其他 trigger 直接 Skip（追溯链检查仅在切 testing 时有意义）
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]

from .base import Decision, Gate, GateContext, Report, Severity, Skip


class TraceabilityGate(Gate):
    """追溯链完整性检查 gate（封装 traceability-gate-checker Skill 的结构化部分）。"""

    id = "GATE-TRACEABILITY"
    severity = Severity.ERROR
    triggers = {"phase-transition", "submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """仅 to_phase=testing 时真跑追溯链校验；其他情况直接跳过。

        参数：ctx.to_phase — 目标阶段；ctx.requirement_id — 需求 ID（必须非空）。
        返回：Skip（无需检查）或 None（继续执行 run）。
        """
        if ctx.to_phase != "testing":
            return Skip(f"traceability check only required when to_phase=testing (got {ctx.to_phase!r})")
        if not ctx.requirement_id:
            return Skip("no requirement_id in context; traceability check skipped")
        return None

    def run(self, ctx: GateContext) -> Report:
        """检查 features.json 完整性与 done feature 在 detailed-design.md 中的追溯。

        错误场景：features.json 不存在（T001）或 done feature 未在设计文档中出现（T002）。
        参数：ctx.requirement_id — 目标需求 ID。
        """
        req_id = ctx.requirement_id
        assert req_id is not None  # precheck 已保证

        req_dir = _REPO_ROOT / "requirements" / req_id
        features_path = req_dir / "artifacts" / "features.json"

        # E001：features.json 必须存在
        if not features_path.exists():
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="T001",
                message=f"features.json 不存在: {features_path.relative_to(_REPO_ROOT)}",
                fix_hint="切到 testing 阶段需要 features.json 列出所有 feature",
            )

        try:
            features_data = json.loads(features_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="T001",
                message=f"features.json 解析失败: {exc}",
                fix_hint="确认 features.json 为合法 JSON",
            )

        features = features_data.get("features", [])
        done_features = [
            f for f in features
            if isinstance(f, dict) and f.get("status") == "done" and f.get("id")
        ]

        if not done_features:
            # 没有 done 的 feature，不阻断
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                message="no done features to trace",
            )

        # 结构化追溯：检查 detailed-design.md 中是否包含每个 done feature 的 id
        design_path = req_dir / "artifacts" / "detailed-design.md"
        missing_in_design: list[str] = []
        if design_path.exists():
            design_text = design_path.read_text(encoding="utf-8")
            for f in done_features:
                fid = f["id"]
                if not _feature_mentioned(fid, design_text):
                    missing_in_design.append(fid)
        else:
            missing_in_design = [f["id"] for f in done_features]

        if missing_in_design:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="T002",
                message=(
                    f"以下 done feature 未在 detailed-design.md 中找到追溯: "
                    f"{', '.join(missing_in_design)}"
                ),
                fix_hint=(
                    "在 detailed-design.md 中为每个 feature 添加对应章节；"
                    "完整追溯链校验由 /requirement:next 调用 traceability-gate-checker Skill 完成"
                ),
                vars={"missing_in_design": missing_in_design},
            )

        return Report(
            gate_id=self.id,
            decision=Decision.PASS,
            vars={"done_features": [f["id"] for f in done_features]},
        )


def _feature_mentioned(feature_id: str, text: str) -> bool:
    """检查 feature_id 是否在文本中被提到（宽松：只要字符串出现即算）。"""
    return bool(re.search(re.escape(feature_id), text))


# 模块级导出
GATE_CLASS = TraceabilityGate
