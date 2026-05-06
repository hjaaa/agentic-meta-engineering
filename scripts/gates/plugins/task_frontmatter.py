"""GATE-TASK-FRONTMATTER：task.md frontmatter schema 合规性校验（F-003）。

功能：
  - 扫描 changed_files 中命中 requirements/*/artifacts/tasks/*.md 的文件，
    对每个文件调用 check_task_frontmatter 校验 frontmatter schema 合规性。
  - 触发时机：pre-commit / phase-transition / submit / ci。
  - 自然过滤：changed_files 不含 tasks/*.md → Skip（无需下沉 phase 检查）。

设计决策（来源 detailed-design.md §5.1 + D-009 ADR 教训）：
  - GATE-TASK-FRONTMATTER 靠 changed_files glob 命中即足够，
    避免 D-009 to_phase=None 冲突；不需要 target_phase / current_phase_in 过滤。
  - ADR（F-003）：schema_version 是 required 字段，task.md 缺 schema_version → fail；
    F-007 派发模板改造后会统一注入，过渡期这是预期行为（"快暴露问题"原则）。
"""
from __future__ import annotations

import fnmatch
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
import check_task_frontmatter  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# changed_files 过滤 glob 模式（对应 registry.yaml applies_when.changed_files）
_TASK_MD_GLOB = "requirements/*/artifacts/tasks/*.md"

# trigger 白名单（与 registry.yaml triggers 对齐）
_ALLOWED_TRIGGERS = frozenset({"pre-commit", "phase-transition", "submit", "ci"})


class TaskFrontmatterGate(Gate):
    """task.md frontmatter schema 合规性校验 gate。"""

    id = "GATE-TASK-FRONTMATTER"
    severity = Severity.ERROR
    triggers = _ALLOWED_TRIGGERS
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """多层 precheck——快速过滤不命中场景。

        过滤层次：
          1. trigger 防御性确认：不在白名单 → Skip
          2. changed_files 过滤：无 tasks/*.md 命中 → Skip（自然过滤）
          3. 命中的 task.md 文件存在性：全部不存在（如被删除）→ Skip
        """
        # 第 1 层：trigger 白名单防御性确认
        if ctx.trigger not in _ALLOWED_TRIGGERS:
            return Skip(f"trigger={ctx.trigger!r} 不命中（仅 {sorted(_ALLOWED_TRIGGERS)}）")

        # 第 2 层：changed_files 中是否有 tasks/*.md 命中
        matched = _filter_task_files(ctx.changed_files)
        if not matched:
            return Skip("changed_files 不含 tasks/*.md（自然过滤）")

        # 第 3 层：命中文件存在性（被删除则无需校验）
        existing = [f for f in matched if (_REPO_ROOT / f).exists()]
        if not existing:
            return Skip("命中的 task.md 均已不存在（可能已被删除）")

        return None  # 通过所有 precheck，进入 run()

    def run(self, ctx: GateContext) -> Report:
        """主体校验逻辑。

        流程：
          1. 从 changed_files 过滤出命中 glob 的 task.md 路径
          2. 对每个存在的 task.md 调 check_task_frontmatter.validate
          3. 校验失败给 fail_message + fix_hint（含具体字段名 / 路径）
        """
        matched = _filter_task_files(ctx.changed_files)
        existing = [f for f in matched if (_REPO_ROOT / f).exists()]

        failures: list[str] = []
        for rel_path in existing:
            failure = _validate_task_md_file(rel_path)
            if failure:
                failures.append(failure)

        if failures:
            message = f"共 {len(failures)} 个 task.md 校验失败：" + "；".join(failures[:3])
            if len(failures) > 3:
                message += f"（另有 {len(failures) - 3} 条省略）"
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="R-TASK-FRONTMATTER-INVALID",
                message=message,
                fix_hint=(
                    "请检查 task.md frontmatter 字段是否完整"
                    "（必填：schema_version/feature_id/title/status/complexity/"
                    "depends_on/touches/created_at/updated_at），"
                    "status 枚举须为 pending/in-progress/done，"
                    "complexity 枚举须为 trivial/light/medium/heavy，"
                    "feature_id 格式须为 ^F-\\d{3}$。"
                    "注意：schema_version 是必填字段，过渡期由 F-007 派发模板统一注入。"
                ),
            )

        return Report(gate_id=self.id, decision=Decision.PASS)


# ---------- 辅助函数 ----------

def _filter_task_files(changed_files: list[str]) -> list[str]:
    """从 changed_files 中过滤出命中 tasks/*.md glob 的路径列表。

    glob 模式：requirements/*/artifacts/tasks/*.md
    使用 fnmatch 做路径匹配（forward-slash 归一化）。
    """
    result = []
    for f in changed_files:
        normalized = f.replace("\\", "/")
        if fnmatch.fnmatch(normalized, _TASK_MD_GLOB):
            result.append(f)
    return result


def _validate_task_md_file(rel_path: str) -> Optional[str]:
    """对单个 task.md 执行 frontmatter schema 校验。

    Args:
        rel_path: 相对于 repo root 的路径字符串（由 _filter_task_files 过滤）。

    Returns:
        None（校验通过）；错误描述字符串（失败，含路径 + 首条错误消息）。
    """
    task_path = _REPO_ROOT / rel_path
    try:
        schema = check_task_frontmatter._load_schema()
    except check_task_frontmatter.SchemaLoadError as exc:
        logger.exception(
            "task_frontmatter: schema 加载失败，task_md=%s", rel_path
        )
        return f"{rel_path}: task-frontmatter-schema.yaml 加载失败（schema 文件损坏）：{exc}"

    # 直接解析 frontmatter，不走 _load_task_frontmatter（避免 sys.exit 副作用）
    frontmatter_data = _parse_frontmatter_safe(task_path, rel_path)
    if isinstance(frontmatter_data, str):
        # 返回值是 str 表示解析出错（错误消息）
        return frontmatter_data

    report = check_task_frontmatter.validate(frontmatter_data, schema, rel_path)
    if report.has_errors:
        errors = report.errors
        first = errors[0] if errors else "未知错误"
        extra = f"（共 {len(errors)} 条）" if len(errors) > 1 else ""
        return f"{rel_path}: task.md 校验失败：{first}{extra}"

    return None  # 通过


def _parse_frontmatter_safe(
    task_path: Path, rel_path: str
) -> "dict | str":
    """安全解析 task.md 的 frontmatter，不 sys.exit。

    Args:
        task_path: task.md 绝对路径。
        rel_path: 相对路径（用于错误消息）。

    Returns:
        dict（解析成功）或 str（失败，错误消息）。
    """
    import yaml  # 延迟 import，减少模块级副作用

    try:
        content = task_path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"{rel_path}: task.md 读取失败：{exc}"

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return f"{rel_path}: task.md 首行不是 '---'，无法读取 frontmatter；字段 schema_version 必填，当前缺失"

    end_idx: Optional[int] = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return f"{rel_path}: task.md 没有找到 frontmatter 结束标记 '---'；字段 schema_version 必填，当前缺失"

    frontmatter_text = "\n".join(lines[1:end_idx])
    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        return f"{rel_path}: task.md frontmatter YAML 解析失败：{exc}"

    if data is None:
        return {}
    if not isinstance(data, dict):
        return f"{rel_path}: task.md frontmatter 顶层不是 mapping，实际类型：{type(data).__name__}"

    return data


# 模块级导出：runner 通过 module.GATE_CLASS 拿到子类
GATE_CLASS = TaskFrontmatterGate
