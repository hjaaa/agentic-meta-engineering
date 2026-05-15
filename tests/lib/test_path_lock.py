"""tests/lib/test_path_lock.py — path_lock 单元测试（F-008 AC-05）。

覆盖 7 条 acceptance + 1 条性能测试：
  AC-1  acquire 首次取锁成功 → .lock JSON 含 pid / created_at / path_target
  AC-2  requirement 类 run → requirements/.locks/<id>.lock 是 symlink 指向实锁
  AC-3  release 后 .lock 删除；symlink 保留（dangling 容忍）
  AC-4  并发：进程 A 持锁，进程 B → raise LockBusyError（stderr 含目标串）
  AC-5  残锁：mock _is_pid_alive=False → 自动清理 + 重试一次成功
  AC-6  残锁 + 重试后仍冲突 → raise LockBusyError（不进入活锁）
  AC-7  atexit：sys.exit(0) → .lock 文件被删
  PERF  单次 acquire wall-clock ≤ 100ms
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import path_lock
from path_lock import LockBusyError, LockHandle, acquire, release


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> Path:
    """在 tmp_path 下建一个最小 repo 结构（runs/.locks + requirements/.locks）。"""
    (tmp_path / "runs" / ".locks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "requirements" / ".locks").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _lock_path(root: Path, run_id: str) -> Path:
    return root / "runs" / ".locks" / f"{run_id}.lock"


def _symlink_path(root: Path, run_id: str) -> Path:
    return root / "requirements" / ".locks" / f"{run_id}.lock"


def _read_lock_json(root: Path, run_id: str) -> dict:
    return json.loads(_lock_path(root, run_id).read_text(encoding="utf-8").strip())


# ---------------------------------------------------------------------------
# AC-1：acquire 首次取锁成功 → JSON 含必填字段
# ---------------------------------------------------------------------------

def test_acquire_success_lock_json(tmp_path: Path) -> None:
    """AC-1: acquire 首次成功 → .lock 文件 JSON 含 pid / created_at / path_target。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    handle = acquire(run_id, root)
    try:
        lp = _lock_path(root, run_id)
        assert lp.exists(), ".lock 文件应存在"

        data = _read_lock_json(root, run_id)
        assert data["pid"] == os.getpid(), "pid 应等于当前进程"
        # created_at 格式为 ISO8601（含 T 分隔符）
        assert "T" in data["created_at"], "created_at 应为 ISO8601 格式"
        # path_target 应为绝对路径
        assert os.path.isabs(data["path_target"]), "path_target 应为绝对路径"
    finally:
        release(handle)


# ---------------------------------------------------------------------------
# AC-2：requirement 类 run → symlink 存在且指向实锁
# ---------------------------------------------------------------------------

def test_acquire_req_run_creates_symlink(tmp_path: Path) -> None:
    """AC-2: requirement 类 run → requirements/.locks/<id>.lock 是 symlink 指向实锁。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    handle = acquire(run_id, root)
    try:
        sl = _symlink_path(root, run_id)
        assert os.path.islink(sl), "requirements/.locks/<id>.lock 应是 symlink"
        # readlink 结果应包含实锁文件名
        target = os.readlink(sl)
        assert run_id + ".lock" in target, f"symlink target 应包含 {run_id}.lock，实际: {target}"
    finally:
        release(handle)


def test_acquire_non_req_run_no_symlink(tmp_path: Path) -> None:
    """非 REQ- 类 run 不建 symlink。"""
    root = _make_repo(tmp_path)
    run_id = "RUN-2026-001"

    handle = acquire(run_id, root)
    try:
        assert handle.symlink_path is None
    finally:
        release(handle)


# ---------------------------------------------------------------------------
# AC-3：release 后 .lock 删除；symlink 保留（dangling）
# ---------------------------------------------------------------------------

def test_release_deletes_lock_keeps_symlink(tmp_path: Path) -> None:
    """AC-3: release → .lock 删除，symlink 保留（dangling 容忍）。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    handle = acquire(run_id, root)
    sl = _symlink_path(root, run_id)
    release(handle)

    assert not _lock_path(root, run_id).exists(), "release 后 .lock 文件应被删除"
    # symlink 仍存在（dangling）
    assert os.path.lexists(sl), "release 后 symlink 应仍存在（dangling 容忍）"
    assert not sl.exists(), "dangling symlink 不应 resolve 成功"


# ---------------------------------------------------------------------------
# AC-4：并发：同进程内模拟第二次 acquire 时 fcntl 冲突（用 fork-like 进程测试见 e2e）
# 此处通过 mock _try_fcntl_lock 模拟 BlockingIOError 场景，验证 LockBusyError 抛出
# ---------------------------------------------------------------------------

def test_acquire_busy_raises_lock_busy_error(tmp_path: Path) -> None:
    """AC-4: 模拟 fcntl 失败 + pid 存活 → 抛 LockBusyError 含正确 pid。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    # 先写一个假 .lock 文件（模拟持有者）
    lp = _lock_path(root, run_id)
    fake_pid = os.getpid()  # 用当前 pid（保证 _is_pid_alive=True）
    lock_data = {
        "pid": fake_pid,
        "created_at": "2026-05-15T10:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }
    lp.write_text(json.dumps(lock_data) + "\n", encoding="utf-8")

    # 模拟 _try_fcntl_lock 返回 False（锁冲突）
    with mock.patch.object(path_lock, "_try_fcntl_lock", return_value=False):
        with pytest.raises(LockBusyError) as exc_info:
            acquire(run_id, root)

    assert exc_info.value.pid == fake_pid
    assert "another continue is running" in str(exc_info.value)
    assert f"pid={fake_pid}" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC-5：残锁：mock _is_pid_alive=False → 自动清理 + 重试一次成功
# ---------------------------------------------------------------------------

def test_acquire_stale_lock_auto_cleanup(tmp_path: Path) -> None:
    """AC-5: mock _is_pid_alive=False → stale 残锁自动清理，重试一次取锁成功。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    # 写一个假 .lock（模拟残锁，pid 不存在）
    lp = _lock_path(root, run_id)
    dead_pid = 99999999  # 极大概率不存在的 pid
    lock_data = {
        "pid": dead_pid,
        "created_at": "2026-01-01T00:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }
    lp.write_text(json.dumps(lock_data) + "\n", encoding="utf-8")

    # 第一次 _try_fcntl_lock 返 False（模拟锁冲突），后续正常
    call_count = {"n": 0}
    original_try = path_lock._try_fcntl_lock

    def _mock_try(fd: int) -> bool:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return False  # 第一次失败
        return original_try(fd)  # 重试成功（因为 .lock 已被清理）

    with mock.patch.object(path_lock, "_try_fcntl_lock", side_effect=_mock_try):
        with mock.patch.object(path_lock, "_is_pid_alive", return_value=False):
            handle = acquire(run_id, root)

    try:
        # 取锁成功，.lock 应含当前 pid
        data = _read_lock_json(root, run_id)
        assert data["pid"] == os.getpid()
    finally:
        release(handle)


# ---------------------------------------------------------------------------
# AC-6：残锁 + 重试后仍冲突 → raise LockBusyError，不进入活锁
# ---------------------------------------------------------------------------

def test_acquire_stale_lock_retry_still_busy(tmp_path: Path) -> None:
    """AC-6: 残锁清理后重试仍失败 → raise LockBusyError，不进入活锁。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    lp = _lock_path(root, run_id)
    dead_pid = 99999999
    lock_data = {
        "pid": dead_pid,
        "created_at": "2026-01-01T00:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }
    lp.write_text(json.dumps(lock_data) + "\n", encoding="utf-8")

    # 两次 _try_fcntl_lock 都返 False（极小概率并发场景模拟）
    # 重试后 .lock 写有新的 pid（另一进程）
    new_pid = os.getpid()
    new_lock_data = {
        "pid": new_pid,
        "created_at": "2026-05-15T10:00:00+00:00",
        "path_target": str(lp.resolve()),
        "host": "Darwin-25.4.0",
    }

    call_count = {"n": 0}

    def _mock_try(fd: int) -> bool:
        call_count["n"] += 1
        if call_count["n"] == 2:
            # 重试前写入新持有者的 lock 信息
            lp.write_text(json.dumps(new_lock_data) + "\n", encoding="utf-8")
        return False

    with mock.patch.object(path_lock, "_try_fcntl_lock", side_effect=_mock_try):
        with mock.patch.object(path_lock, "_is_pid_alive", return_value=False):
            with pytest.raises(LockBusyError):
                acquire(run_id, root)

    # 确认只重试了 2 次（第一次 + 一次重试），不进入活锁
    assert call_count["n"] == 2, f"应只重试 2 次，实际 {call_count['n']} 次"


# ---------------------------------------------------------------------------
# AC-7：atexit：进程退出 → .lock 文件被删（用 subprocess 验证）
# ---------------------------------------------------------------------------

def test_atexit_cleanup_on_exit(tmp_path: Path) -> None:
    """AC-7: 进程 sys.exit(0) → .lock 文件被删（通过 subprocess + 共享 tmp_path 验证）。"""
    import subprocess

    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    script = f"""
import sys
sys.path.insert(0, {str(REPO_ROOT / "scripts" / "lib")!r})
from pathlib import Path
import path_lock

root = Path({str(root)!r})
handle = path_lock.acquire({run_id!r}, root)
# 不显式 release，依赖 atexit 清理
sys.exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"子进程应 exit 0，stderr={result.stderr}"
    assert not _lock_path(root, run_id).exists(), "atexit 应删除 .lock 文件"


# ---------------------------------------------------------------------------
# PERF：单次 acquire wall-clock ≤ 100ms
# ---------------------------------------------------------------------------

def test_acquire_under_100ms(tmp_path: Path) -> None:
    """PERF: 单次 acquire（无竞争）wall-clock ≤ 100ms。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    t0 = time.perf_counter()
    handle = acquire(run_id, root)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    release(handle)

    assert elapsed_ms < 100, f"acquire 耗时 {elapsed_ms:.1f}ms，超过 100ms 阈值"


# ---------------------------------------------------------------------------
# 幂等：release 多次安全
# ---------------------------------------------------------------------------

def test_release_idempotent(tmp_path: Path) -> None:
    """release 多次调用不应抛异常（幂等）。"""
    root = _make_repo(tmp_path)
    run_id = "REQ-2026-099"

    handle = acquire(run_id, root)
    release(handle)
    release(handle)  # 第二次 release 不应抛异常
