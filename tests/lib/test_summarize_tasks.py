"""tests for scripts/lib/summarize_tasks.py（Bug-13）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARIZE = REPO_ROOT / "scripts" / "lib" / "summarize_tasks.py"


def _make_task(dir_: Path, name: str, complexity: str, status: str) -> None:
    (dir_ / f"{name}.md").write_text(
        f"---\nid: {name}\ncomplexity: {complexity}\nstatus: {status}\n---\n# {name}\n",
        encoding="utf-8",
    )


def _run(arg: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SUMMARIZE), arg],
        capture_output=True,
        text=True,
    )


def test_happy_path(tmp_path: Path):
    _make_task(tmp_path, "F-001", "light", "done")
    _make_task(tmp_path, "F-002", "medium", "in-progress")
    _make_task(tmp_path, "F-003", "medium", "pending")
    _make_task(tmp_path, "F-004", "heavy", "pending")
    proc = _run(str(tmp_path))
    assert proc.returncode == 0
    out = proc.stdout
    assert "total: 4" in out
    assert "light: 1" in out
    assert "medium: 2" in out
    assert "heavy: 1" in out
    assert "pending: 2" in out
    assert "in-progress: 1" in out
    assert "done: 1" in out


def test_unknown_buckets(tmp_path: Path):
    _make_task(tmp_path, "F-001", "exotic-level", "weirdo-state")
    proc = _run(str(tmp_path))
    assert proc.returncode == 0
    assert "unknown: 1" in proc.stdout


def test_no_frontmatter(tmp_path: Path):
    (tmp_path / "F-001.md").write_text("just text, no frontmatter\n", encoding="utf-8")
    proc = _run(str(tmp_path))
    assert proc.returncode == 0
    assert "total: 1" in proc.stdout
    assert "unknown: 1" in proc.stdout


def test_invalid_yaml(tmp_path: Path):
    (tmp_path / "F-001.md").write_text(
        "---\n  : invalid:\nyaml broken\n---\n", encoding="utf-8"
    )
    proc = _run(str(tmp_path))
    assert proc.returncode == 0
    assert "unknown" in proc.stdout


def test_missing_dir(tmp_path: Path):
    proc = _run(str(tmp_path / "noexist"))
    assert proc.returncode == 1
    assert "不存在或非目录" in proc.stderr


def test_empty_dir(tmp_path: Path):
    proc = _run(str(tmp_path))
    assert proc.returncode == 0
    assert "total: 0" in proc.stdout
