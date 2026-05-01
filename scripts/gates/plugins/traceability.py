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
        """放行两种路径：phase-transition→testing 以及 submit（含 requirement_id）。

        参数：ctx.trigger — 触发类型；ctx.to_phase — 目标阶段（phase-transition 时有效）；
              ctx.requirement_id — 需求 ID（submit 路径必须非空）。
        返回：Skip（无需检查）或 None（继续执行 run）。
        """
        # 路径 1：阶段切换到 testing（既有逻辑保持不变）
        if ctx.trigger == "phase-transition" and ctx.to_phase == "testing":
            if not ctx.requirement_id:
                return Skip("no requirement_id in context; traceability check skipped")
            return None
        # 路径 2：submit 时做追溯链快查（F-005 新增，确保 PR 前追溯已完整）
        if ctx.trigger == "submit" and ctx.requirement_id:
            return None
        return Skip(
            f"traceability check only required when to_phase=testing "
            f"or trigger=submit with requirement_id (got trigger={ctx.trigger!r}, "
            f"to_phase={ctx.to_phase!r})"
        )

    def run(self, ctx: GateContext) -> Report:
        """串调私有检查方法：features.json 读取 → design 追溯检查。

        参数：ctx.requirement_id — 目标需求 ID（precheck 已保证非空）。
        失败场景：T001（features.json 缺失/解析失败）/ T002（done feature 未在设计中）。
        """
        req_id = ctx.requirement_id
        assert req_id is not None  # precheck 已保证
        req_dir = _REPO_ROOT / "requirements" / req_id

        done_features, fail_report = _check_features_file(self.id, req_dir)
        if fail_report is not None:
            return fail_report
        assert done_features is not None
        return _check_design_traceability(self.id, req_dir, done_features)


def _check_features_file(
    gate_id: str, req_dir: Path
) -> tuple[Optional[list[dict]], Optional[Report]]:
    """读取并解析 features.json，过滤出 status=done 的 feature 列表。

    参数：
      gate_id  — 用于构造 Report 的 gate 标识符。
      req_dir  — 需求目录（如 requirements/REQ-2026-002/）。

    返回：
      (done_features, None)       — 成功：done_features 为过滤后列表（可为空）。
      (None, FailReport)          — features.json 不存在或解析失败，含 T001 Report。
    """
    features_path = req_dir / "artifacts" / "features.json"

    if not features_path.exists():
        return None, Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code="T001",
            message=f"features.json 不存在: {features_path.relative_to(_REPO_ROOT)}",
            fix_hint="切到 testing 阶段需要 features.json 列出所有 feature",
        )

    try:
        features_data = json.loads(features_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return None, Report(
            gate_id=gate_id,
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
    return done_features, None


def _check_design_traceability(
    gate_id: str, req_dir: Path, done_features: list[dict]
) -> Report:
    """检查每个 done feature 是否在 detailed-design.md 中有对应追溯章节。

    参数：
      gate_id       — 用于构造 Report 的 gate 标识符。
      req_dir       — 需求目录。
      done_features — 已过滤的 done feature 列表（_check_features_file 的输出）。

    返回：PASS（全部追溯）/ FAIL T002（存在 missing）/ PASS（无 done feature）。
    """
    if not done_features:
        return Report(gate_id=gate_id, decision=Decision.PASS, message="no done features to trace")

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
            gate_id=gate_id,
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
        gate_id=gate_id,
        decision=Decision.PASS,
        vars={"done_features": [f["id"] for f in done_features]},
    )


def _feature_mentioned(feature_id: str, text: str) -> bool:
    """检查 feature_id 是否在文本中被提到（单词边界：不匹配前/后有标识符字符的情况）。

    使用 look-behind / look-ahead 实现单词边界，确保：
      - "FG-001" 不匹配 "FG-0015" 或 "XFG-001Y"（F-005 收紧）
      - 边界定义：前后不含字母、数字或连字符
    """
    pattern = r"(?<![A-Za-z0-9-])" + re.escape(feature_id) + r"(?![A-Za-z0-9-])"
    return re.search(pattern, text) is not None


# 模块级导出
GATE_CLASS = TraceabilityGate
