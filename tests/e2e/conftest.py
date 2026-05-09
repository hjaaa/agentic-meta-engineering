"""e2e 测试共享 fixture loader（pytest conftest）。

工具函数定义在 tests/e2e/fixtures/e2e_helpers.py（供测试文件直接 import）。
本文件只暴露 pytest fixture（供 @pytest.fixture 声明）。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §7.3.3
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 把 scripts/lib 和 fixtures 目录加入 sys.path，让所有 e2e 测试能直接 import
if str(REPO_ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
if str(REPO_ROOT / "tests" / "e2e" / "fixtures") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e" / "fixtures"))

# F1 fixture 路径见 e2e_helpers.F1_FIXTURE_DIR
