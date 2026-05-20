"""共用工厂函数，供 tests/lib/test_context_usage_*.py 各模块引用。

fixtures（fake_repo / git_repo）在 conftest.py 中定义，由 pytest 自动注入。
本模块只放非 fixture 的普通工厂函数和常量。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lib"))

from context_usage_report import (  # noqa: E402
    AppliedEvidence,
    IndexGraphResult,
    KnowledgeFile,
    ReferenceEvidence,
    UsageAggregator,
)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

FIXTURE_REPO = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "context_usage_report"
)

# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def make_file(rel_path: str, kind: str = "team") -> KnowledgeFile:
    """创建最小可用 KnowledgeFile。"""
    return KnowledgeFile(
        path=Path(f"/fake/{rel_path}"),
        rel_path=rel_path,
        kind=kind,  # type: ignore[arg-type]
        size_bytes=100,
        fs_mtime=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def make_index_result(
    indexed_by: dict | None = None,
    broken_links: list | None = None,
    orphans: list | None = None,
) -> IndexGraphResult:
    return IndexGraphResult(
        indexed_by=indexed_by or {},
        broken_links=broken_links or [],
        orphans=orphans or [],
    )


def make_ref(
    target: str,
    source: str = "requirements/req/process.txt",
    line: int = 1,
    kind: str = "raw_path",
    context_line: str = "",
) -> ReferenceEvidence:
    return ReferenceEvidence(
        target=target,
        source=source,
        line=line,
        kind=kind,  # type: ignore[arg-type]
        context_line=context_line,
    )


def make_applied(ref: ReferenceEvidence) -> AppliedEvidence:
    return AppliedEvidence(
        reference=ref,
        rule="window_hit",
        matched_keyword="按照",
        section_heading="## 设计",
    )


def make_aggregator(
    inventory: list,
    indexed_by: dict | None = None,
    references: list | None = None,
    applied: list | None = None,
    git_timestamps: dict | None = None,
    now: datetime | None = None,
) -> UsageAggregator:
    return UsageAggregator(
        inventory=inventory,
        index_result=make_index_result(indexed_by=indexed_by),
        references=references or [],
        applied=applied or [],
        git_timestamps=git_timestamps or {},
        now=now or datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
