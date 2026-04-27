"""GATE-META-SCHEMA：包装 scripts/lib/check_meta.py 适配统一 Gate API。

逻辑零改动 —— 沿用 check_meta 的 schema/枚举/格式/条件必填规则，仅把旧版
`common.Report` 的多 finding 聚合结果映射为新 `plugins.base.Report`：

  - 任一 ERROR finding → Decision.FAIL，code=R-META（表示 meta 类）
  - 仅 WARNING finding → Decision.PASS（severity=warning 由 registry 决定，runner 据此调整 exit code）
  - 无 finding         → Decision.PASS

为保持与旧入口的行为契约等价（详细设计 §5.1），fail 路径会把 legacy report 的
完整 render 输出到 stdout（与旧入口一致），让 normalize-stderr.sh 的关键前缀过滤
得到同样的行集合。

precheck 决定本 gate 是否真跑：当 trigger=pre-commit 且无任何
`requirements/*/meta.yaml` 命中 ctx.changed_files 时直接 Skip。
其他 trigger 由 runner 通过 registry.yaml 的 applies_when 过滤，
本 plugin 内的 precheck 仅做 trigger 局部短路。
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
        # pre-commit 时若没有任何 meta.yaml 改动，直接跳过；其他 trigger 一律继续。
        if ctx.trigger == "pre-commit":
            if not _has_meta_yaml_change(ctx.changed_files):
                return Skip("no meta.yaml changes in this commit")
        return None

    def run(self, ctx: GateContext) -> Report:
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

        # 行为契约（详细设计 §5.1）：把 legacy 完整 render 输出到 stdout，
        # 经 normalize-stderr.sh 关键前缀过滤后与旧入口等价。
        if legacy_report.findings():
            print(legacy_report.render())

        return _legacy_to_report(self.id, legacy_report)


def _has_meta_yaml_change(changed_files: list[str]) -> bool:
    """changed_files 命中 requirements/*/meta.yaml glob → True。"""
    for f in changed_files:
        parts = Path(f).parts
        if len(parts) >= 3 and parts[0] == "requirements" and parts[-1] == "meta.yaml":
            return True
    return False


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


def _legacy_to_report(gate_id: str, legacy: LegacyReport) -> Report:
    """把 common.Report 的 findings 列表降维成单条 Report。"""
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

    return Report(
        gate_id=gate_id,
        decision=Decision.PASS,
        vars={"warnings": [list(f) for f in warnings]} if warnings else {},
    )


# 模块级导出：runner 通过 module.GATE_CLASS 拿到子类
GATE_CLASS = MetaSchemaGate
