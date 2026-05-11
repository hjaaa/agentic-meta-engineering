"""tests/tools 共享 fixture（pytest conftest）。

把 scripts/lib 注入 sys.path，让 test_migrate_requirements.py 能直接 import。
风格与 tests/gates/conftest.py 一致。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = REPO_ROOT / "scripts" / "lib"

if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
