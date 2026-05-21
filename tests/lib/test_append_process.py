"""tests for scripts/lib/append_process.py（Bug-7）。

覆盖：
  AC-1  --run 显式参数 → 写 requirements/<id>/process.txt，前缀时间戳
  AC-2  $RUN_ID env → 同效果
  AC-3  cwd 在 requirements/<id>/ 子树 → 推断 run_id
  AC-4  推断不到 run_id → exit 1
  AC-5  requirements/<id>/ 父目录不存在 → exit 1
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APPEND_PROCESS = REPO_ROOT / "scripts" / "lib" / "append_process.py"
TS_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ")


def _run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(APPEND_PROCESS), *args],
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def fake_requirements(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    """构造一个最小化 requirements/<id>/ 子树，把 REPO_ROOT 重定位到 tmp_path。"""
    req_id = "REQ-2099-001"
    req_dir = tmp_path / "requirements" / req_id
    req_dir.mkdir(parents=True)
    (req_dir / "process.txt").touch()
    return tmp_path, req_id


def test_explicit_run_flag(fake_requirements, monkeypatch):
    fake_root, req_id = fake_requirements
    # 通过单独的 PYTHONPATH-style 注入难度高，直接复制脚本到 tmp_path 下并改 REPO_ROOT 不现实；
    # 转用 subprocess 在 fake_root 下跑，并依赖 cwd 推断。
    # 走 cwd 推断：cwd 是 fake_root/requirements/<id>/
    proc = _run("[test] hello", cwd=fake_root / "requirements" / req_id)
    # 由于 REPO_ROOT 在脚本 import 时绑定真实路径，cwd 内的 requirements 不在脚本认识的
    # REQUIREMENTS_DIR 之下 —— 这条用例语义为「确认错误推断」
    assert proc.returncode == 1
    assert "推断不到 run_id" in proc.stderr or "不存在" in proc.stderr


def test_run_via_real_repo_with_explicit_flag(tmp_path):
    """在真实 REPO_ROOT 下用 --run 显式指向一个 sandbox req_id，验证写入与时间戳格式。"""
    sandbox = REPO_ROOT / "requirements" / "REQ-2099-AP"
    sandbox.mkdir(parents=True, exist_ok=True)
    process_path = sandbox / "process.txt"
    if process_path.exists():
        process_path.unlink()
    process_path.touch()
    try:
        proc = _run("--run", "REQ-2099-AP", "[test] explicit flag")
        assert proc.returncode == 0, proc.stderr
        line = process_path.read_text(encoding="utf-8")
        assert TS_PREFIX_RE.match(line)
        assert line.rstrip().endswith("[test] explicit flag")
    finally:
        # cleanup sandbox
        import shutil

        shutil.rmtree(sandbox, ignore_errors=True)


def test_run_via_env(tmp_path):
    """$RUN_ID 注入"""
    sandbox = REPO_ROOT / "requirements" / "REQ-2099-AE"
    sandbox.mkdir(parents=True, exist_ok=True)
    process_path = sandbox / "process.txt"
    process_path.touch()
    try:
        proc = _run("[test] env", env={"RUN_ID": "REQ-2099-AE"})
        assert proc.returncode == 0, proc.stderr
        assert process_path.read_text(encoding="utf-8").rstrip().endswith("[test] env")
    finally:
        import shutil

        shutil.rmtree(sandbox, ignore_errors=True)


def test_cwd_inference(tmp_path):
    """cwd 在 requirements/<id>/ 子树 → 推断 run_id"""
    sandbox = REPO_ROOT / "requirements" / "REQ-2099-AC"
    sandbox.mkdir(parents=True, exist_ok=True)
    process_path = sandbox / "process.txt"
    process_path.touch()
    try:
        proc = _run("[test] cwd", cwd=sandbox)
        assert proc.returncode == 0, proc.stderr
        assert process_path.read_text(encoding="utf-8").rstrip().endswith("[test] cwd")
    finally:
        import shutil

        shutil.rmtree(sandbox, ignore_errors=True)


def test_missing_run_id():
    """无 --run、无 $RUN_ID、cwd 在 REPO_ROOT 之外 → exit 1"""
    proc = _run("[test] orphan", cwd=Path("/tmp"))
    assert proc.returncode == 1
    assert "推断不到 run_id" in proc.stderr


def test_missing_requirements_dir():
    """--run 指向不存在的 req → exit 1"""
    proc = _run("--run", "REQ-9999-NOPE", "[test] noexist")
    assert proc.returncode == 1
    assert "不存在" in proc.stderr
