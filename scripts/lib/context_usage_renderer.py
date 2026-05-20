"""context_usage_renderer — F-010 ReportRenderer 组件。

负责：
  - _to_iso8601 datetime 序列化辅助
  - ReportRenderer: 渲染 Markdown 4 章节 + JSON 报告
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))


def _to_iso8601(dt: datetime | None) -> str | None:
    """将 datetime 转换为 ISO-8601 UTC 字符串，None 保留为 None。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')


class ReportRenderer:
    """渲染 Markdown 4 章节 + JSON 报告。

    职责：
    - render_markdown：输出固定 4 章节（总览 → 高价值知识 → 待治理知识 → 引用明细）
    - render_json：序列化为 JSON 结构（schema 见详设）
    - write：原子化写入文件
    """

    TOOL_VERSION: str = "0.1.0"
    JSON_SCHEMA_URL: str = "https://example.invalid/context-usage-report.schema.json"

    def __init__(
        self,
        config: dict,
        broken_links_count: int,
        orphans_count: int,
        now: datetime,
    ) -> None:
        """初始化 ReportRenderer。

        Args:
            config: 含 5 个必填 key（context_dir/requirements_dir/since_days/
                    high_value_reference_min/stale_threshold_days）；缺失抛 KeyError
            broken_links_count: 断链计数
            orphans_count: 孤岛计数
            now: 生成时间（UTC）
        """
        required_keys = {
            "context_dir", "requirements_dir", "since_days",
            "high_value_reference_min", "stale_threshold_days"
        }
        missing = required_keys - set(config.keys())
        if missing:
            raise KeyError(f"config 缺失必填键：{missing}")
        self._config = config
        self._broken_links_count = broken_links_count
        self._orphans_count = orphans_count
        self._now = now

    def render_markdown(
        self, summaries: list, warnings: list[str]
    ) -> str:
        """渲染 Markdown 报告（4 章节固定顺序）。

        幂等：纯字符串拼接，无 IO。

        Returns:
            Markdown 字符串（UTF-8）
        """
        lines: list[str] = []
        lines.append("# Context 知识利用率报告")
        lines.append("")
        iso_time = _to_iso8601(self._now) or "Unknown"
        lines.append(f"生成时间：{iso_time}  · 工具版本：{self.TOOL_VERSION}")
        lines.append("")

        self._render_overview_section(lines, summaries)
        self._render_high_value_section(lines, summaries)
        self._render_to_review_section(lines, summaries)
        self._render_reference_detail_section(lines, summaries)
        self._render_warnings_section(lines, warnings)

        return "\n".join(lines)

    def _render_overview_section(self, lines: list[str], summaries: list) -> None:
        """渲染 ## 总览 章节（状态统计表）。"""
        # 延迟导入避免循环
        from context_usage_aggregator import KnowledgeStatus  # noqa: PLC0415

        lines.append("## 总览")
        lines.append("")
        total = len(summaries)
        by_status = {status: 0 for status in KnowledgeStatus}
        for s in summaries:
            by_status[s.status] += 1
        lines.append("| 状态 | 计数 |")
        lines.append("|---|---|")
        lines.append(f"| 总计 | {total} |")
        for status in KnowledgeStatus:
            lines.append(f"| {status.value} | {by_status[status]} |")
        lines.append(f"| 断链 | {self._broken_links_count} |")
        lines.append(f"| 孤岛 | {self._orphans_count} |")
        lines.append("")

    def _render_high_value_section(self, lines: list[str], summaries: list) -> None:
        """渲染 ## 高价值知识 章节。"""
        from context_usage_aggregator import KnowledgeStatus  # noqa: PLC0415

        lines.append("## 高价值知识")
        lines.append("")
        high_value = [s for s in summaries if s.status == KnowledgeStatus.HIGH_VALUE]
        if high_value:
            lines.append("| 文件 | 分数 | 引用数 | 应用信号数 | 最后引用 |")
            lines.append("|---|---|---|---|---|")
            for s in high_value:
                last_ref = _to_iso8601(s.last_referenced_at) or "—"
                lines.append(
                    f"| {s.path} | {s.score} | {s.reference_count} | "
                    f"{s.applied_signal_count} | {last_ref} |"
                )
            lines.append("")
        else:
            lines.append("（无）")
            lines.append("")

    def _render_to_review_section(self, lines: list[str], summaries: list) -> None:
        """渲染 ## 待治理知识 章节。"""
        from context_usage_aggregator import KnowledgeStatus  # noqa: PLC0415

        lines.append("## 待治理知识")
        lines.append("")
        review_statuses = (
            KnowledgeStatus.ORPHAN,
            KnowledgeStatus.NEEDS_REVIEW,
            KnowledgeStatus.VISIBLE_UNUSED,
            KnowledgeStatus.STALE_CANDIDATE,
        )
        to_review = [s for s in summaries if s.status in review_statuses]
        if to_review:
            for status_val in review_statuses:
                status_items = [s for s in to_review if s.status == status_val]
                if not status_items:
                    continue
                lines.append(f"### {status_val.value}")
                lines.append("")
                lines.append("| 文件 | 分数 | 引用数 |")
                lines.append("|---|---|---|")
                for s in sorted(status_items, key=lambda x: -x.score):
                    lines.append(f"| {s.path} | {s.score} | {s.reference_count} |")
                lines.append("")
        else:
            lines.append("（无）")
            lines.append("")

    def _render_reference_detail_section(self, lines: list[str], summaries: list) -> None:
        """渲染 ## 引用明细 章节。"""
        lines.append("## 引用明细")
        lines.append("")
        files_with_refs = [s for s in summaries if s.reference_evidences]
        if files_with_refs:
            for s in files_with_refs:
                lines.append(f"### {s.path}")
                lines.append("")
                lines.append("| 来源 | 行号 | 类型 | 引用行 |")
                lines.append("|---|---|---|---|")
                for ev in s.reference_evidences:
                    lines.append(
                        f"| {ev.source} | {ev.line} | {ev.kind} | "
                        f"{ev.context_line[:50]}... |"
                    )
                lines.append("")
        else:
            lines.append("（无）")
            lines.append("")

    def _render_warnings_section(self, lines: list[str], warnings: list[str]) -> None:
        """渲染 ## Warnings 章节（仅在 warnings 非空时追加）。"""
        if warnings:
            lines.append("## Warnings")
            lines.append("")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

    def render_json(
        self, summaries: list, warnings: list[str]
    ) -> str:
        """渲染 JSON 报告。

        schema 见 detailed-design.md §数据结构 JSON 顶层结构。
        datetime → ISO-8601 字符串；Enum → .value；None → null。

        幂等：纯字符串转换。

        Returns:
            JSON 字符串（UTF-8）
        """
        from context_usage_aggregator import KnowledgeStatus  # noqa: PLC0415

        by_status = {status.value: 0 for status in KnowledgeStatus}
        for s in summaries:
            by_status[s.status.value] += 1

        files_list = []
        for s in summaries:
            ref_evs = []
            for ev in s.reference_evidences:
                ref_evs.append({
                    "target": ev.target,
                    "source": ev.source,
                    "line": ev.line,
                    "kind": ev.kind,
                    "context_line": ev.context_line,
                })
            app_evs = []
            for ev in s.applied_evidences:
                ref_dict = {
                    "target": ev.reference.target,
                    "source": ev.reference.source,
                    "line": ev.reference.line,
                    "kind": ev.reference.kind,
                    "context_line": ev.reference.context_line,
                }
                app_evs.append({
                    "reference": ref_dict,
                    "rule": ev.rule,
                    "matched_keyword": ev.matched_keyword,
                    "section_heading": ev.section_heading,
                })
            files_list.append({
                "path": s.path,
                "kind": s.kind,
                "indexed": s.indexed,
                "index_paths": s.index_paths,
                "reference_count": s.reference_count,
                "applied_signal_count": s.applied_signal_count,
                "first_referenced_at": _to_iso8601(s.first_referenced_at),
                "last_referenced_at": _to_iso8601(s.last_referenced_at),
                "last_modified_at": _to_iso8601(s.last_modified_at),
                "last_modified_at_source": s.last_modified_at_source,
                "status": s.status.value,
                "score": s.score,
                "reference_evidences": ref_evs,
                "applied_evidences": app_evs,
            })

        result = {
            "generated_at": _to_iso8601(self._now),
            "tool_version": self.TOOL_VERSION,
            "schema_version": 1,
            "config": {
                "context_dir": self._config["context_dir"],
                "requirements_dir": self._config["requirements_dir"],
                "since_days": self._config["since_days"],
                "high_value_reference_min": self._config["high_value_reference_min"],
                "stale_threshold_days": self._config["stale_threshold_days"],
            },
            "summary": {
                "total": len(summaries),
                "by_status": by_status,
                "broken_links": self._broken_links_count,
                "orphans": self._orphans_count,
            },
            "files": files_list,
            "warnings": warnings,
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    @staticmethod
    def write(content: str, output_path: Path) -> None:
        """原子化写入文件。

        副作用：
        - 自动 mkdir -p output_path.parent
        - 先写 tmp，再 os.replace（原子覆盖）
        - UTF-8 编码

        Args:
            content: 待写入内容（字符串）
            output_path: 目标路径（Path 对象）

        Raises:
            OSError: 磁盘写失败（tmp 写阶段抛，不影响既有文件）
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, output_path)
