"""tests/gates 共享 fixture：把 scripts/gates 注入 sys.path 以便直接 import。"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATES_DIR = _REPO_ROOT / "scripts" / "gates"

# 测试期把 gates 目录注入 sys.path（与 run.py 自身同样手法）
if str(_GATES_DIR) not in sys.path:
    sys.path.insert(0, str(_GATES_DIR))
