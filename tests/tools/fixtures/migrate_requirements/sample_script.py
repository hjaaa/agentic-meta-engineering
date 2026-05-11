"""fixture: 含 requirements/REQ- 字面量引用的示例 Python 脚本。

包含：
  - 2 处 literal 字面量（第 8、11 行）
  - 1 处 f-string risky_unmapped（第 17 行）
  - 1 处 concat risky_unmapped（第 20 行）
"""
from pathlib import Path

# literal: 直接硬编码路径（自动改）
WORK_DIR = Path("requirements/REQ-2026-001/artifacts")

# literal: 另一处直接引用（自动改）
NOTES_FILE = Path("requirements/REQ-2026-001/notes.md")


def get_run_dir(req_id: str) -> Path:
    # f-string: risky_unmapped，建议改为 _resolve_run_dir(req_id)
    return Path(f"requirements/{req_id}/artifacts")


def get_plan_path(req_id: str) -> Path:
    # concat: risky_unmapped，建议改为 _resolve_run_dir(req_id)
    return Path("requirements/" + req_id + "/plan.md")
