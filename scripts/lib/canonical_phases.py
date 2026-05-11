"""canonical phase 枚举的单一事实源加载器。

唯一事实源：context/team/engineering-spec/meta-schema.yaml `enums.phase`

任何门禁或 CLI 入口只要需要校验 phase 字符串是否合法，都必须用本模块；
禁止各处复制 phase-rules.md 表导致漂移。

设计动机：
  REQ-2026-003 排查发现，meta.yaml 的 `phase` 字段被写成 `technical-research`
  （应为 `tech-research`）后，门禁链上多处 vacuous pass（未知 phase 名静默通过）。
  本模块加载 schema 真名集合，让所有 R 函数与 plugin 都能 fail-closed。

REQ-2026-005 F-003 扩展：
  新增 load_adjacent_phases() / load_canonical_phases_ordered()，从 enums.phase
  有序列表推导前进相邻关系，给 runner _validate_phase_args 做"非法 phase 跳跃"校验。

REQ-2026-009 F-012 重命名（旧名 phase_enum.py）：
  "enum" 暗示静态常量集合，但本模块实际从 yaml 动态加载 + 缓存——名实不符。
  新名 canonical_phases.py 与函数族 load_canonical_phases / load_canonical_phases_ordered
  / load_adjacent_phases 命名空间统一。同期删除跨模块共享 dict（参考 plan.md D-016）；
  R 函数改 required_phases 显式参数注入避免双轨漂移。
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
META_SCHEMA_PATH = _REPO_ROOT / "context" / "team" / "engineering-spec" / "meta-schema.yaml"

_cached: frozenset[str] | None = None
# 有序缓存：保留 yaml 加载顺序，给 load_adjacent_phases / load_canonical_phases_ordered 用
_cached_ordered: tuple[str, ...] | None = None
_cached_adjacent: frozenset[tuple[str, str]] | None = None


def _load_phase_enum_list() -> list[str]:
    """读盘解析 meta-schema.yaml.enums.phase 列表（保留 yaml 顺序，不排序）。

    内部 helper；首次调用读盘，后续走 _cached_ordered 缓存。
    异常：FileNotFoundError / yaml.YAMLError 透传，调用方决定降级策略。
    """
    global _cached_ordered
    if _cached_ordered is not None:
        return list(_cached_ordered)
    with META_SCHEMA_PATH.open("r", encoding="utf-8") as f:
        schema = yaml.safe_load(f) or {}
    phases = (schema.get("enums") or {}).get("phase") or []
    # 防御：yaml 可能给出非 list 类型；强制转 list[str]
    ordered = [str(p) for p in phases]
    _cached_ordered = tuple(ordered)
    return ordered


def load_canonical_phases() -> frozenset[str]:
    """加载 canonical phase 枚举（首次调用读盘，后续走缓存）。

    返回：frozenset[str]，meta-schema.yaml.enums.phase 的全部合法值。
    异常：FileNotFoundError / yaml.YAMLError 透传，调用方决定降级策略。
    """
    global _cached
    if _cached is not None:
        return _cached
    _cached = frozenset(_load_phase_enum_list())
    return _cached


def load_canonical_phases_ordered() -> tuple[str, ...]:
    """加载 canonical phase 有序元组（保留 yaml 顺序）。

    用途：runner _validate_phase_args 需要 from/to 在 canonical 列表中的下标对比，
    判断是"前进方向"还是"回退方向"——回退方向不做相邻校验。
    """
    return tuple(_load_phase_enum_list())


def load_adjacent_phases() -> frozenset[tuple[str, str]]:
    """从 enums.phase 有序列表推导前进相邻关系。

    返回：frozenset[(prev, next)]，例如：
      {("bootstrap","definition"), ("definition","tech-research"),
       ("tech-research","outline-design"), ...}

    设计：仅前进方向。如 enums.phase = [a, b, c, d] → {(a,b), (b,c), (c,d)}。
    回退方向（如 d→a）不在返回集合中——回退由 runner 单独放行（rollback 用）。
    """
    global _cached_adjacent
    if _cached_adjacent is not None:
        return _cached_adjacent
    canonical = _load_phase_enum_list()
    pairs = (
        (canonical[i], canonical[i + 1])
        for i in range(len(canonical) - 1)
    )
    _cached_adjacent = frozenset(pairs)
    return _cached_adjacent


def reset_cache() -> None:
    """测试用：清空缓存以便 monkeypatch META_SCHEMA_PATH 后重新加载。"""
    global _cached, _cached_ordered, _cached_adjacent
    _cached = None
    _cached_ordered = None
    _cached_adjacent = None
