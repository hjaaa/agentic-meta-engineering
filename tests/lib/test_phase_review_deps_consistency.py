"""三处 _PHASE_REVIEW_DEPS dict 副本一致性测试（D-016 ADR 缓解）

防止未来新增 phase 时漏改 1 处导致静默漂移。

来源：REQ-2026-009 F-012 rev2 F-5/F-11 checker 发现三处本地副本缺机器同步保障。
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parents[2] / "scripts" / "lib"
_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "gates" / "plugins"

if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))
if str(_PLUGINS_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGINS_DIR))

from scripts.lib import check_reviews  # noqa: E402
from scripts.gates.plugins import review_verdict, review_verdict_ci  # noqa: E402


def test_should_equal_when_all_three_phase_review_deps_compared():
    """given_three_local_copies_when_compared_then_all_equal（防漂移回归）。"""
    assert check_reviews._PHASE_REVIEW_DEPS == review_verdict._PHASE_REVIEW_DEPS, (
        "check_reviews._PHASE_REVIEW_DEPS 与 review_verdict._PHASE_REVIEW_DEPS 不一致；"
        "新增 phase 时需同步 3 处副本"
    )
    assert review_verdict._PHASE_REVIEW_DEPS == review_verdict_ci._PHASE_REVIEW_DEPS, (
        "review_verdict._PHASE_REVIEW_DEPS 与 review_verdict_ci._PHASE_REVIEW_DEPS 不一致；"
        "新增 phase 时需同步 3 处副本"
    )
