"""GATE-META-SCHEMA：包装 scripts/lib/check_meta.py 适配统一 Gate API。

逻辑零改动 —— 沿用 check_meta 的 schema/枚举/格式/条件必填规则，仅把旧版
`common.Report` 的多 finding 聚合结果映射为新 `plugins.base.Report`：

  - 任一 ERROR finding → Decision.FAIL，code=R-META（表示 meta 类）
  - 仅 WARNING finding → Decision.PASS（severity=warning 由 registry 决定，runner 据此调整 exit code）
  - 无 finding         → Decision.PASS

为保持与旧入口的行为契约等价（详细设计 §5.1），fail 路径会把 legacy report 的
完整 render 输出到 stdout（与旧入口一致），让 normalize-stderr.sh 的关键前缀过滤
得到同样的行集合。

F-003：changed_files 过滤双轨清理——pre-commit 时 runner 已通过
registry.yaml.applies_when.changed_files 一次性过滤掉无 meta.yaml 改动的场景，
本 plugin 不再 precheck 内重复判定（避免双轨腐化）；run() 内 _resolve_meta_paths
仍按 changed_files 选择性扫描，是 IO 选路而非过滤，保留不动。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# 复用现有 check_meta 逻辑：把 scripts/lib 加入 sys.path 后 import
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# noqa: E402 —— sys.path 注入后才能 import
from common import Report as LegacyReport  # noqa: E402
from common import Severity as LegacySeverity  # noqa: E402
import check_meta  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip


class MetaSchemaGate(Gate):
    """meta.yaml schema 校验 gate（包装 check_meta.py）。"""

    id = "GATE-META-SCHEMA"
    severity = Severity.ERROR
    triggers = {"pre-commit", "phase-transition", "submit", "ci", "post-dev"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """F-003 起本 plugin 不在 precheck 做 changed_files 过滤（runner 一处消费）。

        留空实现仅为满足 Gate 抽象方法契约（base.py:115）；过滤完全交给 runner
        的 filter_gates(applies_when.changed_files) 一次性处理，避免双轨腐化。
        """
        return None

    def run(self, ctx: GateContext) -> Report:
        """对所有目标 meta.yaml 做 schema 校验，返回聚合结果。

        错误场景：meta.yaml 不符合 meta-schema.yaml 约束时 FAIL。
        参数：ctx — 包含 requirement_id / trigger / changed_files / extra["meta_paths"]。
        """
        meta_paths = _resolve_meta_paths(ctx)
        if not meta_paths:
            # 没有目标 meta.yaml 可校验：以 PASS 报告（registry 应通过 applies_when 避免到此）
            return Report(gate_id=self.id, decision=Decision.PASS,
                          message="no meta.yaml in scope")

        try:
            schema = check_meta._load_yaml(check_meta.SCHEMA_PATH)
        except Exception as exc:  # noqa: BLE001
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="META-SCHEMA-LOAD",
                message=f"读取 meta-schema.yaml 失败: {exc}",
                fix_hint="确认 context/team/engineering-spec/meta-schema.yaml 存在且 YAML 合法",
            )

        legacy_report = LegacyReport()
        for path in meta_paths:
            check_meta.check_one(path, schema, legacy_report)
            # F-005：在 check_meta 之后追加 legacy 误用检查（共用同一 legacy_report）
            try:
                meta_data = check_meta._load_yaml(path)
            except Exception:  # noqa: BLE001
                # _load_yaml 失败时 check_meta 已记录错误，此处静默跳过
                meta_data = {}
            _check_legacy_misuse(meta_data, legacy_report)

        # 行为契约（详细设计 §5.1）：把 legacy 完整 render 输出到 stdout，
        # 经 normalize-stderr.sh 关键前缀过滤后与旧入口等价。
        if legacy_report.findings():
            print(legacy_report.render())

        strict = bool(ctx.cli_flags.get("strict"))
        return _legacy_to_report(self.id, legacy_report, strict=strict)


def _resolve_meta_paths(ctx: GateContext) -> list[Path]:
    """根据 ctx 决定本次需要校验的 meta.yaml 路径列表。

    优先级：
      1. ctx.extra["meta_paths"]（runner / 测试显式注入）
      2. trigger=pre-commit 时使用 ctx.changed_files 中匹配的 meta.yaml
      3. ctx.requirement_id 存在则取 requirements/<id>/meta.yaml
      4. 兜底：扫 requirements/*/meta.yaml
    """
    explicit = ctx.extra.get("meta_paths")
    if explicit:
        return [Path(p) for p in explicit]

    if ctx.trigger == "pre-commit":
        hits = [Path(f) for f in ctx.changed_files
                if Path(f).parts[:1] == ("requirements",)
                and Path(f).name == "meta.yaml"]
        if hits:
            return hits

    if ctx.requirement_id:
        target = _REPO_ROOT / "requirements" / ctx.requirement_id / "meta.yaml"
        if target.exists():
            return [target]

    return list((_REPO_ROOT / "requirements").glob("*/meta.yaml"))


def _legacy_to_report(
    gate_id: str, legacy: LegacyReport, *, strict: bool = False
) -> Report:
    """把 common.Report 的 findings 列表降维成单条 Report。

    转换规则（Bug-18 同模式修复）：
      - 任一 ERROR finding         → Decision.FAIL，code=R-META
      - 仅 WARNING + strict        → Decision.FAIL，code=R-WARNING-ONLY
      - 仅 WARNING + 非strict      → Decision.PASS，warnings 透传到 vars
      - 无 finding                 → Decision.PASS
    """
    findings = legacy.findings()
    errors = [f for f in findings if f[1] == LegacySeverity.ERROR]
    warnings = [f for f in findings if f[1] == LegacySeverity.WARNING]

    if errors:
        # 取首条 error 作为 message，全部 finding 列入 vars 便于审计
        first = errors[0]
        message = f"{first[0]}: {first[2]}: {first[3]}"
        return Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code="R-META",
            message=message,
            fix_hint="对照 context/team/engineering-spec/meta-schema.yaml 修正字段",
            vars={
                "errors": [list(f) for f in errors],
                "warnings": [list(f) for f in warnings],
            },
        )

    if warnings:
        first = warnings[0]
        if strict:
            return Report(
                gate_id=gate_id,
                decision=Decision.FAIL,
                code="R-WARNING-ONLY",
                message=f"{first[0]}: {first[2]}: {first[3]}",
                fix_hint="strict 模式下 warning 视为失败；去掉 --strict 或修复 W001/W002/W003 后重试",
                vars={"warnings": [list(f) for f in warnings]},
            )
        return Report(
            gate_id=gate_id,
            decision=Decision.PASS,
            message=(
                f"{len(warnings)} warning(s) ignored (non-strict); "
                f"first: {first[0]}: {first[2]}: {first[3]}"
            ),
            vars={"warnings": [list(f) for f in warnings]},
        )

    return Report(
        gate_id=gate_id,
        decision=Decision.PASS,
        vars={},
    )


def _check_legacy_misuse(meta: dict, report: LegacyReport) -> None:
    """F-005：legacy=true 仅当 phase ∈ {completed, archived} 才合法。

    在活跃开发阶段（如 development / task-planning 等）误加 legacy=true，
    会导致部分 gate 检查被豁免，引入安全盲区。本函数在 check_meta 后追加检查。

    参数：
      meta   — 已解析的 meta.yaml dict（若 _load_yaml 失败则传 {}）
      report — LegacyReport 实例，finding 追加写入（共用 check_one 的 report）
    """
    _LEGACY_ALLOWED_PHASES = {"completed", "archived"}

    if meta.get("legacy") is True:
        phase = meta.get("phase")
        if phase not in _LEGACY_ALLOWED_PHASES:
            report.add(
                "meta.yaml",
                LegacySeverity.ERROR,
                "R-LEGACY-MISUSE",
                (
                    f"legacy=true 不允许在 phase={phase!r} 阶段使用；"
                    f"仅 completed/archived 阶段可标记历史豁免。"
                    f"修复：移除 meta.legacy 字段，或确认需求确实已 completed/archived"
                ),
            )


# 模块级导出：runner 通过 module.GATE_CLASS 拿到子类
GATE_CLASS = MetaSchemaGate
