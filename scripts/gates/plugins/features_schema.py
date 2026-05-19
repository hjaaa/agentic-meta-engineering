"""GATE-FEATURES-SCHEMA：task-planning 阶段 features.json 结构合规性校验（F-002）。

功能：
  - 扫描 changed_files 中命中 requirements/*/artifacts/features.json 的文件，
    对每个文件调用 check_features 校验 schema 合规性。
  - 触发时机：pre-commit / phase-transition / submit / ci。
  - 自然过滤：changed_files 不含 features.json → Skip（无需下沉 phase 检查）。

设计决策（来源 detailed-design.md §5.1 + D-009 ADR 教训）：
  - F-002 不需要 target_phase / current_phase_in / transition 字段过滤，
    靠 changed_files glob 命中即足够，避免 D-009 to_phase=None 冲突。
  - precheck 层只做 trigger 白名单 + changed_files 过滤 + 文件存在性检查；
    复杂 phase 逻辑不在 plugin 内部实现。
"""
from __future__ import annotations

import fnmatch
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

# noqa: E402 —— sys.path 注入后才能 import
import check_features  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# changed_files 过滤 glob 模式（对应 registry.yaml applies_when.changed_files）
_FEATURES_JSON_GLOB = "requirements/*/artifacts/features.json"

# trigger 白名单（与 registry.yaml triggers 对齐）
_ALLOWED_TRIGGERS = frozenset({"pre-commit", "phase-transition", "submit", "ci"})


class FeaturesSchemaGate(Gate):
    """features.json schema 合规性校验 gate。"""

    id = "GATE-FEATURES-SCHEMA"
    severity = Severity.ERROR
    triggers = _ALLOWED_TRIGGERS
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """多层 precheck——快速过滤不命中场景。

        过滤层次：
          1. trigger 防御性确认：不在白名单 → Skip
          2. changed_files 过滤：无 features.json 命中 → Skip（自然过滤）
          3. 命中的 features.json 文件存在性：全部不存在（如被删除）→ Skip
        """
        # 第 1 层：trigger 白名单防御性确认
        # （registry.yaml triggers 已静态过滤，此处是运行时双保险）
        if ctx.trigger not in _ALLOWED_TRIGGERS:
            return Skip(f"trigger={ctx.trigger!r} 不命中（仅 {sorted(_ALLOWED_TRIGGERS)}）")

        # 第 2 层：changed_files 中是否有 features.json 命中
        matched = _filter_features_files(ctx.changed_files)
        if not matched:
            return Skip("changed_files 不含 features.json（自然过滤）")

        # 第 3 层：命中文件存在性（被删除则无需校验）
        existing = [f for f in matched if (_REPO_ROOT / f).exists()]
        if not existing:
            return Skip("命中的 features.json 均已不存在（可能已被删除）")

        return None  # 通过所有 precheck，进入 run()

    def run(self, ctx: GateContext) -> Report:
        """主体校验逻辑。

        流程：
          1. 从 changed_files 过滤出命中 glob 的 features.json 路径
          2. 对每个存在的 features.json 调 check_features.validate
          3. 校验失败给 fail_message + fix_hint（含具体字段名 / 路径）
        """
        matched = _filter_features_files(ctx.changed_files)
        existing = [f for f in matched if (_REPO_ROOT / f).exists()]

        failures: list[str] = []
        for rel_path in existing:
            failure = _validate_features_file(rel_path)
            if failure:
                failures.append(failure)

        if failures:
            message = f"共 {len(failures)} 个 features.json 校验失败：" + "；".join(failures[:3])
            if len(failures) > 3:
                message += f"（另有 {len(failures) - 3} 条省略）"
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="R-FEATURES-SCHEMA-INVALID",
                message=message,
                fix_hint=(
                    "请检查 features.json 字段是否完整（必填：id/title/description/"
                    "modules/depends_on/depends_on_features/complexity/touches/acceptance），"
                    "complexity 枚举须为 trivial/light/medium/heavy，"
                    "id 格式须为 ^F-\\d{3}$；requirement_id 须匹配 ^REQ-\\d{4}-\\d{3}$（legacy）"
                    " 或 ^\\d{8}-[a-z0-9]+(?:-[a-z0-9]+)*(?:-\\d{2})?$（新格式，D-013）。"
                    "注意：status 字段不在 features.json 中（在 tasks/<fid>.md frontmatter）。"
                ),
            )

        return Report(gate_id=self.id, decision=Decision.PASS)


# ---------- 辅助函数 ----------

def _filter_features_files(changed_files: list[str]) -> list[str]:
    """从 changed_files 中过滤出命中 features.json glob 的路径列表。

    glob 模式：requirements/*/artifacts/features.json
    使用 fnmatch 做路径匹配（forward-slash 归一化）。
    """
    result = []
    for f in changed_files:
        # 路径归一化：统一使用 forward slash
        normalized = f.replace("\\", "/")
        if fnmatch.fnmatch(normalized, _FEATURES_JSON_GLOB):
            result.append(f)
    return result


def _validate_features_file(rel_path: str) -> Optional[str]:
    """对单个 features.json 执行 schema 校验。

    Args:
        rel_path: 相对于 repo root 的路径字符串（由 _filter_features_files 过滤）。

    Returns:
        None（校验通过）；错误描述字符串（失败，含路径 + 首条错误消息）。
    """
    features_path = _REPO_ROOT / rel_path
    try:
        schema = check_features._load_schema()
    except check_features.SchemaLoadError as exc:
        logger.exception(
            "features_schema: schema 加载失败，features_json=%s", rel_path
        )
        return f"{rel_path}: features-schema.yaml 加载失败（schema 文件损坏）：{exc}"

    try:
        with features_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception(
            "features_schema: features.json 读取/解析失败，path=%s", rel_path
        )
        return f"{rel_path}: features.json 读取/解析失败：{exc}"

    if not isinstance(data, dict):
        return f"{rel_path}: features.json 顶层不是 JSON object"

    report = check_features.validate(data, schema, rel_path)
    if report.has_errors:
        errors = report.errors
        first = errors[0] if errors else "未知错误"
        extra = f"（共 {len(errors)} 条）" if len(errors) > 1 else ""
        return f"{rel_path}: features.json 校验失败：{first}{extra}"

    return None  # 通过


# 模块级导出：runner 通过 module.GATE_CLASS 拿到子类
GATE_CLASS = FeaturesSchemaGate
