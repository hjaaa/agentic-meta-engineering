"""F-009 · UsageAggregator 验收测试。

覆盖 TC-1~TC-8 状态机矩阵、_compute_score 子项边界、aggregate() 整链路冒烟、
now 注入、fs_mtime 来源跳过回归等。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parents[1] / "scripts" / "lib"))
sys.path.insert(0, str(_THIS_DIR))

from context_usage_report import (  # noqa: E402
    GitTimestamp,
    KnowledgeFile,
    KnowledgeStatus,
    UsageAggregator,
)
from _context_usage_helpers import (  # noqa: E402
    make_aggregator as _make_aggregator,
    make_applied as _make_applied,
    make_file as _make_file,
    make_index_result as _make_index_result,
    make_ref as _make_ref,
)


# ---------------------------------------------------------------------------
# TC-1 ~ TC-8：状态机矩阵（详见 detailed-design.md L908-917）
# ---------------------------------------------------------------------------


def test_tc1_orphan() -> None:
    """TC-1：indexed=False, ref=0 → orphan。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/a.md")
    agg = _make_aggregator([file], indexed_by={}, now=now)
    summaries = agg.aggregate()
    assert len(summaries) == 1
    assert summaries[0].status == KnowledgeStatus.ORPHAN


def test_tc2_needs_review() -> None:
    """TC-2：indexed=False, ref=2, last_ref=5天前 → needs_review。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/b.md")
    last_commit = datetime(2026, 5, 15, tzinfo=timezone.utc)  # 5天前
    ref1 = _make_ref("context/team/b.md", source="requirements/r1/doc.md", line=1)
    ref2 = _make_ref("context/team/b.md", source="requirements/r1/doc.md", line=2)
    ts = GitTimestamp(
        first_commit_at=last_commit,
        last_commit_at=last_commit,
        source="git_log",
    )
    agg = _make_aggregator(
        [file],
        indexed_by={},
        references=[ref1, ref2],
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.NEEDS_REVIEW


def test_tc3_visible_unused() -> None:
    """TC-3：indexed=True, ref=0 → visible_unused。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/c.md")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/c.md": ["context/INDEX.md"]},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.VISIBLE_UNUSED


def test_tc4_high_value() -> None:
    """TC-4：indexed=True, ref=3, applied=1, last_ref=10天前 → high_value。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/d.md")
    last_commit = datetime(2026, 5, 10, tzinfo=timezone.utc)  # 10天前
    refs = [
        _make_ref("context/team/d.md", source="requirements/r1/doc.md", line=i)
        for i in range(1, 4)
    ]
    applied = [_make_applied(refs[0])]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/d.md": ["context/INDEX.md"]},
        references=refs,
        applied=applied,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.HIGH_VALUE


def test_tc5_high_value_over_stale() -> None:
    """TC-5：同时满足 high_value 与 stale 条件 → high_value（优先级高于 stale）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/e.md")
    last_commit = datetime(2026, 1, 21, tzinfo=timezone.utc)  # 约119天前（>90天）
    refs = [
        _make_ref("context/team/e.md", source="requirements/r1/doc.md", line=i)
        for i in range(1, 6)
    ]
    applied = [_make_applied(refs[0]), _make_applied(refs[1])]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/e.md": ["context/INDEX.md"]},
        references=refs,
        applied=applied,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.HIGH_VALUE


def test_tc6_stale_candidate() -> None:
    """TC-6：indexed=True, ref=2, applied=0, last_ref=100天前 → stale_candidate。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/f.md")
    last_commit = datetime(2026, 2, 9, tzinfo=timezone.utc)  # 100天前
    refs = [
        _make_ref("context/team/f.md", source="requirements/r1/doc.md", line=i)
        for i in range(1, 3)
    ]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/f.md": ["context/INDEX.md"]},
        references=refs,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.STALE_CANDIDATE


def test_tc7_active() -> None:
    """TC-7：indexed=True, ref=2, applied=0, last_ref=10天前 → active。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/g.md")
    last_commit = datetime(2026, 5, 10, tzinfo=timezone.utc)  # 10天前
    refs = [
        _make_ref("context/team/g.md", source="requirements/r1/doc.md", line=i)
        for i in range(1, 3)
    ]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/g.md": ["context/INDEX.md"]},
        references=refs,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.ACTIVE


def test_tc8_active_applied_but_ref_insufficient() -> None:
    """TC-8：indexed=True, ref=1, applied=1, last_ref=10天前 → active（applied有但ref不足3）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    file = _make_file("context/team/h.md")
    last_commit = datetime(2026, 5, 10, tzinfo=timezone.utc)  # 10天前
    ref = _make_ref("context/team/h.md", source="requirements/r1/doc.md", line=1)
    applied = [_make_applied(ref)]
    ts = GitTimestamp(first_commit_at=last_commit, last_commit_at=last_commit, source="git_log")
    agg = _make_aggregator(
        [file],
        indexed_by={"context/team/h.md": ["context/INDEX.md"]},
        references=[ref],
        applied=applied,
        git_timestamps={"requirements/r1/doc.md": ts},
        now=now,
    )
    summaries = agg.aggregate()
    assert summaries[0].status == KnowledgeStatus.ACTIVE


# ---------------------------------------------------------------------------
# _compute_score 子项边界测试
# ---------------------------------------------------------------------------


def test_score_indexed_zero_and_two() -> None:
    """indexed=False → indexed_score=0；indexed=True → indexed_score=2。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    s_false = {"indexed": False, "reference_count": 0, "applied_signal_count": 0, "last_referenced_at": None}
    s_true = {"indexed": True, "reference_count": 0, "applied_signal_count": 0, "last_referenced_at": None}
    assert agg._compute_score(s_false, now) == 0
    assert agg._compute_score(s_true, now) == 2


def test_score_reference_count_cap() -> None:
    """reference_score = min(count*3, 30)：count=0/1/10/11。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    base = {"indexed": False, "applied_signal_count": 0, "last_referenced_at": None}
    assert agg._compute_score({**base, "reference_count": 0}, now) == 0
    assert agg._compute_score({**base, "reference_count": 1}, now) == 3
    assert agg._compute_score({**base, "reference_count": 10}, now) == 30
    assert agg._compute_score({**base, "reference_count": 11}, now) == 30  # cap


def test_score_applied_signal_count_cap() -> None:
    """applied_score = min(count*8, 40)：count=0/1/5/6。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    base = {"indexed": False, "reference_count": 0, "last_referenced_at": None}
    assert agg._compute_score({**base, "applied_signal_count": 0}, now) == 0
    assert agg._compute_score({**base, "applied_signal_count": 1}, now) == 8
    assert agg._compute_score({**base, "applied_signal_count": 5}, now) == 40
    assert agg._compute_score({**base, "applied_signal_count": 6}, now) == 40  # cap


def test_score_recency_boundaries() -> None:
    """recency_score 边界：None/30天/31天/90天/91天 → 0/10/5/5/0。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    base = {"indexed": False, "reference_count": 0, "applied_signal_count": 0}

    assert agg._compute_score({**base, "last_referenced_at": None}, now) == 0

    ref_30d = datetime(2026, 4, 20, tzinfo=timezone.utc)  # 30天前
    assert agg._compute_score({**base, "last_referenced_at": ref_30d}, now) == 10

    ref_31d = datetime(2026, 4, 19, tzinfo=timezone.utc)  # 31天前
    assert agg._compute_score({**base, "last_referenced_at": ref_31d}, now) == 5

    ref_90d = datetime(2026, 2, 19, tzinfo=timezone.utc)  # 90天前
    assert agg._compute_score({**base, "last_referenced_at": ref_90d}, now) == 5

    ref_91d = datetime(2026, 2, 18, tzinfo=timezone.utc)  # 91天前
    assert agg._compute_score({**base, "last_referenced_at": ref_91d}, now) == 0


def test_score_max_all_caps() -> None:
    """四子项全满时总分 = 82。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg = _make_aggregator([], now=now)
    ref_1d = datetime(2026, 5, 19, tzinfo=timezone.utc)
    s = {
        "indexed": True,
        "reference_count": 11,  # reference_score = 30（cap）
        "applied_signal_count": 6,  # applied_score = 40（cap）
        "last_referenced_at": ref_1d,  # recency = 10（30D）
    }
    assert agg._compute_score(s, now) == 82


# ---------------------------------------------------------------------------
# aggregate() 整链路冒烟测试
# ---------------------------------------------------------------------------


def test_aggregate_full_pipeline() -> None:
    """整链路冒烟：2个文件，验证长度/字段串联/时间戳/score范围/排序。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)

    file_a = _make_file("context/team/a.md")
    file_b = _make_file("context/team/b.md")

    indexed_by = {"context/team/a.md": ["context/INDEX.md"]}

    ref_a1 = _make_ref("context/team/a.md", source="requirements/r1/doc1.md", line=5)
    ref_a2 = _make_ref("context/team/a.md", source="requirements/r2/doc2.md", line=10)
    applied_a = _make_applied(ref_a1)

    ts_r1 = GitTimestamp(
        first_commit_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        last_commit_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        source="git_log",
    )
    ts_r2 = GitTimestamp(
        first_commit_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        last_commit_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        source="git_log",
    )
    ts_a = GitTimestamp(
        first_commit_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_commit_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        source="git_log",
    )

    agg = UsageAggregator(
        inventory=[file_a, file_b],
        index_result=_make_index_result(indexed_by=indexed_by),
        references=[ref_a1, ref_a2],
        applied=[applied_a],
        git_timestamps={
            "requirements/r1/doc1.md": ts_r1,
            "requirements/r2/doc2.md": ts_r2,
            "context/team/a.md": ts_a,
        },
        now=now,
    )
    summaries = agg.aggregate()

    assert len(summaries) == 2

    summary_a = next(s for s in summaries if s.path == "context/team/a.md")
    summary_b = next(s for s in summaries if s.path == "context/team/b.md")

    assert summary_a.indexed is True
    assert summary_a.index_paths == ["context/INDEX.md"]
    assert summary_a.reference_count == 2
    assert summary_a.applied_signal_count == 1

    assert summary_a.last_referenced_at == datetime(2026, 5, 15, tzinfo=timezone.utc)
    assert summary_a.first_referenced_at == datetime(2026, 2, 1, tzinfo=timezone.utc)

    assert summary_a.last_modified_at == datetime(2026, 5, 18, tzinfo=timezone.utc)
    assert summary_a.last_modified_at_source == "git_log"

    assert 0 <= summary_a.score <= 82
    assert 0 <= summary_b.score <= 82

    assert summary_a.reference_evidences == sorted(
        [ref_a1, ref_a2], key=lambda e: (e.source, e.line)
    )
    assert len(summary_a.applied_evidences) == 1

    assert summary_b.status == KnowledgeStatus.ORPHAN

    assert summaries[0].score >= summaries[1].score


def test_aggregate_last_modified_fallback_fs_mtime() -> None:
    """git_timestamps 无该文件条目时，last_modified_at 回退到 fs_mtime。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    fs_mtime = datetime(2026, 3, 15, tzinfo=timezone.utc)
    file = KnowledgeFile(
        path=Path("/fake/context/team/z.md"),
        rel_path="context/team/z.md",
        kind="team",
        size_bytes=50,
        fs_mtime=fs_mtime,
    )
    agg = _make_aggregator([file], git_timestamps={}, now=now)
    summaries = agg.aggregate()
    assert summaries[0].last_modified_at == fs_mtime
    assert summaries[0].last_modified_at_source == "fs_mtime"


def test_aggregate_output_length_equals_inventory() -> None:
    """输出长度恒等于 inventory 长度（含空 inventory）。"""
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    agg_empty = _make_aggregator([], now=now)
    assert agg_empty.aggregate() == []

    files = [_make_file(f"context/team/f{i}.md") for i in range(5)]
    agg = _make_aggregator(files, now=now)
    assert len(agg.aggregate()) == 5


# ---------------------------------------------------------------------------
# now 注入测试：同一数据 + 不同 now → recency_score 不同
# ---------------------------------------------------------------------------


def test_aggregate_now_injection_changes_recency() -> None:
    """now 注入：同一 last_referenced_at，传不同 now，recency_score 不同。"""
    file = _make_file("context/team/x.md")
    last_commit = datetime(2026, 4, 20, tzinfo=timezone.utc)

    ref = _make_ref("context/team/x.md", source="requirements/r1/doc.md", line=1)
    ts_ref = GitTimestamp(
        first_commit_at=last_commit,
        last_commit_at=last_commit,
        source="git_log",
    )

    def get_score(now: datetime) -> int:
        agg = UsageAggregator(
            inventory=[file],
            index_result=_make_index_result(),
            references=[ref],
            applied=[],
            git_timestamps={"requirements/r1/doc.md": ts_ref},
            now=now,
        )
        return agg.aggregate()[0].score

    score_30d = get_score(datetime(2026, 5, 20, tzinfo=timezone.utc))
    score_61d = get_score(datetime(2026, 6, 20, tzinfo=timezone.utc))
    score_92d = get_score(datetime(2026, 7, 21, tzinfo=timezone.utc))

    assert score_30d > score_61d > score_92d


# F-009-FU-F4 回归：fs_mtime 来源的 reference source 不参与 recency / first_referenced 计算


def test_aggregate_skips_fs_mtime_source_for_recency() -> None:
    """fs_mtime source 的 reference source 文件 → last/first_referenced_at 不被采纳，recency_score=0。"""
    file = _make_file("context/team/x.md")
    ref = _make_ref(target="context/team/x.md", source="requirements/r1/doc.md")
    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    ts_fs = GitTimestamp(
        first_commit_at=None,
        last_commit_at=now,
        source="fs_mtime",
    )

    agg = UsageAggregator(
        inventory=[file],
        index_result=_make_index_result(),
        references=[ref],
        applied=[],
        git_timestamps={"requirements/r1/doc.md": ts_fs},
        now=now,
    )
    summary = agg.aggregate()[0]

    assert summary.last_referenced_at is None
    assert summary.first_referenced_at is None
    assert summary.score == 3


def test_aggregate_mixed_git_log_and_fs_mtime_sources() -> None:
    """混合：git_log 来源参与 max；fs_mtime 来源即便时间更新也被跳过。"""
    file = _make_file("context/team/x.md")
    ref_a = _make_ref(target="context/team/x.md", source="requirements/ra/doc.md")
    ref_b = _make_ref(target="context/team/x.md", source="requirements/rb/doc.md")

    now = datetime(2026, 5, 20, tzinfo=timezone.utc)
    ts_a = GitTimestamp(
        first_commit_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        last_commit_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        source="git_log",
    )
    ts_b = GitTimestamp(
        first_commit_at=None,
        last_commit_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        source="fs_mtime",
    )

    agg = UsageAggregator(
        inventory=[file],
        index_result=_make_index_result(),
        references=[ref_a, ref_b],
        applied=[],
        git_timestamps={
            "requirements/ra/doc.md": ts_a,
            "requirements/rb/doc.md": ts_b,
        },
        now=now,
    )
    summary = agg.aggregate()[0]

    assert summary.last_referenced_at == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert summary.first_referenced_at == datetime(2026, 3, 1, tzinfo=timezone.utc)
