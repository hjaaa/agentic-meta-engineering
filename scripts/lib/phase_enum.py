"""canonical phase 枚举的单一事实源加载器。

唯一事实源：context/team/engineering-spec/meta-schema.yaml `enums.phase`

任何门禁或 CLI 入口只要需要校验 phase 字符串是否合法，都必须用本模块；
禁止各处复制 PHASE_REQUIREMENTS / phase-rules.md 表导致漂移。

设计动机：
  REQ-2026-003 排查发现，meta.yaml 的 `phase` 字段被写成 `technical-research`
  （应为 `tech-research`）后，门禁链上有两处 vacuous pass：
    1. scripts/lib/check_reviews.py:_r001_review_exists 用 PHASE_REQUIREMENTS.get(...)
       默认空 list → 未知 phase 名静默通过 R001
    2. scripts/gates/plugins/review_verdict.py 同样用 _PHASE_REQUIREMENTS 判定
       → 未知 phase 名直接返回 PASS
  本模块加载 schema 真名集合，让两处都能 fail-closed。
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
META_SCHEMA_PATH = _REPO_ROOT / "context" / "team" / "engineering-spec" / "meta-schema.yaml"

_cached: frozenset[str] | None = None


def load_canonical_phases() -> frozenset[str]:
    """加载 canonical phase 枚举（首次调用读盘，后续走缓存）。

    返回：frozenset[str]，meta-schema.yaml.enums.phase 的全部合法值。
    异常：FileNotFoundError / yaml.YAMLError 透传，调用方决定降级策略。
    """
    global _cached
    if _cached is not None:
        return _cached
    with META_SCHEMA_PATH.open("r", encoding="utf-8") as f:
        schema = yaml.safe_load(f) or {}
    phases = (schema.get("enums") or {}).get("phase") or []
    _cached = frozenset(phases)
    return _cached


def reset_cache() -> None:
    """测试用：清空缓存以便 monkeypatch META_SCHEMA_PATH 后重新加载。"""
    global _cached
    _cached = None
