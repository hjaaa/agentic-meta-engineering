"""context_usage_aggregator — F-009 UsageAggregator 组件。

负责：
  - KnowledgeStatus 枚举
  - KnowledgeUsageSummary 数据载体 (frozen dataclass)
  - UsageAggregator: 聚合四路证据 + 评分 + 状态分类
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))



class KnowledgeStatus(str, Enum):
    """知识文件的利用状态分类。详见 detailed-design.md §KnowledgeStatus。"""

    ORPHAN = "orphan"
    NEEDS_REVIEW = "needs_review"
    VISIBLE_UNUSED = "visible_unused"
    HIGH_VALUE = "high_value"
    STALE_CANDIDATE = "stale_candidate"
    ACTIVE = "active"


@dataclass(frozen=True)
class KnowledgeUsageSummary:
    """单个知识文件的使用汇总。详见 detailed-design.md §KnowledgeUsageSummary（14 字段）。"""

    path: str
    kind: Literal["team", "project"]
    indexed: bool
    index_paths: list[str]
    reference_count: int
    applied_signal_count: int
    first_referenced_at: datetime | None
    last_referenced_at: datetime | None
    last_modified_at: datetime | None
    last_modified_at_source: Literal["git_log", "fs_mtime"]
    status: KnowledgeStatus
    score: int
    reference_evidences: list  # list[ReferenceEvidence]
    applied_evidences: list    # list[AppliedEvidence]


class UsageAggregator:
    """聚合所有证据 + 评分 + 状态分类。

    职责：
    - 把 ContextInventory / IndexGraph / EvidenceScanner / AppliedSignalClassifier
      四路结果与 git log 时间戳合并
    - 计算 usage_score（见 §评分规则）
    - 按状态分类规则归类（见 §状态机表）
    """

    # 评分上限（来源：requirement.md）
    INDEXED_WEIGHT: int = 2
    REFERENCE_WEIGHT: int = 3
    REFERENCE_CAP: int = 30
    APPLIED_WEIGHT: int = 8
    APPLIED_CAP: int = 40
    RECENCY_30D_SCORE: int = 10
    RECENCY_90D_SCORE: int = 5

    # 时间窗口（来源：requirement.md）
    STALE_THRESHOLD_DAYS: int = 90
    HIGH_VALUE_REFERENCE_MIN: int = 3  # [待用户确认]

    def __init__(
        self,
        inventory: list,        # list[KnowledgeFile]
        index_result: object,   # IndexGraphResult
        references: list,       # list[ReferenceEvidence]
        applied: list,          # list[AppliedEvidence]
        git_timestamps: dict,   # dict[str, GitTimestamp]
        now: datetime,
    ) -> None:
        self._inventory = inventory
        self._index_result = index_result
        self._references = references
        self._applied = applied
        self._git_timestamps = git_timestamps
        self._now = now

    def aggregate(self) -> list[KnowledgeUsageSummary]:
        """单次聚合。

        Returns:
            list[KnowledgeUsageSummary]，长度 == len(inventory)，按 score 降序 + rel_path 升序。

        幂等：纯计算。
        """
        ref_by_target, applied_by_target = self._build_lookup_indexes()

        results: list[KnowledgeUsageSummary] = []
        for file in self._inventory:
            rel = file.rel_path
            indexed_paths = self._index_result.indexed_by.get(rel, [])
            indexed = len(indexed_paths) > 0

            file_refs = ref_by_target.get(rel, [])
            reference_count = len(file_refs)

            file_applied = applied_by_target.get(rel, [])
            applied_signal_count = len(file_applied)

            last_referenced_at, first_referenced_at = self._resolve_timestamps(file_refs)

            # last_modified_at：优先 git_timestamps[rel].last_commit_at，回退 fs_mtime
            file_ts = self._git_timestamps.get(rel)
            if file_ts is not None:
                last_modified_at = file_ts.last_commit_at
                last_modified_at_source: Literal["git_log", "fs_mtime"] = file_ts.source
            else:
                last_modified_at = file.fs_mtime
                last_modified_at_source = "fs_mtime"

            partial: dict = {
                "indexed": indexed,
                "reference_count": reference_count,
                "applied_signal_count": applied_signal_count,
                "last_referenced_at": last_referenced_at,
            }
            score = self._compute_score(partial, self._now)
            status = self._classify_status(partial, self._now)

            sorted_refs = sorted(file_refs, key=lambda e: (e.source, e.line))
            sorted_applied = sorted(
                file_applied, key=lambda e: (e.reference.source, e.reference.line)
            )

            results.append(KnowledgeUsageSummary(
                path=rel,
                kind=file.kind,
                indexed=indexed,
                index_paths=indexed_paths,
                reference_count=reference_count,
                applied_signal_count=applied_signal_count,
                first_referenced_at=first_referenced_at,
                last_referenced_at=last_referenced_at,
                last_modified_at=last_modified_at,
                last_modified_at_source=last_modified_at_source,
                status=status,
                score=score,
                reference_evidences=sorted_refs,
                applied_evidences=sorted_applied,
            ))

        results.sort(key=lambda s: (-s.score, s.path))
        return results

    def _build_lookup_indexes(
        self,
    ) -> tuple[dict[str, list], dict[str, list]]:
        """预构建 target → refs 和 target → applied 索引，避免 O(N²) 遍历。"""
        ref_by_target: dict[str, list] = {}
        for ev in self._references:
            ref_by_target.setdefault(ev.target, []).append(ev)

        applied_by_target: dict[str, list] = {}
        for ev in self._applied:
            applied_by_target.setdefault(ev.reference.target, []).append(ev)

        return ref_by_target, applied_by_target

    def _resolve_timestamps(
        self, file_refs: list
    ) -> tuple[datetime | None, datetime | None]:
        """计算 last_referenced_at / first_referenced_at。

        仅采纳 source=="git_log" 的时间戳：fs_mtime 不参与 recency / first_referenced 计算。
        """
        ref_sources = {ev.source for ev in file_refs}
        last_referenced_at: datetime | None = None
        first_referenced_at: datetime | None = None

        for src in ref_sources:
            ts = self._git_timestamps.get(src)
            if ts is None or ts.source != "git_log":
                continue
            if ts.last_commit_at is not None:
                if last_referenced_at is None or ts.last_commit_at > last_referenced_at:
                    last_referenced_at = ts.last_commit_at
            if ts.first_commit_at is not None:
                if first_referenced_at is None or ts.first_commit_at < first_referenced_at:
                    first_referenced_at = ts.first_commit_at

        return last_referenced_at, first_referenced_at

    def _compute_score(self, s: dict, now: datetime) -> int:
        """评分计算，规则见 detailed-design.md §评分规则。

        s 字段：indexed / reference_count / applied_signal_count / last_referenced_at
        """
        indexed_score = self.INDEXED_WEIGHT if s["indexed"] else 0

        reference_score = min(
            s["reference_count"] * self.REFERENCE_WEIGHT,
            self.REFERENCE_CAP,
        )

        applied_score = min(
            s["applied_signal_count"] * self.APPLIED_WEIGHT,
            self.APPLIED_CAP,
        )

        recency_score = 0
        if s["last_referenced_at"] is not None:
            delta_days = (now - s["last_referenced_at"]).days
            if delta_days <= 30:
                recency_score = self.RECENCY_30D_SCORE
            elif delta_days <= 90:
                recency_score = self.RECENCY_90D_SCORE

        return indexed_score + reference_score + applied_score + recency_score

    def _classify_status(self, s: dict, now: datetime) -> KnowledgeStatus:
        """状态分类，规则见 detailed-design.md §状态机表。

        s 字段：indexed / reference_count / applied_signal_count / last_referenced_at
        判定按顺序逐条匹配，先匹配先归类。
        """
        if not s["indexed"]:
            if s["reference_count"] == 0:
                return KnowledgeStatus.ORPHAN
            else:
                return KnowledgeStatus.NEEDS_REVIEW

        if s["reference_count"] == 0:
            return KnowledgeStatus.VISIBLE_UNUSED

        if (s["applied_signal_count"] >= 1
                and s["reference_count"] >= self.HIGH_VALUE_REFERENCE_MIN):
            return KnowledgeStatus.HIGH_VALUE

        if s["last_referenced_at"] is not None:
            delta_days = (now - s["last_referenced_at"]).days
            if delta_days > self.STALE_THRESHOLD_DAYS:
                return KnowledgeStatus.STALE_CANDIDATE

        return KnowledgeStatus.ACTIVE
