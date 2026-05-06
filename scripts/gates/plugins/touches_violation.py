"""GATE-TOUCHES-VIOLATION：touches 越界硬拦截 gate（F-005）。

功能：
  - 扫描 features.json 中的 feature 列表
  - 对每个 feature 读取 tasks/<fid>.receipt.json
  - 任一 receipt.touches_violations[] 非空 → fail
  - 触发时机：phase-transition（development→testing）/ submit

设计来源：
  - detail-design §1.2.2 / §3.4 / §5.1 / §5.2 / §5.3 / §5.4
  - 镜像 post_dev_receipt.py 结构（precheck 4 层 / _resolve_req_dir / _load_feature_ids）

与 GATE-POST-DEV-RECEIPT 分工：
  - post_dev_receipt 负责 receipt.json 存在性和整体合规（status 字段）
  - touches_violation 专注 touches_violations[] 非空检查
  - receipt 不存在 → 本 gate 跳过该 feature（由 post_dev_receipt 兜底报 missing）
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from .base import Decision, Gate, GateContext, Report, Severity, Skip


class TouchesViolationGate(Gate):
    """touches 越界记录硬拦截 gate。"""

    id = "GATE-TOUCHES-VIOLATION"
    severity = Severity.ERROR
    triggers = {"phase-transition", "submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """多层 precheck——快速过滤不命中场景。

        过滤层次（与 post_dev_receipt 同模式）：
          1. trigger 防御性确认：非 phase-transition / submit → Skip
          2. req_dir 存在性：无法定位需求目录 → Skip
          3. features.json 存在性：早期需求未到 task-planning → Skip
          4. phase-transition 时必须是 development→testing → Skip
        """
        # 第 1 层：trigger 白名单（registry.yaml 已静态过滤，此处是运行时双保险）
        if ctx.trigger not in ("phase-transition", "submit"):
            return Skip(f"trigger={ctx.trigger!r} 不命中（仅 phase-transition / submit）")

        # 第 2 层：定位需求目录
        req_dir = _resolve_req_dir(ctx)
        if req_dir is None:
            return Skip("无法定位 req_dir（requirement_id 缺失或需求目录不存在）")

        # 第 3 层：features.json 必须存在
        features_json = req_dir / "artifacts" / "features.json"
        if not features_json.exists():
            return Skip("features.json 不存在（需求可能未到 task-planning 阶段）")

        # 第 4 层：phase-transition 时仅 development→testing 触发（与 post_dev_receipt 同模式）
        if ctx.trigger == "phase-transition":
            target = ctx.extra.get("target_phase") or ctx.to_phase
            if target != "testing":
                return Skip(f"target_phase={target!r}，仅 development→testing 切换时命中")

        return None  # 通过所有 precheck，进入 run()

    def run(self, ctx: GateContext) -> Report:
        """主体校验逻辑：扫描所有 feature 的 touches_violations[]。

        流程：
          1. 读 features.json 获取 feature_id 列表
          2. 对每个 feature_id，尝试读 tasks/<fid>.receipt.json
          3. receipt 不存在 → 跳过（由 GATE-POST-DEV-RECEIPT 兜底）
          4. receipt 存在 → 检查 touches_violations[] 非空
          5. 有违规 → 失败，列出前 3 个 violation（path / tool / feature_id）
        """
        req_dir = _resolve_req_dir(ctx)
        if req_dir is None:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="R-NO-REQ-DIR",
                message="无法定位需求目录",
                fix_hint="确认 requirement_id 正确，需求目录 requirements/<id>/ 存在",
            )

        features_json = req_dir / "artifacts" / "features.json"
        feature_ids, parse_err = _load_feature_ids(features_json)
        if feature_ids is None:
            err_detail = f"：{parse_err}" if parse_err else ""
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="R-FEATURES-PARSE",
                message=f"features.json 解析失败：{features_json}{err_detail}",
                fix_hint="确认 features.json 存在且 JSON 格式合法",
            )

        tasks_dir = req_dir / "artifacts" / "tasks"
        # 收集所有越界条目：(fid, violation_entry)
        all_violations: list[tuple[str, dict]] = []

        for fid in feature_ids:
            violations = _collect_violations(fid, tasks_dir)
            for v in violations:
                all_violations.append((fid, v))

        if not all_violations:
            return Report(gate_id=self.id, decision=Decision.PASS)

        # 生成失败消息：列出前 3 个 violation
        violation_lines = _format_violations(all_violations[:3])
        message = f"共 {len(all_violations)} 个 touches 越界记录：{violation_lines}"
        if len(all_violations) > 3:
            message += f"（另有 {len(all_violations) - 3} 条省略，查看对应 receipt.json）"

        return Report(
            gate_id=self.id,
            decision=Decision.FAIL,
            code="R-TOUCHES-VIOLATION-PRESENT",
            message=message,
            fix_hint=(
                "请审视每个 feature 的 tasks/<fid>.receipt.json 中 touches_violations[] 列表。\n"
                "如越界合理（需求变更）→ 更新 features.json 中该 feature 的 touches 字段后重新提交；\n"
                "如越界不合理（误改）→ 回滚对应文件改动，再重新提交。"
            ),
        )


# ---------- 辅助函数 ----------

def _resolve_req_dir(ctx: GateContext) -> Optional[Path]:
    """从 ctx 定位需求根目录 requirements/<id>/（与 post_dev_receipt 同模式）。

    优先级：
      1. ctx.extra["req_dir"]（测试注入）
      2. ctx.requirement_id → requirements/<id>/
    """
    explicit = ctx.extra.get("req_dir")
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None

    if ctx.requirement_id:
        p = _REPO_ROOT / "requirements" / ctx.requirement_id
        return p if p.exists() else None

    return None


def _load_feature_ids(features_json: Path) -> tuple[list[str] | None, str | None]:
    """读 features.json，返回 (feature_id 列表, 错误信息) 元组（与 post_dev_receipt 同模式）。

    兼容两种格式：顶层 dict.features 或 直接列表。
    返回：(ids, None) 成功；(None, error_msg) 失败。
    """
    try:
        with features_json.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)

    if isinstance(data, dict):
        features = data.get("features", [])
    elif isinstance(data, list):
        features = data
    else:
        return None, "features.json 顶层既非 dict 也非 list"

    ids = []
    for item in features:
        if isinstance(item, dict) and "id" in item:
            ids.append(item["id"])
    return ids, None


def _collect_violations(fid: str, tasks_dir: Path) -> list[dict]:
    """读取单个 feature 的 receipt.json，返回 touches_violations[] 列表。

    receipt.json 不存在 → 返回 []（由 GATE-POST-DEV-RECEIPT 兜底报告缺失，不重复 fail）。
    解析失败 → 返回 []（fail-open，避免误报遮盖真实越界）。
    """
    receipt_path = tasks_dir / f"{fid}.receipt.json"
    if not receipt_path.exists():
        return []  # 不存在由其他 gate 处理

    try:
        with receipt_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("touches_violation: receipt.json 读取失败，fid=%s，原因：%s", fid, exc)
        return []

    if not isinstance(data, dict):
        return []

    violations = data.get("touches_violations", [])
    if not isinstance(violations, list):
        return []

    # 过滤非 dict 条目（容错）
    return [v for v in violations if isinstance(v, dict)]


def _format_violations(items: list[tuple[str, dict]]) -> str:
    """格式化前 N 个 violation 为可读字符串。

    格式：[fid] path=<path>, tool=<tool>
    """
    parts = []
    for fid, v in items:
        path = v.get("path", "?")
        tool = v.get("tool", "?")
        parts.append(f"[{fid}] path={path}, tool={tool}")
    return "；".join(parts)


# 模块级导出：runner 通过 module.GATE_CLASS 拿到子类
GATE_CLASS = TouchesViolationGate
