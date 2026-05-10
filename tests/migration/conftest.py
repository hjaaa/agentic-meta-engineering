"""tests/migration 共享 fixture loader（pytest conftest）。

与 tests/gates/conftest.py 风格一致：把 scripts/lib 和 scripts/gates 注入 sys.path，
让 migration 测试文件能直接 import check_reviews / plugins 等模块。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §8
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = REPO_ROOT / "scripts" / "lib"
_GATES_DIR = REPO_ROOT / "scripts" / "gates"

# scripts/lib 注入（check_reviews / common / save_review / phase_enum）
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# scripts/gates 注入（plugins.base / plugins.review_verdict_ci）
if str(_GATES_DIR) not in sys.path:
    sys.path.insert(0, str(_GATES_DIR))

# fixtures 目录常量供测试文件引用
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
