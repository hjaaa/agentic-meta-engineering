"""GATE-INDEX-INTEGRITY：包装 scripts/lib/check_index.py 适配统一 Gate API。

逻辑零改动 —— 沿用 check_index 的"腐化/锚点/遗漏/孤岛/超长"五类检查规则，
仅把旧版 `common.Report` 的 finding 聚合结果映射为新 `plugins.base.Report`：

  - 任一 ERROR finding（broken link）→ Decision.FAIL，code=R-INDEX
  - 仅 WARNING finding              → Decision.PASS（不在 strict 模式下不阻塞）
  - 无 finding                      → Decision.PASS

precheck 决定本 gate 是否真跑：当 trigger=pre-commit 且无任何 INDEX.md 或
context/* 改动命中时直接 Skip。其他 trigger 一律继续。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# 复用现有 check_index 逻辑：把 scripts/lib 加入 sys.path 后 import
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# noqa: E402 —— sys.path 注入后才能 import
from common import Report as LegacyReport  # noqa: E402
from common import Severity as LegacySeverity  # noqa: E402
from common import rel as legacy_rel  # noqa: E402
import check_index  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip


class IndexIntegrityGate(Gate):
    """INDEX.md 一致性 gate（包装 check_index.py）。"""

    id = "GATE-INDEX-INTEGRITY"
    severity = Severity.ERROR
    triggers = {"pre-commit", "phase-transition", "submit", "ci", "post-dev"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        # pre-commit 仅在 INDEX.md 或 context/、requirements/ 下 md 改动时才跑
        if ctx.trigger == "pre-commit":
            if not _has_index_relevant_change(ctx.changed_files):
                return Skip("no INDEX.md or scanned md changes in this commit")
        return None

    def run(self, ctx: GateContext) -> Report:
        try:
            config = check_index._load_config()
        except Exception as exc:  # noqa: BLE001
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="INDEX-CONFIG-LOAD",
                message=f"读取 index-config.yaml 失败: {exc}",
                fix_hint="确认 scripts/lib/index-config.yaml 存在且 YAML 合法",
            )

        scan_roots = config.get("scan_roots", []) or []
        ignore = config.get("ignore", []) or []
        warn_line_limit = int(config.get("warn_line_limit", 200))
        sibling_scan_depth = int(config.get("sibling_scan_depth", 1))

        indexes = check_index._discover_indexes(scan_roots)
        if not indexes:
            return Report(gate_id=self.id, decision=Decision.PASS,
                          message="no INDEX.md found")

        legacy_report = LegacyReport()
        referenced: set[Path] = set()
        for idx in indexes:
            check_index._check_index_file(
                idx, referenced, ignore, warn_line_limit,
                sibling_scan_depth, legacy_report,
            )

        all_md = check_index._discover_all_md(scan_roots)
        check_index._check_orphans(all_md, referenced, ignore, legacy_report)

        # 行为契约（详细设计 §5.1）：把 legacy 完整 render 输出到 stdout
        if legacy_report.findings():
            print(legacy_report.render())

        return _legacy_to_report(self.id, legacy_report)


def _has_index_relevant_change(changed_files: list[str]) -> bool:
    """改动文件命中 INDEX.md 或扫描根下任一 md → True。"""
    if not changed_files:
        return False
    for f in changed_files:
        if f.endswith("INDEX.md"):
            return True
        # 简化处理：context/ 或 requirements/ 下的 md 文件均视为相关
        parts = Path(f).parts
        if parts[:1] == ("context",) and f.endswith(".md"):
            return True
        if parts[:1] == ("requirements",) and f.endswith(".md"):
            return True
    return False


def _legacy_to_report(gate_id: str, legacy: LegacyReport) -> Report:
    """把 common.Report 的 findings 列表降维成单条 Report。"""
    findings = legacy.findings()
    errors = [f for f in findings if f[1] == LegacySeverity.ERROR]
    warnings = [f for f in findings if f[1] == LegacySeverity.WARNING]

    if errors:
        first = errors[0]
        message = f"{first[0]}: {first[2]}: {first[3]}"
        return Report(
            gate_id=gate_id,
            decision=Decision.FAIL,
            code="R-INDEX",
            message=message,
            fix_hint="跑 /knowledge:organize-index 修复或在 INDEX.md 补条目",
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


# 防止 unused-import 警告（legacy_rel 仅作为 check_index 间接依赖的 sentinel）
_ = legacy_rel

# 模块级导出
GATE_CLASS = IndexIntegrityGate
