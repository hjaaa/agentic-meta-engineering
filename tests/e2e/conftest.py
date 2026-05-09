"""e2e 测试共享 fixture loader（pytest conftest）。

工具函数定义在 tests/e2e/fixtures/e2e_helpers.py（供测试文件直接 import）。
本文件只暴露 pytest fixture（供 @pytest.fixture 声明）。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §7.3.3
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# 把 scripts/lib 和 fixtures 目录加入 sys.path，让所有 e2e 测试能直接 import
if str(REPO_ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
if str(REPO_ROOT / "tests" / "e2e" / "fixtures") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests" / "e2e" / "fixtures"))

# F1 fixture 根目录（供 pytest fixture 返回）
F1_FIXTURE_DIR = REPO_ROOT / "tests" / "lib" / "fixtures" / "rollback" / "F1-cross-parent-child"


@pytest.fixture()
def f1_fixture_dir() -> Path:
    """返回 F1 fixture 目录路径（tests/lib/fixtures/rollback/F1-cross-parent-child/）。"""
    return F1_FIXTURE_DIR
