"""tests for scripts/lib/meta_set.py（Bug-5）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
META_SET = REPO_ROOT / "scripts" / "lib" / "meta_set.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(META_SET), *args], capture_output=True, text=True
    )


def _make_sandbox(tmp_path: Path) -> Path:
    """tmp_path 不在 REPO_ROOT 之下；路径白名单会拒绝。
    用 REPO_ROOT/requirements/REQ-2099-MS/ 作为 sandbox。
    """
    sandbox_dir = REPO_ROOT / "requirements" / "REQ-2099-MS"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    return sandbox_dir


def _cleanup_sandbox():
    import shutil

    sandbox_dir = REPO_ROOT / "requirements" / "REQ-2099-MS"
    shutil.rmtree(sandbox_dir, ignore_errors=True)


@pytest.fixture
def sandbox():
    sb = _make_sandbox(Path("/dev/null"))
    yield sb
    _cleanup_sandbox()


def test_simple_set(sandbox: Path):
    p = sandbox / "meta.yaml"
    p.write_text("phase: bootstrap\n", encoding="utf-8")
    proc = _run("--path", str(p), "--set", ".phase=tech-research")
    assert proc.returncode == 0, proc.stderr
    data = yaml.safe_load(p.read_text())
    assert data["phase"] == "tech-research"


def test_append(sandbox: Path):
    p = sandbox / "meta.yaml"
    p.write_text("gates_passed: []\n", encoding="utf-8")
    _run("--path", str(p), "--append", ".gates_passed=GATE-X")
    _run("--path", str(p), "--append", ".gates_passed=GATE-Y")
    data = yaml.safe_load(p.read_text())
    assert data["gates_passed"] == ["GATE-X", "GATE-Y"]


def test_append_creates_list(sandbox: Path):
    p = sandbox / "meta.yaml"
    p.write_text("phase: bootstrap\n", encoding="utf-8")
    _run("--path", str(p), "--append", ".gates_passed=GATE-X")
    data = yaml.safe_load(p.read_text())
    assert data["gates_passed"] == ["GATE-X"]


def test_set_json_array(sandbox: Path):
    p = sandbox / "meta.yaml"
    p.write_text("affected_modules: []\n", encoding="utf-8")
    proc = _run(
        "--path", str(p), "--set-json", '.affected_modules=["a", "b", "c"]'
    )
    assert proc.returncode == 0, proc.stderr
    data = yaml.safe_load(p.read_text())
    assert data["affected_modules"] == ["a", "b", "c"]


def test_multi_set_chain(sandbox: Path):
    p = sandbox / "meta.yaml"
    p.write_text("phase: testing\n", encoding="utf-8")
    proc = _run(
        "--path",
        str(p),
        "--set", ".archived_at=2026-05-21T15:00:00",
        "--set", ".outcome=shipped",
        "--set", ".phase=completed",
        "--set", ".workflow_status=completed",
        "--set", ".completed_at=2026-05-21T15:00:01",
    )
    assert proc.returncode == 0, proc.stderr
    data = yaml.safe_load(p.read_text())
    assert data["outcome"] == "shipped"
    assert data["phase"] == "completed"
    assert data["workflow_status"] == "completed"


def test_nested_key(sandbox: Path):
    p = sandbox / "meta.yaml"
    p.write_text("worktree:\n  enabled: true\n", encoding="utf-8")
    _run("--path", str(p), "--set", ".worktree.cleanup.removed_at=2026-05-21")
    data = yaml.safe_load(p.read_text())
    assert data["worktree"]["cleanup"]["removed_at"] == "2026-05-21"


def test_yaml_missing(tmp_path: Path):
    proc = _run("--path", str(REPO_ROOT / "requirements" / "REQ-2099-NOPE" / "meta.yaml"), "--set", ".x=y")
    assert proc.returncode == 1


def test_path_outside_allowlist(tmp_path: Path):
    """tmp_path 不在 requirements/ 或 runs/ 之下 → 拒绝"""
    p = tmp_path / "evil.yaml"
    p.write_text("a: b\n", encoding="utf-8")
    proc = _run("--path", str(p), "--set", ".a=z")
    assert proc.returncode == 2
    assert "白名单" in proc.stderr or "仓库根" in proc.stderr


def test_path_in_claude_dir():
    """`.claude/` 下 yaml 也应被拒绝"""
    p = REPO_ROOT / ".claude" / "tmp-meta-set-test.yaml"
    try:
        p.write_text("a: b\n", encoding="utf-8")
        proc = _run("--path", str(p), "--set", ".a=z")
        assert proc.returncode == 2
    finally:
        p.unlink(missing_ok=True)
